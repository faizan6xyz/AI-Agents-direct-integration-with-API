import base64
import json
import os
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import Gmail.Read_mails as xxx
app = Flask(__name__)
HISTORY_FILE = "last_history_id.txt"
GCP_PROJECT_ID = "your-project-id"
PUBSUB_TOPIC = "gmail-notifications"

def watch_mailbox(service, topic_name, label_ids=None):
    body = {"topicName": topic_name, "labelIds": label_ids or ["INBOX"]}
    return service.users().watch(userId="me", body=body).execute()

def stop_watch(service):
    return service.users().stop(userId="me").execute()

def get_current_history_id(service):
    profile = service.users().getProfile(userId="me").execute()
    return profile["historyId"]

def list_history_since(service, start_history_id, history_types=None):
    records = []
    page_token = None
    while True:
        resp = (service.users().history().list(userId="me", startHistoryId= start_history_id, historyTypes= history_types or [], pageToken=page_token,).execute())
        records.extend(resp.get("history", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return records

def get_message(service, msg_id, format="full"):
    return service.users().messages().get(userId="me", id=msg_id, format=format).execute()

def get_last_history_id():
    if not os.path.exists(HISTORY_FILE):
        return None
    with open(HISTORY_FILE) as f:
        content = f.read().strip()
        return content if content else None

def save_last_history_id(history_id):
    with open(HISTORY_FILE, "w") as f:
        f.write(str(history_id))

@app.route("/gmail-watch/start", methods=["POST"])
def start_watch():
    service = xxx.get_service()
    topic_name = f"projects/{GCP_PROJECT_ID}/topics/{PUBSUB_TOPIC}"
    response = watch_mailbox(service, topic_name=topic_name, label_ids=["INBOX"])
    save_last_history_id(response["historyId"])
    return jsonify(response), 200

@app.route("/gmail-watch/stop", methods=["POST"])
def stop_watch_route():
    service = xxx.get_service()
    response = stop_watch(service)
    return jsonify(response), 200

@app.route("/gmail-webhook", methods=["POST"])
def gmail_webhook():
    envelope = request.get_json()
    message_data = envelope["message"]["data"]
    decoded = base64.b64decode(message_data).decode("utf-8")
    notification = json.loads(decoded)
    email_address = notification["emailAddress"]
    new_history_id = notification["historyId"]
    print(f"Change detected for {email_address}, historyId: {new_history_id}")
    service = xxx.get_service()
    last_id = get_last_history_id()
    if last_id is None:
        save_last_history_id(new_history_id)
        return jsonify({"status": "ok", "note": "no baseline, storing current id"}), 200
    try:
        records = list_history_since(service, start_history_id=last_id)
    except HttpError as e:
        status = getattr(e, "status_code", None) or getattr(e.resp, "status", None)
        if status == 404:
            print("historyId too old, resyncing from current notification")
            save_last_history_id(new_history_id)
            return jsonify({"status": "ok", "note": "resynced"}), 200
        raise
    for record in records:
        for msg_added in record.get("messagesAdded", []):
            msg_id = msg_added["message"]["id"]
            full_msg = get_message(service, msg_id)
            headers = full_msg.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)", )
            print(f"New email: {subject}")
    save_last_history_id(new_history_id)
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(port=5001, debug=True)