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

def setup_folders(user_id: str):
    resp = requests.post(f"{BASE_URL}/drive/setup-folders", params={"user_id": user_id})
    if resp.status_code == 401:
        print("Not connected:", resp.json())
        return None
    resp.raise_for_status()
    data = resp.json()
    print("\nFolder structure ready:")
    for platform, subfolders in data["folders"].items():
        print(f"  {platform}/ (id={subfolders['_id']})")
        for name, sub_id in subfolders.items():
            if name == "_id":
                continue
            print(f"    {name}/ (id={sub_id})")
    return data["folders"]

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

def upload_file( user_id: str, file_path: str, parent_id: str | None = None , platform: str | None = None, subfolder: str | None = None, ):
    params = {"user_id": user_id}
    if platform and subfolder:
        params["platform"] = platform
        params["subfolder"] = subfolder
    elif parent_id:
        params["parent_id"] = parent_id
    with open(file_path, "rb") as f:
        resp = requests.post(f"{BASE_URL}/drive/upload", params=params, files={"file": (file_path, f)})
    if resp.status_code == 401:
        print("Not connected:", resp.json())
        return None
    resp.raise_for_status()
    data = resp.json()
    uploaded = data["file"]
    print(f"\nUploaded: {uploaded['name']} -> {uploaded.get('webViewLink')}")
    return uploaded

def delete_file(user_id: str, file_id: str):
    resp = requests.delete(f"{BASE_URL}/drive/delete", params={"user_id": user_id, "file_id": file_id})
    if resp.status_code == 401:
        print("Not connected:", resp.json())
        return False
    if resp.status_code == 404:
        print("File not found:", resp.json())
        return False
    resp.raise_for_status()
    data = resp.json()
    print(f"\nDeleted file: {data['file_id']}")
    return True

def main():
    ensure_connected(USER_ID)
    setup_folders(USER_ID)
    list_files(USER_ID)
    file_to_upload = "report.pdf"
    try:
        upload_file(USER_ID, file_to_upload, platform="whatsapp", subfolder="documents")
    except FileNotFoundError:
        print(f"\nSkipping upload — '{file_to_upload}' not found. "
              f"Update file_to_upload to point at a real file.")
    list_files(USER_ID)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        USER_ID = sys.argv[1]
    main()

    # python dep_call.py user_123