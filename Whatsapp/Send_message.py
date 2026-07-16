import os
import re
import time
import logging
from collections import defaultdict, deque
import requests
from flask import Flask, request, jsonify
ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
SEND_API_KEY = os.environ.get("WHATSAPP_SEND_API_KEY")  # protects /send-test
GRAPH_URL = "https://graph.facebook.com/v19.0"
HEADERS_JSON = {"Authorization": f"Bearer {ACCESS_TOKEN}","Content-Type": "application/json",}  # application/json is a MIME type — a standardized label that tells whoever receives some data "here's the format this content is in, parse it accordingly."
HEADERS_AUTH_ONLY = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5
MAX_TEXT_LENGTH = 4096  # WhatsApp's own hard limit for text message bodies
MAX_FILE_SIZE_BYTES = {"image": 5 * 1024 * 1024,       # 5 MB
    "audio": 16 * 1024 * 1024,      # 16 MB
    "video": 16 * 1024 * 1024,      # 16 MB
    "document": 100 * 1024 * 1024,  # 100 MB 
    }
VALID_MEDIA_TYPES = set(MAX_FILE_SIZE_BYTES.keys())
MAX_BUTTONS = 3
MAX_BUTTON_TITLE_LEN = 20
MAX_BUTTON_ID_LEN = 256
MAX_LIST_SECTIONS = 10
MAX_LIST_ROWS_TOTAL = 10
MAX_LIST_ROW_TITLE_LEN = 24
MAX_LIST_ROW_DESC_LEN = 72
MAX_LIST_BUTTON_TEXT_LEN = 20
MAX_EMOJI_LEN = 8  # generous cap; a single emoji is rarely more than a few codepoints
RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60
_request_log = defaultdict(deque)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("whatsapp_sender")
if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
    log.warning("WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID not set — sends will fail.")
if not SEND_API_KEY:
    log.warning("WHATSAPP_SEND_API_KEY not set — /send-test will refuse all requests until it is.")
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  
class InvalidPhoneNumberError(Exception):
    pass

class MessageTooLongError(Exception):
    pass

class FileTooLargeError(Exception):
    pass

def validate_phone_number(number: str) -> str:
    if not number or not re.fullmatch(r"\+?[1-9]\d{7,14}", str(number)):
        raise InvalidPhoneNumberError(f"'{number}' is not a valid phone number.")
    return re.sub(r"[^\d+]", "", str(number))

def sanitize_field(value: str) -> str:
    if value is None:
        return ""
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value))
    return value.replace("\x00", "")

def validate_text_body(body: str) -> str:
    if body is None:
        body = ""
    if len(body) > MAX_TEXT_LENGTH:
        raise MessageTooLongError(f"Message is {len(body)} chars, exceeds WhatsApp's {MAX_TEXT_LENGTH}-char limit.")
    return body

def check_remote_file_size(url: str, msg_type: str):
    max_bytes = MAX_FILE_SIZE_BYTES.get(msg_type)
    if not max_bytes:
        return
    try:
        resp = requests.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        content_length = resp.headers.get("Content-Length")
        if content_length is not None and int(content_length) > max_bytes:
            raise FileTooLargeError(f"File at {url} is {content_length} bytes, exceeds {max_bytes} "
                f"byte limit for '{msg_type}'.")
    except requests.RequestException as e:
        log.warning(f"Could not verify remote file size for {url}: {e}")

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
            log.warning(f"Send attempt {attempt}/{MAX_RETRIES} failed: {e}. Retrying in {wait:.1f}s.")
            time.sleep(wait)
    raise last_exc

def send_whatsapp_message(recipient_number: str, message_body: str) -> dict:
    recipient_number = validate_phone_number(recipient_number)
    message_body = validate_text_body(message_body)
    payload = {"messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_number,
        "type": "text",
        "text": {"body": message_body},}
    url = f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    resp = request_with_retry("POST", url, headers=HEADERS_JSON, json=payload)
    return resp.json()

