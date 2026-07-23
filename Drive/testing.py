import os
import sqlite3
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # local dev only, remove in prod
from flask import Flask, redirect, request, session, jsonify
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
app = Flask(__name__)
app.secret_key = "replace-with-a-real-secret-key"
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = [ "openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/drive.readonly", ]
REDIRECT_URI = "http://localhost:5000/oauth2callback"
DB_PATH = "tokens.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(""" CREATE TABLE IF NOT EXISTS user_tokens (
                        user_id TEXT PRIMARY KEY,
                        access_token TEXT,
                        refresh_token TEXT,
                        token_uri TEXT,
                        client_id TEXT,
                        client_secret TEXT,
                        scopes TEXT ) """)
    conn.commit()
    conn.close()

def save_user_tokens(user_id, access_token, refresh_token, token_uri, client_id, client_secret, scopes):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT INTO user_tokens (user_id, access_token, refresh_token, token_uri, client_id, client_secret, scopes)
                    VALUES (?, ?, ?, ?, ?, ?, ?) 
                    ON CONFLICT(user_id) DO UPDATE SET
                        access_token=excluded.access_token,
                        refresh_token=COALESCE(excluded.refresh_token, user_tokens.refresh_token),
                        token_uri=excluded.token_uri,
                        client_id=excluded.client_id,
                        client_secret=excluded.client_secret,
                        scopes=excluded.scopes """, (user_id, access_token, refresh_token, token_uri, client_id, client_secret, ",".join(scopes)))
    conn.commit()
    conn.close()

def load_user_tokens(user_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute( "SELECT access_token, refresh_token, token_uri, client_id, client_secret, scopes FROM user_tokens WHERE user_id=?", (user_id,) ).fetchone()
    conn.close()
    if not row:
        return None
    return { "access_token": row[0] , "refresh_token": row[1] , "token_uri": row[2] , "client_id": row[3] , "client_secret": row[4] , "scopes": row[5].split(",") , }

def get_current_user_id():
    return session.get("user_id", "demo-user")


def get_flow():
    return Flow.from_client_secrets_file( CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI, )

def get_drive_service(user_id):
    tokens = load_user_tokens(user_id)
    if not tokens:
        return None
    creds = Credentials( token=tokens["access_token"], refresh_token=tokens["refresh_token"], token_uri=tokens["token_uri"], client_id=tokens["client_id"], client_secret=tokens["client_secret"], scopes=tokens["scopes"], )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_user_tokens( user_id, access_token=creds.token, refresh_token=creds.refresh_token, token_uri=creds.token_uri, client_id=creds.client_id, client_secret=creds.client_secret, scopes=creds.scopes, )
    return build("drive", "v3", credentials=creds)

@app.route("/authorize")
def authorize():
    flow = get_flow()
    auth_url, state = flow.authorization_url( access_type="offline", include_granted_scopes="true", prompt="consent", )
    session["state"] = state
    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    flow = get_flow()
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    user_id = get_current_user_id()  # tie this to your actual logged-in user
    save_user_tokens( user_id, access_token=creds.token, refresh_token=creds.refresh_token, token_uri=creds.token_uri, client_id=creds.client_id, client_secret=creds.client_secret, scopes=creds.scopes, )
    return redirect("/drive/files")

@app.route("/drive/files")
def list_drive_files():
    user_id = get_current_user_id()
    service = get_drive_service(user_id)
    if service is None:
        return redirect("/authorize")
    results = service.files().list( pageSize=20, fields="files(id, name, mimeType, modifiedTime)" ).execute()
    return jsonify(results.get("files", []))

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)