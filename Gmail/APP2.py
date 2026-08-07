import os
import re
import logging
from functools import wraps
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify ,redirect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import Gmail.Read_mails as gc  # rename to match your actual module filename
import authnew as au
from googleapiclient.discovery import build
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gmail_api")
API_KEY = os.environ.get("GMAIL_API_KEY")  # set this in env, required
MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_MB = 15
app.config['MAX_CONTENT_LENGTH'] = MAX_ATTACHMENT_MB * MAX_ATTACHMENTS * 1024 * 1024
ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.doc', '.docx', '.xlsx', '.csv', '.txt', '.zip'}
UPLOAD_ROOT = os.path.abspath('uploads')
ATTACH_ROOT = os.path.abspath('attachments')
app.secret_key = os.environ["FLASK_SECRET_KEY"]
serializer = URLSafeTimedSerializer(app.secret_key)
STATE_MAX_AGE = 600  # seconds
MESSAGE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{5,50}$')
USER_ID_RE = re.compile(r'^[a-zA-Z0-9_.@-]{1,100}$')
LABEL_NAME_RE = re.compile(r'^[\w\s/.-]{1,100}$')
limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"])

def require_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not API_KEY:
            logger.error("GMAIL_API_KEY not configured on server")
            return jsonify({"error": "server misconfigured"}), 500
        provided = request.headers.get("X-API-Key")
        if not provided or provided != API_KEY:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

def get_valid_user_id():
    token = request.args.get("token")
    tokench = au.process(token=token)
    if not tokench["status"]:
        return None
    user_id = tokench['user_id']
    if not user_id or not USER_ID_RE.match(user_id):
        return None
    return user_id

def safe_error(e, status=400):
    logger.exception("request failed")
    return jsonify({"error": "request failed"}), status

def is_allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS

@app.route("/connect-gmail")
def connect_gmail():
    token = request.args.get("token")
    tokench = au.process(token=token)
    if not tokench["status"] :
        return jsonify({"status": "failed" , "reason": tokench["reason"]})
    user_id = tokench['user_id']
    state = serializer.dumps(user_id)
    flow = gc.build_flow()
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state)
    return redirect(auth_url)

@app.route("/oauth/gmail/callback")
def gmail_oauth_callback():
    state = request.args.get("state")
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "missing code"}), 400
    if not state:
        return jsonify({"error": "missing state"}), 400
    try:
        user_id = serializer.loads(state, max_age=STATE_MAX_AGE)
    except SignatureExpired:
        return jsonify({"error": "state expired, please reconnect"}), 400
    except BadSignature:
        return jsonify({"error": "invalid state"}), 400
    flow = gc.build_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    service = build('gmail', 'v1', credentials=creds)
    email_addr = service.users().getProfile(userId='me').execute()['emailAddress']
    gc.save_tokens(user_id, creds, email_addr=email_addr)
    return jsonify({"status": "connected", "email": email_addr})

@app.route('/messages', methods=['GET'])
@limiter.limit("30 per minute")
@require_api_key
def list_messages():
    user_id = get_valid_user_id()
    if not user_id:
        return jsonify({"error": "valid 'user_id' is required"}), 400
    query = request.args.get('q', 'is:unread')[:200]
    try:
        max_results = int(request.args.get('max_results', 10))
    except ValueError:
        return jsonify({"error": "'max_results' must be an integer"}), 400
    max_results = max(1, min(max_results, 100))
    all_pages = request.args.get('all_pages', 'false').lower() == 'true'
    try:
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        messages = gc.list_messages(service, query=query, max_results=max_results, all_pages=all_pages, verbose=False)
        return jsonify({"count": len(messages), "messages": messages})
    except Exception as e:
        return safe_error(e)

@app.route('/messages/send', methods=['POST'])
@limiter.limit("20 per minute")
@require_api_key
def send_message():
    user_id = get_valid_user_id()
    if not user_id:
        return jsonify({"error": "valid 'user_id' is required"}), 400
    data = request.get_json(silent=True) or {}
    to = data.get('to')
    subject = str(data.get('subject', ''))[:300]
    body_text = str(data.get('body_text', ''))[:50000]
    name = str(data.get('name', ''))[:200]
    if not to or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', to):
        return jsonify({"error": "a valid 'to' email is required"}), 400
    try:
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        result = gc.send_message(service, to, subject, body_text, name)
        return jsonify({"id": result.get('id'), "threadId": result.get('threadId')})
    except Exception as e:
        return safe_error(e)