def send_whatsapp_media(recipient_number: str,msg_type: str,link: str,caption: str = None,filename: str = None,) -> dict:
    recipient_number = validate_phone_number(recipient_number)
    if msg_type not in VALID_MEDIA_TYPES:
        raise ValueError(f"msg_type must be one of {VALID_MEDIA_TYPES}, got '{msg_type}'")
    if not link:
        raise ValueError("A 'link' URL is required to send media.")
    check_remote_file_size(link, msg_type)
    media_obj = {"link": link}
    if caption and msg_type in ("image", "video", "document"):
        media_obj["caption"] = validate_text_body(caption)
    if filename and msg_type == "document":
        media_obj["filename"] = filename
    payload = {"messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_number,
        "type": msg_type,
        msg_type: media_obj,}
    url = f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    resp = request_with_retry("POST", url, headers=HEADERS_JSON, json=payload)
    return resp.json()

def send_whatsapp_location(recipient_number: str, latitude: float, longitude: float, name: str = None, address: str = None) -> dict:
    recipient_number = validate_phone_number(recipient_number)
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (TypeError, ValueError):
        raise ValueError("latitude/longitude must be numbers.")
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise ValueError("latitude must be in [-90, 90] and longitude in [-180, 180].")
    location_obj = {"latitude": lat, "longitude": lng}
    if name:
        location_obj["name"] = sanitize_field(name)[:1000]
    if address:
        location_obj["address"] = sanitize_field(address)[:1000]
    payload = {"messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_number,
        "type": "location",
        "location": location_obj,}
    url = f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    resp = request_with_retry("POST", url, headers=HEADERS_JSON, json=payload)
    return resp.json()

def send_whatsapp_reply_buttons(recipient_number: str, body_text: str, buttons: list) -> dict:
    recipient_number = validate_phone_number(recipient_number)
    body_text = validate_text_body(body_text)
    if not buttons or len(buttons) > MAX_BUTTONS:
        raise ValueError(f"Provide 1-{MAX_BUTTONS} buttons, got {len(buttons) if buttons else 0}.")
    formatted_buttons = []
    seen_ids = set()
    for b in buttons:
        btn_id = str(b.get("id", "")).strip()
        title = str(b.get("title", "")).strip()
        if not btn_id or not title:
            raise ValueError("Each button needs a non-empty 'id' and 'title'.")
        if len(btn_id) > MAX_BUTTON_ID_LEN:
            raise ValueError(f"Button id exceeds {MAX_BUTTON_ID_LEN} chars.")
        if len(title) > MAX_BUTTON_TITLE_LEN:
            raise ValueError(f"Button title '{title}' exceeds WhatsApp's {MAX_BUTTON_TITLE_LEN}-char limit.")
        if btn_id in seen_ids:
            raise ValueError(f"Duplicate button id '{btn_id}'.")
        seen_ids.add(btn_id)
        formatted_buttons.append({"type": "reply", "reply": {"id": btn_id, "title": title}})
    payload = {"messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": formatted_buttons},},}
    url = f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    resp = request_with_retry("POST", url, headers=HEADERS_JSON, json=payload)
    return resp.json()

