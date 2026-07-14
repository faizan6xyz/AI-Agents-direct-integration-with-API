import os
import re
import time
import base64
import pickle
import logging
import mimetypes
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
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']  # read + send + labels
TOKEN_PATH = 'Gmail/token.pickle'
CLIENT_SECRET_PATH = 'Gmail/ss.json'
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024   # Gmail's hard cap per message
EMAIL_ADDR_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HEADER_INJECTION_RE = re.compile(r"[\r\n]")  # CRLF -> injected headers/Bcc
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503}

def get_service():
    if not os.path.exists(CLIENT_SECRET_PATH):
        raise FileNotFoundError(
            f"Client secret file not found at '{CLIENT_SECRET_PATH}'. "
            "Download it from Google Cloud Console and place it there."
        )
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
    return build('gmail', 'v1', credentials=creds)

def _validate_email_address(address: str, label: str = "recipient") -> None:
    if not address or not EMAIL_ADDR_RE.match(address.strip()):
        raise ValueError(f"Invalid {label} email address: {address!r}")
    if HEADER_INJECTION_RE.search(address):
        raise ValueError(f"{label} contains invalid characters (possible header injection).")

def _validate_header_value(value: str, label: str) -> None:
    if value and HEADER_INJECTION_RE.search(value):
        raise ValueError(f"{label} contains newline characters, which is not allowed.")

def _validate_attachment(path: str) -> str:
    resolved = os.path.realpath(path)
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"Attachment not found: {path}")
    size = os.path.getsize(resolved)
    if size > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"Attachment '{path}' is {size / (1024*1024):.1f} MB, which exceeds "
            f"Gmail's {MAX_ATTACHMENT_BYTES / (1024*1024):.0f} MB per-message limit."
        )
    return resolved

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
            decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
        except Exception:
            return plain_parts, html_parts
        if mime_type == 'text/plain':
            plain_parts.append(decoded)
        elif mime_type == 'text/html':
            html_parts.append(decoded)
    return plain_parts, html_parts

def get_email_body(payload) -> str:
    plain_parts, html_parts = _extract_body_parts(payload)
    if plain_parts:
        return "\n".join(plain_parts)
    if html_parts:
        return "\n".join(html_parts)
    return "No body content found."

def list_messages(service, query='is:unread', max_results=10, all_pages=False, verbose=True) -> list[dict]:
    parsed = []
    page_token = None
    fetched = 0
    max_pages = 20 if all_pages else 1
    for _ in range(max_pages):
        list_kwargs = {"userId": "me", "q": query, "maxResults": max_results}
        if page_token:
            list_kwargs["pageToken"] = page_token
        results = _with_retry(service.users().messages().list, **list_kwargs)
        messages = results.get('messages', [])
        for msg in messages:
            full = _with_retry(service.users().messages().get,
                                userId='me', id=msg['id'], format='full')
            headers = full['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
            body = get_email_body(full['payload'])
            entry = {"id": msg['id'], "from": sender, "subject": subject, "body": body}
            parsed.append(entry)
            fetched += 1
            if verbose:
                print(f"From: {sender} | Subject: {subject} | Body: {body}")
        page_token = results.get('nextPageToken')
        if not page_token or not all_pages:
            break
    return parsed

def send_message(service, to, subject, body_text):
    _validate_email_address(to)
    _validate_header_value(subject, "subject")
    message = MIMEText(body_text)
    message['to'] = to
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return _with_retry(service.users().messages().send, userId='me', body={'raw': raw})

def send_message_with_attachments(service, to, subject, body_text, file_paths):
    _validate_email_address(to)
    _validate_header_value(subject, "subject")
    resolved_paths = [_validate_attachment(p) for p in file_paths]
    message = MIMEMultipart()
    message['to'] = to
    message['subject'] = subject
    message.attach(MIMEText(body_text))
    total_size = 0
    for path in resolved_paths:
        size = os.path.getsize(path)
        total_size += size
        if total_size > MAX_ATTACHMENT_BYTES:
            raise ValueError(
                f"Combined attachment size exceeds Gmail's "
                f"{MAX_ATTACHMENT_BYTES / (1024*1024):.0f} MB limit."
            )
        content_type, _ = mimetypes.guess_type(path)
        maintype, subtype = (content_type.split('/', 1) if content_type
                              else ('application', 'octet-stream'))
        with open(path, 'rb') as f:
            part = MIMEApplication(f.read(), _subtype=subtype, Name=os.path.basename(path))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(path)}"'
        message.attach(part)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return _with_retry(service.users().messages().send, userId='me', body={'raw': raw})

def mark_as_read(service, message_id: str) -> dict:
    return _with_retry(service.users().messages().modify, userId='me', id=message_id,
                        body={'removeLabelIds': ['UNREAD']})

def mark_as_unread(service, message_id: str) -> dict:
    return _with_retry(service.users().messages().modify, userId='me', id=message_id,
                        body={'addLabelIds': ['UNREAD']})

def archive_message(service, message_id: str) -> dict:
    return _with_retry(service.users().messages().modify, userId='me', id=message_id,
                        body={'removeLabelIds': ['INBOX']})

def trash_message(service, message_id: str, confirm: bool = False) -> dict:
    if not confirm:
        raise ValueError("trash_message requires confirm=True to proceed.")
    return _with_retry(service.users().messages().trash, userId='me', id=message_id)

def download_attachments(service, message_id: str, out_dir: str = "attachments") -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    full = _with_retry(service.users().messages().get, userId='me', id=message_id, format='full')
    saved = []
    def walk(payload):
        if 'parts' in payload:
            for part in payload['parts']:
                walk(part)
        else:
            filename = payload.get('filename')
            body = payload.get('body', {})
            attachment_id = body.get('attachmentId')
            if filename and attachment_id:
                att = _with_retry(service.users().messages().attachments().get,
                                   userId='me', messageId=message_id, id=attachment_id)
                data = base64.urlsafe_b64decode(att['data'])
                if len(data) > MAX_ATTACHMENT_BYTES:
                    logger.warning(f"Skipping '{filename}': exceeds size safety limit.")
                    return
                # Sanitize filename to prevent writing outside out_dir
                safe_name = os.path.basename(filename)
                out_path = os.path.join(out_dir, safe_name)
                with open(out_path, 'wb') as f:
                    f.write(data)
                saved.append(out_path)
    walk(full['payload'])
    return saved

if __name__ == "__main__":
    service = get_service()
    list_messages(service, query='is:unread', max_results=10)