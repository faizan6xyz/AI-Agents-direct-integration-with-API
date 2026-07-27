import base64
import json
import os
from flask import Flask, request, jsonify
from googleapiclient.errors import HttpError
from Gmail.Read_mails import get_service
app = Flask(__name__)
HISTORY_FILE = "last_history_id.txt"
GCP_PROJECT_ID = "your-project-id"
PUBSUB_TOPIC = "gmail-notifications"

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
    service = get_service()
    request_body = {"labelIds": ["INBOX"],"topicName": f"projects/{GCP_PROJECT_ID}/topics/{PUBSUB_TOPIC}",}
    response = service.users().watch(userId="me", body=request_body).execute()
    save_last_history_id(response["historyId"])
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
    service = get_service()
    last_id = get_last_history_id()
    if last_id is None:
        save_last_history_id(new_history_id)
        return jsonify({"status": "ok", "note": "no baseline, storing current id"}), 200
    try:
        history = service.users().history().list(userId="me", startHistoryId=last_id,).execute()
    except HttpError as e:
        if e.resp.status == 404:
            print("historyId too old, resyncing from current notification")
            save_last_history_id(new_history_id)
            return jsonify({"status": "ok", "note": "resynced"}), 200
        raise
    for record in history.get("history", []):
        for msg_added in record.get("messagesAdded", []):
            msg_id = msg_added["message"]["id"]
            full_msg = service.users().messages().get(userId="me", id=msg_id).execute()
            subject = next((h["value"] for h in full_msg["payload"]["headers"] if h["name"] == "Subject"),"(no subject)",)
            print(f"New email: {subject}")
    save_last_history_id(new_history_id)
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(port=5001, debug=True)