def send_whatsapp_list(recipient_number: str, body_text: str, button_text: str, sections: list) -> dict:
    recipient_number = validate_phone_number(recipient_number)
    body_text = validate_text_body(body_text)
    if not button_text or len(button_text) > MAX_LIST_BUTTON_TEXT_LEN:
        raise ValueError(f"'button_text' must be 1-{MAX_LIST_BUTTON_TEXT_LEN} chars.")
    if not sections or len(sections) > MAX_LIST_SECTIONS:
        raise ValueError(f"Provide 1-{MAX_LIST_SECTIONS} sections.")
    total_rows = 0
    formatted_sections = []
    seen_row_ids = set()
    for section in sections:
        title = str(section.get("title", "")).strip()
        rows = section.get("rows", [])
        if not rows:
            raise ValueError(f"Section '{title}' has no rows.")
        formatted_rows = []
        for row in rows:
            row_id = str(row.get("id", "")).strip()
            row_title = str(row.get("title", "")).strip()
            row_desc = str(row.get("description", "")).strip()
            if not row_id or not row_title:
                raise ValueError("Each row needs a non-empty 'id' and 'title'.")
            if len(row_title) > MAX_LIST_ROW_TITLE_LEN:
                raise ValueError(f"Row title '{row_title}' exceeds {MAX_LIST_ROW_TITLE_LEN}-char limit.")
            if len(row_desc) > MAX_LIST_ROW_DESC_LEN:
                raise ValueError(f"Row description exceeds {MAX_LIST_ROW_DESC_LEN}-char limit.")
            if row_id in seen_row_ids:
                raise ValueError(f"Duplicate row id '{row_id}'.")
            seen_row_ids.add(row_id)
            row_obj = {"id": row_id, "title": row_title}
            if row_desc:
                row_obj["description"] = row_desc
            formatted_rows.append(row_obj)
            total_rows += 1
        if total_rows > MAX_LIST_ROWS_TOTAL:
            raise ValueError(f"Total rows across all sections exceeds {MAX_LIST_ROWS_TOTAL}.")
        formatted_sections.append({"title": title, "rows": formatted_rows})
    payload = {"messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_number,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text},
            "action": {"button": button_text, "sections": formatted_sections},},}
    url = f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    resp = request_with_retry("POST", url, headers=HEADERS_JSON, json=payload)
    return resp.json()

def send_whatsapp_reaction(recipient_number: str, message_id: str, emoji: str) -> dict:
    recipient_number = validate_phone_number(recipient_number)
    if not message_id or not str(message_id).startswith("wamid."):
        raise ValueError("message_id must be a valid WhatsApp message id (starts with 'wamid.').")
    if emoji is None:
        emoji = ""
    if len(emoji) > MAX_EMOJI_LEN:
        raise ValueError(f"emoji field exceeds {MAX_EMOJI_LEN} chars — pass a single emoji.")
    payload = {"messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_number,
        "type": "reaction",
        "reaction": {"message_id": message_id, "emoji": emoji},}
    url = f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    resp = request_with_retry("POST", url, headers=HEADERS_JSON, json=payload)
    return resp.json()

def send_whatsapp_contacts(recipient_number: str, contacts: list) -> dict:
    recipient_number = validate_phone_number(recipient_number)
    if not contacts:
        raise ValueError("Provide at least one contact.")
    formatted_contacts = []
    for c in contacts:
        formatted_name = str(c.get("formatted_name", "")).strip()
        if not formatted_name:
            raise ValueError("Each contact needs a non-empty 'formatted_name'.")
        contact_obj = {"name": {
                "formatted_name": sanitize_field(formatted_name)[:200],
                "first_name": sanitize_field(c.get("first_name", formatted_name))[:100],}}
        if c.get("phone"):
            contact_obj["phones"] = [{"phone": str(c["phone"]), "type": c.get("phone_type", "CELL")}]
        formatted_contacts.append(contact_obj)
    payload = {"messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_number,
        "type": "contacts",
        "contacts": formatted_contacts,}
    url = f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages"
    resp = request_with_retry("POST", url, headers=HEADERS_JSON, json=payload)
    return resp.json()

def require_api_key():
    if not SEND_API_KEY:
        return jsonify({"error": "Server not configured (missing API key)"}), 500
    provided = request.headers.get("X-API-Key", "")
    if not SEND_API_KEY or provided != SEND_API_KEY:
        log.warning("Rejected /send-test call: missing/invalid X-API-Key.")
        return jsonify({"error": "Unauthorized"}), 401
    return None

def check_rate_limit(ip: str) -> bool:
    now = time.time()
    q = _request_log[ip]
    while q and now - q[0] > RATE_LIMIT_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= RATE_LIMIT_MAX_REQUESTS:
        return False
    q.append(now)
    return True

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    return "Verification successful", 200

@app.route("/webhook", methods=["POST"])
def receive_webhook():
    return jsonify({"status": "received"}), 200

