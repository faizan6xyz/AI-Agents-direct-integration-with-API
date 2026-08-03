import os
import io
from datetime import datetime
from flask import Flask, request, redirect, jsonify, send_file
from google_auth_oauthlib.flow import Flow
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError
import tempfile
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError, TransportError, GoogleAuthError
from googleapiclient.discovery import build
from itsdangerous import URLSafeSerializer, BadSignature
from cryptography.fernet import Fernet
import database.UserDB as dbimp
app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
REDIRECT_URI = os.environ["GOOGLE_REDIRECT_URI"]
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
fernet = Fernet(os.environ["FERNET_KEY"].encode())
serializer = URLSafeSerializer(app.secret_key)
table_name = "Drive" 
PLATFORM_FOLDERS = ["whatsapp", "instagram", "gmail", "linkedin"]
SUBFOLDERS = ["photos", "videos", "pdf", "documents", "analytics" ]

def save_tokens(user_id, access_token, refresh_token, expiry):
    dbimp.insert_rows(table_name, {"id" : user_id , "Access_token" : fernet.encrypt(access_token.encode()) , "Refresh_token" : fernet.encrypt(refresh_token.encode()) , "Token_expire": fernet.encrypt(expiry.isoformat().encode()), "Connected" : 1 , "Scopes" : SCOPES})
    

def Update_token(user_id, access_token, refresh_token, expiry):
    dbimp.update_rows(table_name, {"Access_token" : fernet.encrypt(access_token.encode()) , "Refresh_token": fernet.encrypt(refresh_token.encode()) , "Token_expire": fernet.encrypt(expiry.isoformat().encode()) }, {"id" : user_id})

def load_tokens(user_id):
    row = dbimp.select_rows(table_name , filters= {"id" : user_id})
    if not row :    
        return None
    access_token = row["Access_token"]
    refresh_token = row["Refresh_token"]
    expiry = row["Token_expire"]
    connected = row["Connected"]
    return {"access_token": fernet.decrypt(access_token).decode(), "refresh_token": fernet.decrypt(refresh_token).decode(), "token_expiry": fernet.decrypt(expiry).decode() , "connected": bool(connected) }

def mark_disconnected(user_id):
    dbimp.update_rows(table_name , {"Connected" : 0 } , {"id" : user_id} )

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
    expiry = None
    if tokens["token_expiry"]:
        expiry = datetime.fromisoformat(tokens["token_expiry"])
    creds = Credentials( token=tokens["access_token"], refresh_token=tokens["refresh_token"], token_uri="https://oauth2.googleapis.com/token", client_id=CLIENT_ID, client_secret=CLIENT_SECRET, scopes=SCOPES , expiry=expiry )
    if creds.expired:
        try:
            creds.refresh(GoogleRequest())
            Update_token(user_id, creds.token, creds.refresh_token, creds.expiry)
        except RefreshError:    
            mark_disconnected(user_id)
            return None
        except TransportError as e: # network-level failure talking to Google — don't disconnect, just fail this call
            return None
        except GoogleAuthError as e: # any other auth-library error we didn't anticipate
            return None
        except Exception as e: # last-resort catch so a bad response/JSON parse doesn't 500 the route
            return None 
    return build("drive", "v3", credentials=creds)

def get_or_create_folder(service, folder_name, parent_id=None):
    query = (f"name='{folder_name}' "
            "and mimeType='application/vnd.google-apps.folder' "
            "and trashed=false")
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get("files", [])
    if folders:
        if len(folders) > 1:
            print(f"[warning] multiple folders named '{folder_name}' found "
                  f"under parent={parent_id}; using the first one (id={folders[0]['id']})")
        return folders[0]["id"], False
    folder_metadata = { "name": folder_name, "mimeType": "application/vnd.google-apps.folder", }
    if parent_id:
        folder_metadata["parents"] = [parent_id]
    folder = service.files().create(body=folder_metadata, fields="id").execute()
    return folder["id"], True

