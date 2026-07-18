import os , re , time , base64 , pickle , logging , mimetypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gmail_client")
GMAIL_SCOPES = os.environ.get("GMAIL_SCOPES")
if not GMAIL_SCOPES or not GMAIL_SCOPES.strip():
    raise EnvironmentError("GMAIL_SCOPES environment variable is not set or empty.")
SCOPES = [scope.strip() for scope in GMAIL_SCOPES.split(",") if scope.strip()]
if not SCOPES:
    raise EnvironmentError("GMAIL_SCOPES did not contain any valid scopes.")
TOKEN_PATH = 'Gmail/token.pickle'
CLIENT_SECRET_PATH = 'Gmail/ss.json'
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_TOTAL_SEND_BYTES = 25 * 1024 * 1024
MAX_RESULTS_CAP = 500
MAX_QUERY_LENGTH = 2048
EMAIL_ADDR_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HEADER_INJECTION_RE = re.compile(r"[\r\n]")
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503}
BLOCKED_ATTACHMENT_EXTENSIONS = {
    '.exe', '.bat', '.cmd', '.com', '.scr', '.msi', '.ps1', '.vbs', '.js',
    '.jar', '.sh', '.dll', '.pif', '.gadget', '.wsf', '.hta'}

def get_service():
    if not os.path.exists(CLIENT_SECRET_PATH):
        raise FileNotFoundError(f"Client secret file not found at '{CLIENT_SECRET_PATH}'. "
            "Download it from Google Cloud Console and place it there.")
    if os.path.getsize(CLIENT_SECRET_PATH) == 0:
        raise ValueError(f"Client secret file at '{CLIENT_SECRET_PATH}' is empty.")
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        os.makedirs(os.path.dirname(TOKEN_PATH) or ".", exist_ok=True)
        with open(TOKEN_PATH, 'wb') as f:
            pickle.dump(creds, f)
        try:
            os.chmod(TOKEN_PATH, 0o600)
        except OSError:
            logger.warning(f"Could not set restrictive permissions on {TOKEN_PATH}")
    if set(SCOPES) - set(getattr(creds, 'scopes', None) or SCOPES):
        logger.warning("Stored credentials may not cover all requested scopes.")
    return build('gmail', 'v1', credentials=creds)

def _validate_email_address(address: str, label: str = "recipient") -> None:
    if not address or not isinstance(address, str):
        raise ValueError(f"Invalid {label} email address: {address!r}")
    address = address.strip()
    if not EMAIL_ADDR_RE.match(address):
        raise ValueError(f"Invalid {label} email address: {address!r}")
    if HEADER_INJECTION_RE.search(address):
        raise ValueError(f"{label} contains invalid characters (possible header injection).")

def _validate_header_value(value: str, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    if HEADER_INJECTION_RE.search(value):
        raise ValueError(f"{label} contains newline characters, which is not allowed.")

def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise ValueError("query must be a string.")
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"query exceeds maximum length of {MAX_QUERY_LENGTH} characters.")
    return query

def _validate_max_results(max_results: int) -> int:
    if not isinstance(max_results, int) or isinstance(max_results, bool):
        raise ValueError("max_results must be an integer.")
    if max_results <= 0:
        raise ValueError("max_results must be positive.")
    if max_results > MAX_RESULTS_CAP:
        raise ValueError(f"max_results cannot exceed {MAX_RESULTS_CAP}.")
    return max_results

def _validate_attachment(path: str, base_dir: str = None) -> str:   
    resolved = os.path.realpath(path)
    if base_dir is not None:
        base_resolved = os.path.realpath(base_dir)
        if os.path.commonpath([resolved, base_resolved]) != base_resolved:
            raise ValueError(f"Attachment path '{path}' resolves outside the allowed directory.")
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"Attachment not found: {path}")
    if os.path.islink(path):
        raise ValueError(f"Attachment '{path}' is a symlink, which is not allowed.")
    size = os.path.getsize(resolved)
    if size == 0:
        raise ValueError(f"Attachment '{path}' is empty.")
    if size > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"Attachment '{path}' is {size / (1024*1024):.1f} MB, which exceeds "
            f"Gmail's {MAX_ATTACHMENT_BYTES / (1024*1024):.0f} MB per-message limit.")
    return resolved