@app.route("/send-test", methods=["POST"])
def test_send():
    auth_error = require_api_key()
    if auth_error:
        return auth_error
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if not check_rate_limit(client_ip):
        log.warning(f"Rate limit exceeded for {client_ip}")
        return jsonify({"error": "Rate limit exceeded, slow down"}), 429
    data = request.get_json(silent=True)
    if not data or "phone" not in data:
        return jsonify({"error": "Please provide at least 'phone'"}), 400
    phone = data["phone"]
    msg_type = data.get("type", "text")
    try:
        if msg_type == "text":
            if "msg" not in data:
                return jsonify({"error": "'msg' is required for type 'text'"}), 400
            result = send_whatsapp_message(phone, data["msg"])
        elif msg_type in VALID_MEDIA_TYPES:
            if "link" not in data:
                return jsonify({"error": f"'link' is required for type '{msg_type}'"}), 400
            result = send_whatsapp_media(phone,
                msg_type,
                link=data["link"],
                caption=data.get("caption"),
                filename=data.get("filename"),)
        elif msg_type == "location":
            if "latitude" not in data or "longitude" not in data:
                return jsonify({"error": "'latitude' and 'longitude' are required"}), 400
            result = send_whatsapp_location(phone,
                data["latitude"],
                data["longitude"],
                name=data.get("name"),
                address=data.get("address"),)
        elif msg_type == "button":
            if "body" not in data or "buttons" not in data:
                return jsonify({"error": "'body' and 'buttons' are required"}), 400
            result = send_whatsapp_reply_buttons(phone, data["body"], data["buttons"])
        elif msg_type == "list":
            if "body" not in data or "button_text" not in data or "sections" not in data:
                return jsonify({"error": "'body', 'button_text', and 'sections' are required"}), 400
            result = send_whatsapp_list(phone, data["body"], data["button_text"], data["sections"])
        elif msg_type == "reaction":
            if "message_id" not in data:
                return jsonify({"error": "'message_id' is required"}), 400
            result = send_whatsapp_reaction(phone, data["message_id"], data.get("emoji", ""))
        elif msg_type == "contacts":
            if "contacts" not in data:
                return jsonify({"error": "'contacts' is required"}), 400
            result = send_whatsapp_contacts(phone, data["contacts"])
        else:
            return jsonify({"error": f"Unsupported type '{msg_type}'"}), 400
        return jsonify({"status": "sent", "details": result}), 200
    except InvalidPhoneNumberError as e:
        return jsonify({"error": str(e)}), 400
    except MessageTooLongError as e:
        return jsonify({"error": str(e)}), 400
    except FileTooLargeError as e:
        return jsonify({"error": str(e)}), 413
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except requests.RequestException as e:
        log.error(f"Send failed after retries: {e}")
        return jsonify({"error": "Failed to send message after retries"}), 502
    except Exception as e:
        log.exception(f"Unexpected error in /send-test: {e}")
        return jsonify({"error": "Internal error"}), 500

if __name__ == "__main__":
    # debug=True is convenient locally but should be False in production
    app.run(port=5000, debug=True)
    
    
'''   
    # Image
    curl -X POST http://localhost:5000/send-test \
    -H "X-API-Key: your-secret" -H "Content-Type: application/json" \
    -d '{
        "phone": "15551234567",
        "type": "image",
        "link": "https://example.com/photo.jpg",
        "caption": "optional caption text"
    }'

    # Document
    curl -X POST http://localhost:5000/send-test \
    -H "X-API-Key: your-secret" -H "Content-Type: application/json" \
    -d '{
        "phone": "15551234567",
        "type": "document",
        "link": "https://example.com/report.pdf",
        "filename": "report.pdf"
    }'

    # Audio (no caption/filename supported by WhatsApp for audio)
    curl -X POST http://localhost:5000/send-test \
    -H "X-API-Key: your-secret" -H "Content-Type: application/json" \
    -d '{"phone": "15551234567", "type": "audio", "link": "https://example.com/voice.mp3"}'

    # Video
    curl -X POST http://localhost:5000/send-test \
    -H "X-API-Key: your-secret" -H "Content-Type: application/json" \
    -d '{
        "phone": "15551234567",
        "type": "video",
        "link": "https://example.com/clip.mp4",
        "caption": "optional caption"
    }'
'''