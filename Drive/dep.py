import io
import pandas as pd
import os
from flask import Flask, request, redirect, jsonify, send_file
from google_auth_oauthlib.flow import Flow
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload , MediaIoBaseUpload ,MediaIoBaseDownload
from googleapiclient.errors import HttpError
import tempfile
from datetime import datetime, timezone, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError, TransportError, GoogleAuthError
from googleapiclient.discovery import build
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from cryptography.fernet import Fernet
import requests
import database.UserDB as dbimp
import authnew as au
app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]  
REDIRECT_URI = os.environ["GOOGLE_REDIRECT_URI"]
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
fernet = Fernet(os.environ["FERNET_KEY"].encode())
serializer = URLSafeTimedSerializer(app.secret_key)
STATE_MAX_AGE = 600  # seconds, state link expires after 10 min
table_name = "Drive" 
PLATFORM_FOLDERS = ["whatsapp", "instagram", "gmail", "linkedin","x"]
BASE_URL = ""
SUBFOLDERS = ["photos", "videos", "pdf", "documents", " " ]

def save_tokens(token, user_id, access_token, refresh_token, expiry):
    timestamp = datetime.now(timezone.utc).isoformat()
    dbimp.insert_rows(token,table_name, {"id" : user_id , "Timestamp":timestamp ,"Access_token" : fernet.encrypt(access_token.encode()).decode(), "Refresh_token" : fernet.encrypt(refresh_token.encode()).decode(), "Token_expire": fernet.encrypt(expiry.encode()).decode(), "Connected" : 1 , "Scopes" : SCOPES})
    

def Update_token(token , user_id, access_token, refresh_token, expiry):
    dbimp.update_rows(token , table_name, {"Access_token" : fernet.encrypt(access_token.encode()).decode(), "Refresh_token": fernet.encrypt(refresh_token.encode()).decode(), "Token_expire": fernet.encrypt(expiry.isoformat().encode()).decode()}, {"id" : user_id})

def load_tokens(token,user_id):
    rows = dbimp.select_rows(token,table_name , filters= {"id" : user_id})
    row = rows[0] if rows else None
    if not row :    
        return None
    access_token = row["Access_token"]
    refresh_token = row["Refresh_token"]
    expiry = row["Token_expire"]
    connected = row["Connected"]
    return {"access_token": fernet.decrypt(access_token.encode()).decode(), "refresh_token": fernet.decrypt(refresh_token.encode()).decode(), "token_expiry": fernet.decrypt(expiry.encode()).decode() , "connected": bool(connected) }


def mark_disconnected(token,user_id):
    dbimp.update_rows(token,table_name , {"Connected" : 0 } , {"id" : user_id} )