def _safe_output_path(out_dir: str, filename: str) -> str:
    safe_name = os.path.basename(filename or "")
    if not safe_name or safe_name in ('.', '..'):
        raise ValueError(f"Unsafe or empty attachment filename: {filename!r}")
    out_dir_resolved = os.path.realpath(out_dir)
    candidate = os.path.realpath(os.path.join(out_dir_resolved, safe_name))
    if os.path.commonpath([candidate, out_dir_resolved]) != out_dir_resolved:
        raise ValueError(f"Attachment filename '{filename}' resolves outside the output directory.")
    return candidate

def _with_retry(func, *args, **kwargs):
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs).execute()
        except HttpError as e:
            status = getattr(e, "status_code", None) or getattr(e.resp, "status", None)
            if status in RETRYABLE_HTTP_STATUSES and attempt < MAX_RETRIES:
                logger.warning(f"Gmail API error {status} on attempt {attempt}/{MAX_RETRIES}, retrying")
                time.sleep(RETRY_BACKOFF_BASE ** attempt)
                last_exc = e
                continue
            raise
    raise last_exc

def _extract_body_parts(payload, plain_parts=None, html_parts=None):
    if plain_parts is None:
        plain_parts, html_parts = [], []
    mime_type = payload.get('mimeType', '')
    if 'parts' in payload:
        for part in payload['parts']:
            _extract_body_parts(part, plain_parts, html_parts)
    else:
        data = payload.get('body', {}).get('data', '')
        if not data:
            return plain_parts, html_parts
        try:
            decoded = base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)).decode('utf-8', errors='replace')
        except Exception as e:
            logger.warning(f"Failed to decode body part: {e}")
            return plain_parts, html_parts
        if mime_type == 'text/plain':
            plain_parts.append(decoded)
        elif mime_type == 'text/html':
            html_parts.append(decoded)
    return plain_parts, html_parts

def get_email_body(payload) -> str:
    if not payload or not isinstance(payload, dict):
        return "No body content found."
    plain_parts, html_parts = _extract_body_parts(payload)
    if plain_parts:
        return "\n".join(plain_parts)
    if html_parts:
        return "\n".join(html_parts)
    return "No body content found."

def list_messages(service, query='is:unread', max_results=10, all_pages=False, verbose=True) -> list[dict]:
    query = _validate_query(query)
    max_results = _validate_max_results(max_results)
    parsed = []
    page_token = None
    max_pages = 20 if all_pages else 1
    for _ in range(max_pages):
        list_kwargs = {"userId": "me", "q": query, "maxResults": max_results}
        if page_token:
            list_kwargs["pageToken"] = page_token
        results = _with_retry(service.users().messages().list, **list_kwargs)
        messages = results.get('messages', [])
        for msg in messages:
            full = _with_retry(service.users().messages().get, userId='me', id=msg['id'], format='full')
            headers = full.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
            body = get_email_body(full.get('payload'))
            entry = {"id": msg['id'], "from": sender, "subject": subject, "body": body}
            parsed.append(entry)
            if verbose:
                print(f"From: {sender} | Subject: {subject} | Body: {body}")
        page_token = results.get('nextPageToken')
        if not page_token or not all_pages:
            break
    return parsed

def send_message(service, to, subject, body_text):
    _validate_email_address(to)
    _validate_header_value(subject, "subject")
    _validate_header_value(body_text, "body_text")
    message = MIMEText(body_text or "")
    message['to'] = to
    message['subject'] = subject or ""
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return _with_retry(service.users().messages().send, userId='me', body={'raw': raw})