@app.route('/messages/send-with-attachments', methods=['POST'])
@limiter.limit("10 per minute")
@require_api_key
def send_message_with_attachments():
    user_id = get_valid_user_id()
    if not user_id:
        return jsonify({"error": "valid 'user_id' is required"}), 400
    to = request.form.get('to')
    subject = str(request.form.get('subject', ''))[:300]
    body_text = str(request.form.get('body_text', ''))[:50000]
    name = str(request.form.get('name', ''))[:200]
    if not to or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', to):
        return jsonify({"error": "a valid 'to' email is required"}), 400
    files = request.files.getlist('attachments')
    if not files or len(files) > MAX_ATTACHMENTS:
        return jsonify({"error": f"between 1 and {MAX_ATTACHMENTS} attachments required"}), 400
    upload_dir = os.path.join(UPLOAD_ROOT, 'tmp', secure_filename(user_id))
    os.makedirs(upload_dir, exist_ok=True)
    saved_paths = []
    try:
        for f in files:
            filename = secure_filename(f.filename or '')
            if not filename or not is_allowed_file(filename):
                return jsonify({"error": f"file type not allowed: {f.filename}"}), 400
            path = os.path.join(upload_dir, filename)
            if not os.path.abspath(path).startswith(upload_dir):
                return jsonify({"error": "invalid file path"}), 400
            f.save(path)
            saved_paths.append(path)
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        result = gc.send_message_with_attachments(service, to, subject, body_text, saved_paths, name=name, allowed_dir=upload_dir)
        return jsonify({"id": result.get('id'), "threadId": result.get('threadId')})
    except Exception as e:
        return safe_error(e)
    finally:
        for p in saved_paths:
            if os.path.exists(p):
                os.remove(p)

@app.route('/messages/<message_id>/read', methods=['POST'])
@limiter.limit("60 per minute")
@require_api_key
def mark_as_read(message_id):
    user_id = get_valid_user_id()
    if not user_id or not MESSAGE_ID_RE.match(message_id):
        return jsonify({"error": "valid 'user_id' and message_id are required"}), 400
    try:
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        result = gc.mark_as_read(service, message_id)
        return jsonify(result)
    except Exception as e:
        return safe_error(e)

@app.route('/messages/<message_id>/unread', methods=['POST'])
@limiter.limit("60 per minute")
@require_api_key
def mark_as_unread(message_id):
    user_id = get_valid_user_id()
    if not user_id or not MESSAGE_ID_RE.match(message_id):
        return jsonify({"error": "valid 'user_id' and message_id are required"}), 400
    try:
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        result = gc.mark_as_unread(service, message_id)
        return jsonify(result)
    except Exception as e:
        return safe_error(e)

@app.route('/messages/<message_id>/attachments', methods=['GET'])
@limiter.limit("20 per minute")
@require_api_key
def download_attachments(message_id):
    user_id = get_valid_user_id()
    if not user_id or not MESSAGE_ID_RE.match(message_id):
        return jsonify({"error": "valid 'user_id' and message_id are required"}), 400
    out_dir = os.path.join(ATTACH_ROOT, secure_filename(user_id), secure_filename(message_id))
    if not os.path.abspath(out_dir).startswith(ATTACH_ROOT):
        return jsonify({"error": "invalid output path"}), 400
    try:
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        saved = gc.download_attachments(service, message_id, out_dir=out_dir)
        return jsonify({"saved_files": saved})
    except Exception as e:
        return safe_error(e)

@app.route('/filters', methods=['GET'])
@limiter.limit("30 per minute")
@require_api_key
def list_filters():
    user_id = get_valid_user_id()
    if not user_id:
        return jsonify({"error": "valid 'user_id' is required"}), 400
    try:
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        return jsonify(gc.list_filters(service))
    except Exception as e:
        return safe_error(e)

@app.route('/filters', methods=['POST'])
@limiter.limit("15 per minute")
@require_api_key
def create_filter():
    user_id = get_valid_user_id()
    if not user_id:
        return jsonify({"error": "valid 'user_id' is required"}), 400
    data = request.get_json(silent=True) or {}
    criteria = data.get('criteria')
    action = data.get('action')
    criteria["from"] = criteria["from"].replace(",", " OR ") # google api use OR for checking multiple ones
    if not isinstance(criteria, dict) or not isinstance(action, dict):
        return jsonify({"error": "'criteria' and 'action' must be objects"}), 400
    try:
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        result = gc.create_filter(service, criteria, action) # this reutrn the filter_id which is the result["id"]
        return jsonify(result)
    except Exception as e:
        return safe_error(e)