def build_flow():
    return Flow.from_client_config({"web": { "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [REDIRECT_URI], }}, scopes=SCOPES,redirect_uri=REDIRECT_URI)

def get_drive_service(token,user_id):
    tokens = load_tokens(token,user_id)
    if not tokens or not tokens["connected"]:
        return None
    expiry = None
    if tokens["token_expiry"]:
        expiry = datetime.fromisoformat(tokens["token_expiry"])
    creds = Credentials( token=tokens["access_token"], refresh_token=tokens["refresh_token"], token_uri="https://oauth2.googleapis.com/token", client_id=CLIENT_ID, client_secret=CLIENT_SECRET, scopes=SCOPES , expiry=expiry )
    if creds.expired:
        try:
            creds.refresh(GoogleRequest())
            Update_token(token ,user_id, creds.token, creds.refresh_token, creds.expiry)
        except RefreshError:
            try:
                mark_disconnected(token, user_id)
            except Exception:
                pass
            return None
        except TransportError as e: # network-level failure talking to Google — don't disconnect, just fail this call
            return None
        except GoogleAuthError as e: # any other auth-library error we didn't anticipate
            return None
        except Exception as e: # last-resort catch so a bad response/JSON parse doesn't 500 the route
            return None 
    return build("drive", "v3", credentials=creds)

def authenticate_request():
    token = request.args.get("token")
    tokench = au.process(token=token)
    if not tokench["status"]:
        return None, (jsonify({"status": "failed", "reason": tokench["reason"]}), 200)
    user_id = tokench['user_id']
    if not user_id:
        return None, (jsonify({"error": "user_id required"}), 400)
    return user_id, None

def authenticate_and_get_service(token):
    user_id, err = authenticate_request()
    if err: return None,  err
    service = get_drive_service(token,user_id)
    if not service:
        return None, (jsonify({"error": "not connected", "connect_url": f"/connect-drive?user_id={user_id}"}), 401)
    return service, None

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
    for platform in PLATFORM_FOLDERS:
        platform_id, platform_created = get_or_create_folder(service, platform)
        structure[platform] = {"_id": platform_id, "_created": platform_created}
        for sub in SUBFOLDERS:
            sub_id, sub_created = get_or_create_folder(service, sub, parent_id=platform_id)
            structure[platform][sub] = {"id": sub_id, "created": sub_created}
    return structure

def read_csv_from_dive(file_id, token):
    if not file_id:
        raise ValueError("file_id is required")
    service, err = authenticate_and_get_service(token)
    if err:
        raise RuntimeError(f"Authentication failed: {err}")
    try:
        drive_request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, drive_request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buffer.seek(0)
    except Exception as e:
        raise RuntimeError(f"Failed to read CSV from Google Drive: {e}")
    try:
        df = pd.read_csv(buffer)
    except pd.errors.EmptyDataError:
        raise ValueError("The CSV file is empty")
    except pd.errors.ParserError:
        raise ValueError("The file is not a valid CSV")
    return df      

@app.route("/connect-drive")
def connect_drive():
    user_id, err = authenticate_request()
    if err: return err
    flow = build_flow()
    signed_state = serializer.dumps(user_id)
    auth_url, _ = flow.authorization_url( access_type="offline", prompt="consent", state=signed_state )
    return redirect(auth_url)

@app.route("/auth/drivecallback")
def oauth_callback():
    signed_state = request.args.get("state")
    try:
        user_id = serializer.loads(signed_state, max_age=STATE_MAX_AGE)
    except SignatureExpired:
        return jsonify({"error": "state expired, please reconnect"}), 400
    except BadSignature:
        return jsonify({"error": "invalid state"}), 400
    flow = build_flow()
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "missing code", "details": request.args.get("error")}), 400
    flow.fetch_token(code=code)
    creds = flow.credentials
    expire = creds.expiry.isoformat()
    expiry_ts = datetime.now(timezone.utc) + timedelta(hours=1)
    token = au.jsonspoof(user_id=user_id, timestamp=expiry_ts)
    payload = {"user_id": user_id,"access": creds.token,"expire": expire,"refresh": creds.refresh_token ,"token":token}
    signed_payload = serializer.dumps(payload)
    resp = requests.post(f"{BASE_URL}/auth/drive/callbackshi", json={"data": signed_payload}, timeout=5)
    return (resp.content, resp.status_code, resp.headers.items())

@app.route("/auth/drive/callbackshi", methods=["POST"])
def oauth_callbac():
    raw = request.get_json(silent=True) or {}
    try:
        data = serializer.loads(raw.get("data"), max_age=STATE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return jsonify({"status": False, "error": "invalid or expired payload"}), 403
    token = data.get("token")
    user_id = data.get("user_id")
    expire = data.get("expire")
    refresh = data.get("refresh")
    access = data.get("access")
    if not token or not user_id or not expire or not access or not refresh :
        return jsonify({"status":False}),403
    try:
        datetime.fromisoformat(expire)
    except ValueError:
        return jsonify({"status": False, "error": "invalid expire format"}), 400
    try:
        save_tokens(token, user_id, access, refresh, expire)
    except Exception as e:
        return jsonify({"status": False, "error": str(e)}), 403
    return jsonify({"status":True}),200
    

@app.route("/drive/files")
def list_files():
    token= request.args.get("token")
    service, err = authenticate_and_get_service(token)
    if err: return err
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
    token= request.args.get("token")
    service, err = authenticate_and_get_service(token)
    if err: return err
    try:
        structure = create_platform_folder_structure(service)
    except HttpError as e:
        return jsonify({"error": "drive error", "detail": str(e)}), 400
    return jsonify({ "folders": structure})

@app.route("/drive/upload", methods=["POST"])
def upload_file():
    token= request.args.get("token")
    service, err = authenticate_and_get_service(token)
    if err: return err
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
    token= request.args.get("token")
    service, err = authenticate_and_get_service(token)
    if err: return err
    file_id = request.args.get("file_id")
    if not file_id:
        return jsonify({"error": "file_id required"}), 400
    try:
        service.files().delete(fileId=file_id).execute()
    except HttpError as e:
        status = e.resp.status if e.resp else 500
        if status == 404:
            return jsonify({"error": "file not found"}), 404
        return jsonify({"error": "drive error", "details": str(e)}), status
    return jsonify({ "file_id": file_id, "status": "deleted"})

@app.route("/drive/anal/<file_id>")
def read_csv_from_drive(file_id):
    token= request.args.get("token")
    if not file_id :
        return jsonify({"error" : "File_id is required "}) , 500
    service, err = authenticate_and_get_service(token)
    if err:
        return err
    try:
        drive_request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, drive_request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buffer.seek(0)
    except Exception as e:
        return jsonify({ "error": "Failed to read CSV from Google Drive", "details": str(e)}), 500
    try :
        df = pd.read_csv(buffer)
    except pd.errors.EmptyDataError:
        return jsonify({ "error": "The CSV file is empty" }), 400
    except pd.errors.ParserError:
        return jsonify({"error": "The file is not a valid CSV" }), 400
    return jsonify({"CSV": df.to_dict(orient="records")}), 200  

@app.route("/drive/append/<file_id>", methods=["POST"])
def append_csv_to_drive(file_id):
    token = request.args.get("token")
    if not file_id:
        return jsonify({"error": "File_id is required"}), 500
    service, err = authenticate_and_get_service(token)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    new_rows = body.get("rows")  # expects list of dicts: [{"col1": "val", "col2": "val"}, ...]
    if not new_rows or not isinstance(new_rows, list):
        return jsonify({"error": "expected a non-empty 'rows' list"}), 400
    try:
        drive_request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, drive_request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buffer.seek(0)
    except Exception as e:
        return jsonify({"error": "Failed to read CSV from Google Drive", "details": str(e)}), 500
    try:
        existing_df = pd.read_csv(buffer)
    except pd.errors.EmptyDataError:
        existing_df = pd.DataFrame()
    except pd.errors.ParserError:
        return jsonify({"error": "The existing file is not a valid CSV"}), 400
    try:
        new_df = pd.DataFrame(new_rows)
    except Exception as e:
        return jsonify({"error": "Invalid row data", "details": str(e)}), 400
    if not existing_df.empty and list(existing_df.columns) != list(new_df.columns):
        missing_cols = set(existing_df.columns) - set(new_df.columns)
        extra_cols = set(new_df.columns) - set(existing_df.columns)
        if missing_cols or extra_cols:
            return jsonify({ "error": "Column mismatch between existing CSV and new rows","missing_in_new": list(missing_cols),"unexpected_in_new": list(extra_cols)}), 400
    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    out_buffer = io.BytesIO()
    combined_df.to_csv(out_buffer, index=False)
    out_buffer.seek(0)
    try:
        media = MediaIoBaseUpload(out_buffer, mimetype="text/csv", resumable=True)
        service.files().update(fileId=file_id, media_body=media).execute()
    except Exception as e:
        return jsonify({"error": "Failed to write updated CSV to Google Drive", "details": str(e)}), 500
    return jsonify({"status": "ok","rows_added": len(new_df),"total_rows": len(combined_df)}), 200

@app.route("/drive/metadata")
def get_drive_file_metadata():
    token= request.args.get("token")
    service, err = authenticate_and_get_service(token)
    if err: return err
    file_id = request.args.get("file_id")
    if not file_id:
        return jsonify({"error": "file_id required"}), 400
    try:
        file = service.files().get(fileId=file_id,fields="id,name,mimeType,size,videoMediaMetadata,imageMediaMetadata").execute()
    except HttpError as e:
        return jsonify({"error": "metadata fetch failed", "detail": str(e)}), 400
    return jsonify({"file": file})

if __name__ == "__main__":
    # for server        gunicorn -w 4 -b 0.0.0.0:8080 app:app             insread of py app.py
    app.run(host="0.0.0.0", port=8080, debug=True)