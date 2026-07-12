
import base64
import json
from flask import Flask, request, jsonify
from Gmail.Gmail_watch import get_service
app = Flask(__name__)

def get_last_history_id():
    with open("last_history_id.txt") as f:
        return f.read().strip()

def save_last_history_id(history_id):
    with open("last_history_id.txt", "w") as f:
        f.write(str(history_id))

@app.route("/gmail-webhook", methods=["POST"])
def gmail_webhook():
    envelope = request.get_json()
    # Pub/Sub wraps the real data in base64 inside "message" -> "data"
    message_data = envelope["message"]["data"]
    decoded = base64.b64decode(message_data).decode("utf-8")
    notification = json.loads(decoded)
    email_address = notification["emailAddress"]
    new_history_id = notification["historyId"]
    print(f"Change detected for {email_address}, historyId: {new_history_id}")
    # Fetch what actually changed since our last known historyId
    service = get_service()
    last_id = get_last_history_id()
    history = service.users().history().list(
        userId="me",
        startHistoryId=last_id,
    ).execute()
    for record in history.get("history", []):
        for msg_added in record.get("messagesAdded", []):
            msg_id = msg_added["message"]["id"]
            full_msg = service.users().messages().get(userId="me", id=msg_id).execute()
            subject = next(
                (h["value"] for h in full_msg["payload"]["headers"] if h["name"] == "Subject"),
                "(no subject)",
            )
            print(f"New email: {subject}")
    save_last_history_id(new_history_id)
    # Pub/Sub requires a 200 response, or it will retry delivery
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(port=5001, debug=True)