@app.route('/filters/<filter_id>', methods=['DELETE'])
@limiter.limit("15 per minute")
@require_api_key
def delete_filter(filter_id):
    user_id = get_valid_user_id()
    if not user_id or not MESSAGE_ID_RE.match(filter_id):
        return jsonify({"error": "valid 'user_id' and filter_id are required"}), 400
    try:
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        gc.delete_filter(service, filter_id)
        return jsonify({"deleted": filter_id})
    except Exception as e:
        return safe_error(e)

@app.route('/labels', methods=['GET'])
@limiter.limit("30 per minute")
@require_api_key
def list_labels():
    user_id = get_valid_user_id()
    if not user_id:
        return jsonify({"error": "valid 'user_id' is required"}), 400
    try:
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        return jsonify(gc.list_labels(service))
    except Exception as e:
        return safe_error(e)

@app.route('/labels', methods=['POST'])
@limiter.limit("15 per minute")
@require_api_key
def create_label():
    user_id = get_valid_user_id()
    if not user_id:
        return jsonify({"error": "valid 'user_id' is required"}), 400
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    if not name or not LABEL_NAME_RE.match(name):
        return jsonify({"error": "valid 'name' is required"}), 400
    list_visibility = data.get('list_visibility', 'labelShow')
    label_visibility = data.get('label_visibility', 'labelShow')
    if list_visibility not in ('labelShow', 'labelHide'):
        list_visibility = 'labelShow'
    if label_visibility not in ('labelShow', 'labelShowIfUnread', 'labelHide'):
        label_visibility = 'labelShow'
    try:
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        result = gc.create_label(service, name, list_visibility, label_visibility)
        return jsonify(result)
    except Exception as e:
        return safe_error(e)

@app.errorhandler(429)
def rate_limit_handler(e):
    return jsonify({"error": "rate limit exceeded"}), 429

@app.route('/messages/send-multiple', methods=['POST'])
@limiter.limit("10 per minute")
def send_multiple_message():
    token = request.args.get("token")
    tokench = au.process(token=token)
    if not tokench["status"] :
        return jsonify({"status": "failed" , "reason": tokench["reason"]})
    user_id = tokench['user_id']

    data = request.get_json(force=True) or {}
    messages = data.get('messages')
    if not messages or not isinstance(messages, list):
        return jsonify({"error": "'messages' must be a non-empty list."}), 400
    try:
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    results = []
    for msg in messages:
        to = msg.get('to')
        subject = msg.get('subject', '')
        body_text = msg.get('body_text', '')
        name = msg.get('name', '')
        if not to:
            results.append({"to": to, "error": "'to' is required."})
            continue
        try:
            result = gc.send_message(service, to, subject, body_text, name)
            results.append({"to": to, "id": result.get('id'), "threadId": result.get('threadId')})
        except Exception as e:
            results.append({"to": to, "error": str(e)})
    return jsonify({"count": len(results), "results": results})


@app.route('/messages/send-multiple-with-attachments', methods=['POST'])
@limiter.limit("10 per minute")
def send_multiple_message_with_attachments():
    token = request.args.get("token")
    tokench = au.process(token=token)
    if not tokench["status"] :
        return jsonify({"status": "failed" , "reason": tokench["reason"]})
    user_id = tokench['user_id']

    recipients_raw = request.form.get('to')
    subject = request.form.get('subject', '')
    body_text = request.form.get('body_text', '')
    name = request.form.get('name', '')
    if not recipients_raw:
        return jsonify({"error": "'to' is required (comma-separated list)."}), 400
    recipients = [r.strip() for r in recipients_raw.split(',') if r.strip()]
    if not recipients:
        return jsonify({"error": "'to' must contain at least one recipient."}), 400
    files = request.files.getlist('attachments')
    if not files:
        return jsonify({"error": "At least one attachment is required."}), 400
    upload_dir = os.path.join('uploads', 'tmp')
    os.makedirs(upload_dir, exist_ok=True)
    saved_paths = []
    try:
        for f in files:
            path = os.path.join(upload_dir, f.filename)
            f.save(path)
            saved_paths.append(path)
        service = gc.get_service(user_id=user_id)
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        results = []
        for to in recipients:
            try:
                result = gc.send_message_with_attachments( service, to, subject, body_text, saved_paths, name=name, allowed_dir=upload_dir )
                results.append({"to": to, "id": result.get('id'), "threadId": result.get('threadId')})
            except Exception as e:
                results.append({"to": to, "error": str(e)})
        return jsonify({"count": len(results), "results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        for p in saved_paths:
            if os.path.exists(p):
                os.remove(p)

if __name__ == '__main__':
    os.makedirs(UPLOAD_ROOT, exist_ok=True)
    os.makedirs(ATTACH_ROOT, exist_ok=True)
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, port=int(os.environ.get("PORT", 5000)))