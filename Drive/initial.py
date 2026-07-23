import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build   # The google-api-python-client is a wrapper around the API
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"

def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=8080)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds

def list_all_files(service):
    all_files = []
    page_token = None
    while True:
        response = service.files().list( pageSize=100, fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)", pageToken=page_token).execute()
        all_files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return all_files

def main():
    creds = get_credentials()
    print("Access token:", creds.token)
    service = build("drive", "v3", credentials=creds) # Build a Drive named API client that has v3 version with those credentials to talk.
    files = list_all_files(service)
    print(f"\nFound {len(files)} files:\n")
    for f in files:
        size = f.get("size", "N/A")
        print(f"{f['name']:<40} {f['mimeType']:<45} size={size:<10} id={f['id']}")

if __name__ == "__main__":
    main()