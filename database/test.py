import os
import hmac
import hashlib
import logging
import time
from functools import wraps
from flask import Flask, request, jsonify
from supabase import create_client, Client
from postgrest.exceptions import APIError
logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",)
logger = logging.getLogger("whatsapp_webhook")
REQUIRED_ENV_VARS = [
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "WHATSAPP_APP_SECRET",   # used to verify X-Hub-Signature-256
    "WHATSAPP_VERIFY_TOKEN", # used for the GET verification handshake
]
missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if missing:
    raise RuntimeError(f"Missing required environment variables: {missing}")
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
APP_SECRET = os.environ["WHATSAPP_APP_SECRET"]
VERIFY_TOKEN = os.environ["WHATSAPP_VERIFY_TOKEN"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = Flask(__name__)
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.5  # 1.5s, 3s, 6s

def verify_signature(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        signature_header = request.headers.get("X-Hub-Signature-256", "")
        if not signature_header.startswith("sha256="):
            logger.warning("Missing or malformed signature header")
            return jsonify({"error": "invalid signature"}), 403

        received_sig = signature_header.split("sha256=", 1)[1]

        expected_sig = hmac.new(
            key=APP_SECRET.encode("utf-8"),
            msg=request.get_data(),  # raw body, must match exactly
            digestmod=hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(received_sig, expected_sig):
            logger.warning("Signature mismatch — possible spoofed request")
            return jsonify({"error": "invalid signature"}), 403

        return f(*args, **kwargs)
    return wrapper

def with_retries(max_retries=MAX_RETRIES, base_delay=BASE_BACKOFF_SECONDS):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return f(*args, **kwargs)
                except APIError as e:
                    # Postgrest/Supabase API errors — check if retryable
                    status = getattr(e, "code", None)
                    if status and str(status).startswith("4"):
                        logger.error(f"Non-retryable Supabase error: {e}")
                        raise
                    last_exc = e
                    logger.warning(
                        f"Supabase API error (attempt {attempt}/{max_retries}): {e}"
                    )
                except Exception as e:
                    last_exc = e
                    logger.warning(
                        f"Transient error (attempt {attempt}/{max_retries}): {e}"
                    )

                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))
                    time.sleep(delay)

            logger.error(f"All {max_retries} attempts failed: {last_exc}")
            raise last_exc
        return wrapper
    return decorator

@with_retries()
def message_already_exists(message_id: str) -> bool:
    result = (
        supabase.table("messages")
        .select("id")
        .eq("wa_message_id", message_id)
        .limit(1)
        .execute()
    )
    return len(result.data) > 0

@with_retries()
def insert_message(record: dict):
    return supabase.table("messages").insert(record).execute()

def save_message(wa_message_id, source, contact_id, direction,
                  message_type, content, raw_payload):
    try:
        if message_already_exists(wa_message_id):
            logger.info(f"Duplicate message {wa_message_id}, skipping insert")
            return {"status": "duplicate"}

        record = {
            "wa_message_id": wa_message_id,
            "source": source,
            "contact_id": contact_id,
            "direction": direction,
            "message_type": message_type,
            "content": content,
            "raw_payload": raw_payload,
        }
        insert_message(record)
        logger.info(f"Stored message {wa_message_id} from {contact_id}")
        return {"status": "stored"}
    except Exception as e:
        logger.error(f"Failed to store message {wa_message_id}: {e}")
        return {"status": "failed", "error": str(e)}
    
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    logger.warning("Webhook verification failed — token mismatch")
    return "verification failed", 403

@app.route("/webhook", methods=["POST"])
@verify_signature
def receive_message():
    payload = request.get_json(silent=True)
    if not payload:
        logger.warning("Received POST with no/invalid JSON body")
        return jsonify({"error": "invalid payload"}), 400
    results = []
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    wa_message_id = msg.get("id")
                    sender = msg.get("from")
                    msg_type = msg.get("type", "unknown")
                    content = (
                        msg.get("text", {}).get("body")
                        if msg_type == "text"
                        else None
                    )
                    result = save_message(
                        wa_message_id=wa_message_id,
                        source="whatsapp",
                        contact_id=sender,
                        direction="inbound",
                        message_type=msg_type,
                        content=content,
                        raw_payload=msg,
                    )
                    results.append(result)
    except Exception as e:
        logger.error(f"Error processing webhook payload: {e}")
        return jsonify({"status": "error", "detail": "processing failed"}), 200
    return jsonify({"status": "ok", "results": results}), 200

if __name__ == "__main__":
    app.run(port=5000, debug=False)