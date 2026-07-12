import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import pickle

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
PROJECT_ID = "YOUR_GCP_PROJECT_ID"
TOPIC_NAME = "gmail-notifications"  # the Pub/Sub topic you created
TOPIC_PATH = f"projects/{PROJECT_ID}/topics/{TOPIC_NAME}"

def get_service():
    creds = None
    if os.path.exists(r'Gmail/token.pickle'):
        with open(r'Gmail/token.pickle', 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('Gmail/ss.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open(r'Gmail/token.pickle', 'wb') as f:
            pickle.dump(creds, f)
    return build('gmail', 'v1', credentials=creds)


def start_watch(service):
    request_body = {
        "labelIds": ["INBOX"],       # only watch inbox changes
        "topicName": TOPIC_PATH,
        "labelFilterAction": "include",
    }
    response = service.users().watch(userId="me", body=request_body).execute()
    print("Watch started successfully:")
    print(f"  History ID: {response['historyId']}")
    print(f"  Expiration: {response['expiration']} (epoch ms)")
    return response


def stop_watch(service):
    service.users().stop(userId="me").execute()
    print("Watch stopped.")

if __name__ == "__main__":
    gmail_service = get_service()
    watch_response = start_watch(gmail_service)
    # Save the historyId - you need this to know "what's new" when a
    # Pub/Sub notification arrives (see the receiver script for that part)
    with open("last_history_id.txt", "w") as f:
        f.write(str(watch_response["historyId"]))