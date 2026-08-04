import os
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
app = Flask(__name__)
VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN")
APP_SECRET = os.getenv("IG_APP_SECRET")

@app.route("/instagram/comments/<account_id>", methods=["GET", "POST"])
def webhook(account_id):
    if request.method == "GET":
        return verify_webhook()
    return receive_webhook(account_id)

def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

def receive_webhook(account_id):
    if not verify_signature(request):
        return "Invalid signature", 403
    data = request.get_json()
    events = []  
    if data.get("object") == "instagram":
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "comments":
                    events.append(handle_comment_event(account_id, change["value"]))
    return jsonify({"info" :events, "status" :"EVENT_RECEIVED"}), 200

def verify_signature(req):
    signature = req.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(APP_SECRET.encode(), req.data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)

def handle_comment_event(account_id, value):
    comment_id = value.get("id")
    from_user_id = value.get("from", {}).get("id")
    from_username = value.get("from", {}).get("username")
    media_id = value.get("media", {}).get("id")
    return {"account_id": account_id, "comment_id": comment_id, "from_user_id": from_user_id, "from_username": from_username,  "media_id": media_id,}

def subscribe_page_to_webhooks(page_id, page_access_token): # run it once for the subscription
    url = f"https://graph.facebook.com/v25.0/{page_id}/subscribed_apps"   # webhook require facebook api and link the facebook account with it 
    resp = requests.post( url,params={"subscribed_fields": "comments", "access_token": page_access_token},)
    return resp.json()

if __name__ == "__main__":
    app.run(port=5000, debug=True)