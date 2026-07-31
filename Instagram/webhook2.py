from flask import Flask, Blueprint, request, jsonify
import hmac, hashlib, os
import requests as http_requests  # Aliased to avoid conflict with Flask's 'request'
instagram_bp = Blueprint("instagram_webhook", __name__)
VERIFY_TOKEN = os.environ.get("IG_WEBHOOK_VERIFY_TOKEN")
APP_SECRET = os.environ.get("IG_APP_SECRET")
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN") # Needed to reply to comments

@instagram_bp.route("/webhook/instagram", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook verified successfully!")
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
    expected = hmac.new(APP_SECRET.encode('utf-8'),req.data,hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)

def handle_comment_event(value):
    comment_id = value.get("id")
    text = value.get("text")
    from_user = value.get("from", {}).get("username")
    media_id = value.get("media", {}).get("id")
    print(f" New comment from @{from_user} on media {media_id}: '{text}'")
    reply_message = f"Thanks for commenting, @{from_user}! 🚀"
app = Flask(__name__)
app.register_blueprint(instagram_bp, url_prefix="/instagram")

if __name__ == "__main__":
    app.run(debug=True, port=5000)