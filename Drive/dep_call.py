import sys
import webbrowser
import requests
BASE_URL = "http://localhost:8080"
USER_ID = "user_123"

def ensure_connected(user_id: str) -> bool:
    resp = requests.get(f"{BASE_URL}/drive/files", params={"user_id": user_id})
    if resp.status_code != 401:
        return True
    connect_url = BASE_URL + resp.json()["connect_url"]
    print(f"Not connected yet. Opening browser to: {connect_url}")
    webbrowser.open(connect_url)
    input("Press Enter once you've completed the Google login/consent screen...")
    return True

def list_files(user_id: str):
    resp = requests.get(f"{BASE_URL}/drive/files", params={"user_id": user_id})
    if resp.status_code == 401:
        print("Still not connected:", resp.json())
        return []
    resp.raise_for_status()
    data = resp.json()
    print(f"\nFound {data['count']} files:\n")
    for f in data["files"]:
        print(f"{f['name']:<40} {f['mimeType']:<40} id={f['id']}")
    return data["files"]

def upload_file(user_id: str, file_path: str, parent_id: str | None = None):
    params = {"user_id": user_id}
    if parent_id:
        params["parent_id"] = parent_id
    with open(file_path, "rb") as f:
        resp = requests.post( f"{BASE_URL}/drive/upload",params=params,files={"file": (file_path, f)},)
    if resp.status_code == 401:
        print("Not connected:", resp.json())
        return None
    resp.raise_for_status()
    data = resp.json()
    uploaded = data["file"]
    print(f"\nUploaded: {uploaded['name']} -> {uploaded.get('webViewLink')}")
    return uploaded

def main():
    ensure_connected(USER_ID)
    list_files(USER_ID)
    file_to_upload = "report.pdf"
    parent_folder_id = None 
    try:
        upload_file(USER_ID, file_to_upload, parent_folder_id)
    except FileNotFoundError:
        print(f"\nSkipping upload — '{file_to_upload}' not found. "
              f"Update file_to_upload to point at a real file.")
    list_files(USER_ID)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        USER_ID = sys.argv[1]
    main()
    
    # python dep_call.py user_123