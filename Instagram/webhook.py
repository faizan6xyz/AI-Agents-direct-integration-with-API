from flask import Blueprint, request, jsonify , Flask
import hmac, hashlib, os, requests
instagram_bp = Blueprint("instagram_webhook", __name__)
VERIFY_TOKEN = os.environ.get("IG_WEBHOOK_VERIFY_TOKEN")
APP_SECRET = os.environ.get("IG_APP_SECRET")

@instagram_bp.route("/webhook/instagram", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@instagram_bp.route("/webhook/instagram", methods=["POST"])
def receive_webhook():
    if not verify_signature(request):
        return "Invalid signature", 403
    data = request.get_json()
    if data.get("object") == "instagram":
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "comments":
                    handle_comment_event(change["value"])
    return jsonify(status="EVENT_RECEIVED"), 200

def verify_signature(req):
    signature = req.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(APP_SECRET.encode(), req.data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)

def handle_comment_event(value):
    comment_id = value.get("id")
    text = value.get("text")
    from_user = value.get("from", {}).get("username")
    media_id = value.get("media", {}).get("id")
    print(f"[IG comment] {from_user}: {text} (comment_id={comment_id}, media_id={media_id})")

def subscribe_page_to_webhooks(page_id, page_access_token):
    url = f"https://graph.facebook.com/v21.0/{page_id}/subscribed_apps"
    resp = requests.post(url, params={"subscribed_fields": "comments","access_token": page_access_token})
    return resp.json()

def reply_to_comment(comment_id, message, access_token):
    url = f"https://graph.facebook.com/v21.0/{comment_id}/replies"
    resp = requests.post(url, params={"message": message,"access_token": access_token})
    return resp.json()

app = Flask(__name__)
app.register_blueprint(instagram_bp)

if __name__ == "__main__":
    app.run(port=5000, debug=True)