def send_message_with_attachments(service, to, subject, body_text, file_paths, allowed_dir=None):
    _validate_email_address(to)
    _validate_header_value(subject, "subject")
    _validate_header_value(body_text, "body_text")
    if not file_paths:
        raise ValueError("file_paths must contain at least one attachment.")
    resolved_paths = [_validate_attachment(p, base_dir=allowed_dir) for p in file_paths]
    total_size = sum(os.path.getsize(p) for p in resolved_paths)
    if total_size > MAX_TOTAL_SEND_BYTES:
        raise ValueError(f"Combined attachment size ({total_size / (1024*1024):.1f} MB) exceeds Gmail's "
            f"{MAX_TOTAL_SEND_BYTES / (1024*1024):.0f} MB limit.")
    message = MIMEMultipart()
    message['to'] = to
    message['subject'] = subject or ""
    message.attach(MIMEText(body_text or ""))
    for path in resolved_paths:
        content_type, _ = mimetypes.guess_type(path)
        maintype, subtype = (content_type.split('/', 1) if content_type else ('application', 'octet-stream'))
        with open(path, 'rb') as f:
            data = f.read()
        part = MIMEApplication(data, _subtype=subtype, Name=os.path.basename(path))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(path)}"'
        message.attach(part)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    if len(raw) > MAX_ATTACHMENT_BYTES * 2:
        raise ValueError("Encoded message size exceeds safe transmission limits.")
    return _with_retry(service.users().messages().send, userId='me', body={'raw': raw})

def mark_as_read(service, message_id: str) -> dict:
    if not message_id or not isinstance(message_id, str):
        raise ValueError("message_id must be a non-empty string.")
    return _with_retry(service.users().messages().modify, userId='me', id=message_id,body={'removeLabelIds': ['UNREAD']})

def mark_as_unread(service, message_id: str) -> dict:
    if not message_id or not isinstance(message_id, str):
        raise ValueError("message_id must be a non-empty string.")
    return _with_retry(service.users().messages().modify, userId='me', id=message_id,body={'addLabelIds': ['UNREAD']})

def archive_message(service, message_id: str) -> dict:
    if not message_id or not isinstance(message_id, str):
        raise ValueError("message_id must be a non-empty string.")
    return _with_retry(service.users().messages().modify, userId='me', id=message_id,body={'removeLabelIds': ['INBOX']})

def trash_message(service, message_id: str, confirm: bool = False) -> dict:
    if not message_id or not isinstance(message_id, str):
        raise ValueError("message_id must be a non-empty string.")
    if not confirm:
        raise ValueError("trash_message requires confirm=True to proceed.")
    return _with_retry(service.users().messages().trash, userId='me', id=message_id)

def download_attachments(service, message_id: str, out_dir: str = "attachments",allow_executable_types: bool = False) -> list[str]:
    if not message_id or not isinstance(message_id, str):
        raise ValueError("message_id must be a non-empty string.")
    os.makedirs(out_dir, exist_ok=True)
    full = _with_retry(service.users().messages().get, userId='me', id=message_id, format='full')
    saved = []
    skipped = []
    def walk(payload):
        if not payload or not isinstance(payload, dict):
            return
        if 'parts' in payload:
            for part in payload['parts']:
                walk(part)
            return
        filename = payload.get('filename')
        body = payload.get('body', {})
        attachment_id = body.get('attachmentId')
        if not filename or not attachment_id:
            return
        ext = os.path.splitext(filename)[1].lower()
        if ext in BLOCKED_ATTACHMENT_EXTENSIONS and not allow_executable_types:
            logger.warning(f"Skipping '{filename}': potentially dangerous file type ({ext}).")
            skipped.append(filename)
            return
        estimated_size = body.get('size')
        if isinstance(estimated_size, int) and estimated_size > MAX_ATTACHMENT_BYTES:
            logger.warning(f"Skipping '{filename}': reported size exceeds safety limit.")
            skipped.append(filename)
            return
        out_path = _safe_output_path(out_dir, filename)
        att = _with_retry(service.users().messages().attachments().get,userId='me', messageId=message_id, id=attachment_id)
        data = base64.urlsafe_b64decode(att['data'] + '=' * (-len(att['data']) % 4))
        if len(data) > MAX_ATTACHMENT_BYTES:
            logger.warning(f"Skipping '{filename}': decoded size exceeds safety limit.")
            skipped.append(filename)
            return
        if len(data) == 0:
            logger.warning(f"Skipping '{filename}': attachment is empty.")
            skipped.append(filename)
            return
        with open(out_path, 'wb') as f:
            f.write(data)
        saved.append(out_path)
    walk(full.get('payload'))
    if skipped:
        logger.info(f"Skipped {len(skipped)} attachment(s): {skipped}")
    return saved

if __name__ == "__main__":
    service = get_service()
    list_messages(service, query='is:unread', max_results=10)