def create_platform_folder_structure(service):
    structure = {}
    get_or_create_folder(service,"marketing_due") # to store the info about the sending people
    for platform in PLATFORM_FOLDERS:
        platform_id, platform_created = get_or_create_folder(service, platform)
        structure[platform] = {"_id": platform_id, "_created": platform_created}
        for sub in SUBFOLDERS:
            sub_id, sub_created = get_or_create_folder(service, sub, parent_id=platform_id)
            structure[platform][sub] = {"id": sub_id, "created": sub_created}
    return structure

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
    return jsonify({ "count": len(all_files), "files": all_files })

@app.route("/drive/setup-folders", methods=["POST"])
def setup_folders():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    service = get_drive_service(user_id)
    if not service:
        return jsonify({"error": "not connected", "connect_url": f"/connect-drive?user_id={user_id}"}), 401
    try:
        structure = create_platform_folder_structure(service)
    except HttpError as e:
        return jsonify({"error": "drive error", "detail": str(e)}), 400
    return jsonify({ "folders": structure})

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
        platform = request.args.get("platform")
        subfolder = request.args.get("subfolder")
        parent_id = request.args.get("parent_id")
        make_public = True
        file_metadata = {"name": uploaded_file.filename}
        if platform or subfolder:
            if platform not in PLATFORM_FOLDERS:
                return jsonify({"error": f"invalid platform, must be one of {PLATFORM_FOLDERS}"}), 400
            if subfolder not in SUBFOLDERS:
                return jsonify({"error": f"invalid subfolder, must be one of {SUBFOLDERS}"}), 400
            platform_id, _ = get_or_create_folder(service, platform)
            sub_id, _ = get_or_create_folder(service, subfolder, parent_id=platform_id)
            file_metadata["parents"] = [sub_id]
        elif parent_id:
            file_metadata["parents"] = [parent_id]
        media = MediaFileUpload(tmp_path, mimetype=uploaded_file.mimetype, resumable=True)
        created_file = service.files().create(body=file_metadata, media_body=media, fields="id, name, webViewLink, webContentLink, mimeType" ).execute()
        file_id = created_file["id"]
        if make_public:
            service.permissions().create(fileId=file_id, body={"type": "anyone", "role": "reader"}, ).execute()
    except HttpError as e:
        return jsonify({"error": "drive upload failed", "detail": str(e)}), 400
    finally:
        os.remove(tmp_path)
    return jsonify({"file_id": file_id, "name": created_file.get("name"),"mime_type": created_file.get("mimeType"), "url": created_file.get("webViewLink"),"download_url": created_file.get("webContentLink"),  "public": make_public,})   # download url is the media url to pass

@app.route("/drive/delete", methods=["DELETE"])
def delete_file():
    user_id = request.args.get("user_id")
    file_id = request.args.get("file_id")
    if not user_id or not file_id:
        return jsonify({"error": "user_id and file_id required"}), 400
    service = get_drive_service(user_id)
    if not service:
        return jsonify({"error": "not connected", "connect_url": f"/connect-drive?user_id={user_id}"}), 401
    try:
        service.files().delete(fileId=file_id).execute()
    except HttpError as e:
        status = e.resp.status if e.resp else 500
        if status == 404:
            return jsonify({"error": "file not found"}), 404
        return jsonify({"error": "drive error", "details": str(e)}), status
    return jsonify({ "file_id": file_id, "status": "deleted"})

@app.route("/drive/metadata")
def get_drive_file_metadata():
    user_id = request.args.get("user_id")
    file_id = request.args.get("file_id")
    if not user_id or not file_id:
        return jsonify({"error": "user_id and file_id required"}), 400
    service = get_drive_service(user_id)
    if not service:
        return jsonify({"error": "not connected", "connect_url": f"/connect-drive?user_id={user_id}"}), 401
    try:
        file = service.files().get(fileId=file_id,fields="id,name,mimeType,size,videoMediaMetadata,imageMediaMetadata").execute()
    except HttpError as e:
        return jsonify({"error": "metadata fetch failed", "detail": str(e)}), 400
    return jsonify({"file": file})

if __name__ == "__main__":
    # for server        gunicorn -w 4 -b 0.0.0.0:8080 app:app             insread of py app.py
    app.run(host="0.0.0.0", port=8080, debug=True)