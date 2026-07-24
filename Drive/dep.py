import os
import sqlite3
from flask import Flask, request, redirect, jsonify
from google_auth_oauthlib.flow import Flow
from googleapiclient.http import MediaFileUpload    
import tempfile
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from itsdangerous import URLSafeSerializer, BadSignature
from cryptography.fernet import Fernet
app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
REDIRECT_URI = os.environ["GOOGLE_REDIRECT_URI"]
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DB_PATH = "drive_accounts.db"
fernet = Fernet(os.environ["FERNET_KEY"].encode())
serializer = URLSafeSerializer(app.secret_key)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(""" CREATE TABLE IF NOT EXISTS drive_accounts (
                        user_id TEXT PRIMARY KEY,
                        access_token BLOB NOT NULL,
                        refresh_token BLOB NOT NULL,
                        token_expiry TEXT,
                        connected INTEGER DEFAULT 1 ) """)
    conn.commit()
    conn.close()

def save_tokens(user_id, access_token, refresh_token, expiry):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(""" INSERT INTO drive_accounts (user_id, access_token, refresh_token, token_expiry, connected)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(user_id) DO UPDATE SET
                        access_token = excluded.access_token,
                        refresh_token = excluded.refresh_token,
                        token_expiry = excluded.token_expiry,
                        connected = 1 """, ( user_id, fernet.encrypt(access_token.encode()),fernet.encrypt(refresh_token.encode()), expiry.isoformat() if expiry else None ))
    conn.commit()
    conn.close()

def load_tokens(user_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute( "SELECT access_token, refresh_token, token_expiry, connected FROM drive_accounts WHERE user_id = ?", (user_id,) ).fetchone()
    conn.close()
    if not row:
        return None
    access_token, refresh_token, expiry, connected = row
    return {"access_token": fernet.decrypt(access_token).decode(), "refresh_token": fernet.decrypt(refresh_token).decode(), "token_expiry": expiry, "connected": bool(connected) }

def mark_disconnected(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE drive_accounts SET connected = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def build_flow():
    return Flow.from_client_config({"web": { 
                                        "client_id": CLIENT_ID,
                                        "client_secret": CLIENT_SECRET,
                                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                        "token_uri": "https://oauth2.googleapis.com/token",
                                        "redirect_uris": [REDIRECT_URI], }},
                                    scopes=SCOPES,redirect_uri=REDIRECT_URI)

def get_drive_service(user_id):
    tokens = load_tokens(user_id)
    if not tokens or not tokens["connected"]:
        return None
    creds = Credentials( token=tokens["access_token"], refresh_token=tokens["refresh_token"], token_uri="https://oauth2.googleapis.com/token", client_id=CLIENT_ID, client_secret=CLIENT_SECRET, scopes=SCOPES )
    if creds.expired:
        try:
            creds.refresh(GoogleRequest())
            save_tokens(user_id, creds.token, creds.refresh_token, creds.expiry)
        except RefreshError:
            mark_disconnected(user_id)
            return None
    return build("drive", "v3", credentials=creds)

@app.route("/connect-drive")
def connect_drive():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    flow = build_flow()
    signed_state = serializer.dumps(user_id)
    auth_url, _ = flow.authorization_url( access_type="offline", prompt="consent", state=signed_state )
    return redirect(auth_url)

@app.route("/oauth/callback")
def oauth_callback():
    signed_state = request.args.get("state")
    try:
        user_id = serializer.loads(signed_state)
    except BadSignature:
        return jsonify({"error": "invalid state"}), 400
    flow = build_flow()
    flow.fetch_token(code=request.args["code"])
    creds = flow.credentials
    save_tokens(user_id, creds.token, creds.refresh_token, creds.expiry)
    return jsonify({"status": "connected", "user_id": user_id})

@app.route("/drive/files")
def list_files():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    service = get_drive_service(user_id)
    if not service:
        return jsonify({"error": "not connected", "connect_url": f"/connect-drive?user_id={user_id}"}), 401
    all_files = []
    page_token = None
    while True:
        response = service.files().list( pageSize=100, fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, webViewLink, webContentLink)", pageToken=page_token).execute()
        all_files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return jsonify({"user_id": user_id, "count": len(all_files), "files": all_files })

@app.route("/drive/upload", methods=["POST"])
def upload_file():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    service = get_drive_service(user_id)
    if not service:
        return jsonify({"error": "not connected", "connect_url": f"/connect-drive?user_id={user_id}"}), 401
    if "file" not in request.files:
        return jsonify({"error": "file required (form-data field: file)"}), 400
    uploaded_file = request.files["file"]
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        uploaded_file.save(tmp.name)
        tmp_path = tmp.name
    try:
        file_metadata = {"name": uploaded_file.filename}
        parent_id = request.args.get("parent_id")
        if parent_id:
            file_metadata["parents"] = [parent_id]
        media = MediaFileUpload(tmp_path, mimetype=uploaded_file.mimetype, resumable=True)
        created_file = service.files().create(body=file_metadata, media_body=media, fields="id, name, webViewLink, mimeType" ).execute()
    finally:
        os.remove(tmp_path)
    return jsonify({"user_id": user_id, "file": created_file})

if __name__ == "__main__":
    init_db()
    # for server        gunicorn -w 4 -b 0.0.0.0:8080 app:app
    app.run(host="0.0.0.0", port=8080, debug=True)