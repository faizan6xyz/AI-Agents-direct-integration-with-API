import os
import re
import hmac
import time
import logging
import mimetypes
import datetime
import hashlib
import requests
from flask import Flask, request, jsonify
ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN") #env
PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID") #env
VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN") #env
APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET")  #env
API_VERSION = os.environ.get("WHATSAPP_API_VERSION") #env
GRAPH_URL = f"https://graph.facebook.com/{API_VERSION}" 
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
DOWNLOAD_DIR = "Download"
REQUEST_TIMEOUT = 15          # seconds, for every outbound HTTP call
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5      # seconds; doubles-ish each retry
MAX_FILE_SIZE_BYTES = {
    "image": 5 * 1024 * 1024,      # 5 MB
    "audio": 16 * 1024 * 1024,     # 16 MB
    "video": 16 * 1024 * 1024,     # 16 MB
    "document": 100 * 1024 * 1024,  # 100 MB
}
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",)
log = logging.getLogger("whatsapp_webhook")
if not all([ACCESS_TOKEN, PHONE_NUMBER_ID, VERIFY_TOKEN, APP_SECRET]):
    log.warning("One or more required environment variables are missing "
        "(WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, "
        "WHATSAPP_VERIFY_TOKEN, WHATSAPP_APP_SECRET). "
        "The webhook will not work correctly until these are set.")
app = Flask(__name__)

def is_valid_signature(req) -> bool:
    if not APP_SECRET:
        log.error("APP_SECRET not configured — refusing to process webhook.")
        return False
    signature_header = req.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256="):
        log.warning("Missing or malformed X-Hub-Signature-256 header.")
        return False
    received_sig = signature_header.split("sha256=", 1)[1]
    expected_sig = hmac.new(APP_SECRET.encode("utf-8"), req.get_data(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_sig, expected_sig)

def sanitize_component(value: str, fallback: str = "unknown") -> str:
    if not value:
        return fallback
    value = str(value)
    value = value.replace("\x00", "")
    value = re.sub(r"[^A-Za-z0-9_\-.]", "_", value)
    return value[:80] or fallback  # cap length too

def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if resp.status_code >= 500:
                raise requests.HTTPError(f"Server error {resp.status_code}")
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            last_exc = e
            wait = RETRY_BACKOFF_BASE ** attempt
            log.warning(
                f"Request to {url} failed (attempt {attempt}/{MAX_RETRIES}): {e}. "
                f"Retrying in {wait:.1f}s...")
            time.sleep(wait)
    raise last_exc

class FileTooLargeError(Exception):
    pass

def download_file(media_id: str, save_path: str, msg_type: str) -> str:
    max_bytes = MAX_FILE_SIZE_BYTES.get(msg_type)
    # Step 1: get metadata (includes a temporary download URL + declared file_size)
    meta_resp = request_with_retry("GET", f"{GRAPH_URL}/{media_id}", headers=HEADERS)
    meta = meta_resp.json()
    file_url = meta["url"]
    declared_size = meta.get("file_size")
    if max_bytes and declared_size and int(declared_size) > max_bytes:
        raise FileTooLargeError(f"Declared size {declared_size} bytes exceeds {max_bytes} byte "
            f"limit for '{msg_type}'. Skipping download.")
    # Step 2: stream the download, enforcing the cap chunk-by-chunk in case
    # the server's declared size can't be trusted or is missing
    downloaded = 0
    tmp_path = save_path + ".part"
    try:
        with requests.get(file_url, headers=HEADERS, stream=True, timeout=REQUEST_TIMEOUT) as file_resp:
            file_resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in file_resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if max_bytes and downloaded > max_bytes:
                        raise FileTooLargeError(f"'{msg_type}' download exceeded {max_bytes} byte "
                            f"limit mid-stream. Aborting.")
                    f.write(chunk)
        os.replace(tmp_path, save_path)  # atomic-ish move once fully validated
        return save_path
    except Exception:
        # Clean up partial file on any failure (size violation, network error, etc.)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

def guess_extension(msg_payload: dict, mime_type: str) -> str:
    original_filename = msg_payload.get("filename", "")
    if original_filename and "." in original_filename:
        return sanitize_component(original_filename.rsplit(".", 1)[-1], "bin")
    ext = mimetypes.guess_extension(mime_type or "") or ".bin"
    return ext.lstrip(".")

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    log.warning("Webhook verification attempt failed (bad verify token).")
    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def receive_webhook():
    # --- Security gate: reject anything not genuinely signed by Meta ---
    if not is_valid_signature(request):
        log.error("Rejected webhook POST: invalid or missing signature.")
        return jsonify({"status": "invalid signature"}), 403
    data = request.get_json(silent=True)
    if not data:
        log.warning("Received webhook POST with no/invalid JSON body.")
        return jsonify({"status": "ignored"}), 200

    try:
        value = data["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError) as e:
        log.warning(f"Unexpected payload shape: {e}")
        return jsonify({"status": "ignored"}), 200

    for msg in value.get("messages", []):
        # Isolate failures per-message so one bad/oversized file doesn't
        # stop the rest of the batch from being processed.
        try:
            process_message(msg)
        except FileTooLargeError as e:
            log.warning(f"Skipped media (too large): {e}")
        except requests.RequestException as e:
            log.error(f"Network failure processing message {msg.get('id')}: {e}")
        except Exception as e:
            log.exception(f"Unexpected error processing message {msg.get('id')}: {e}")
    return jsonify({"status": "received"}), 200

def process_message(msg: dict):
    msg_type = msg.get("type")
    if msg_type not in ("document", "image", "audio", "video"):
        return  # nothing to download for text/location/etc.
    media_id = msg[msg_type]["id"]
    mime_type = msg[msg_type].get("mime_type", "")
    user_number = sanitize_component(msg.get("from"), "unknown_user")
    msg_id = sanitize_component(msg.get("id"), "no_id")
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    ext = guess_extension(msg[msg_type], mime_type)
    new_filename = f"{user_number}_{timestamp}_{msg_id}.{ext}"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    save_path = os.path.join(DOWNLOAD_DIR, new_filename)
    download_file(media_id, save_path, msg_type)
    log.info(f"Saved incoming {msg_type} to {save_path}")

if __name__ == "__main__":
    # debug=True is convenient locally but should be False in production
    app.run(port=5000, debug=True)