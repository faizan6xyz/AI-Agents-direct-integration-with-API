import requests
from flask import Flask, request, jsonify
ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"
PHONE_NUMBER_ID = "YOUR_PHONE_NUMBER_ID"
VERIFY_TOKEN = "YOUR_CUSTOM_VERIFY_TOKEN"
GRAPH_URL = "https://graph.facebook.com/v19.0"
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

def send_file(to_number: str, file_path: str, caption: str = ""):
    # Step 1: upload the file
    with open(file_path, "rb") as f:
        upload_resp = requests.post(
            f"{GRAPH_URL}/{PHONE_NUMBER_ID}/media",
            headers=HEADERS,
            files={"file": f},
            data={"messaging_product": "whatsapp"},
        )
    upload_resp.raise_for_status()
    media_id = upload_resp.json()["id"]
    # Step 2: send the uploaded file to a number
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "document",
        "document": {"id": media_id, "caption": caption, "filename": file_path.split("/")[-1]},
    }
    send_resp = requests.post(
        f"{GRAPH_URL}/{PHONE_NUMBER_ID}/messages",
        headers={**HEADERS, "Content-Type": "application/json"},
        json=payload,
    )
    send_resp.raise_for_status()
    return send_resp.json()

def download_file(media_id: str, save_path: str):
    # Step 1: get the temporary download URL for this media
    meta_resp = requests.get(f"{GRAPH_URL}/{media_id}", headers=HEADERS)
    meta_resp.raise_for_status()
    file_url = meta_resp.json()["url"]
    # Step 2: download the actual file bytes
    file_resp = requests.get(file_url, headers=HEADERS)
    file_resp.raise_for_status()
    with open(save_path, "wb") as f:
        f.write(file_resp.content)
    return save_path

app = Flask(__name__)
@app.route("/webhook", methods=["GET"]) # Flask decorator that tells your app: "when someone sends an HTTP GET request to the URL path /webhook, run the function defined right below this line."
def verify_webhook():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verification failed", 403

# A webhook is basically a notification system. Instead of you constantly asking "any new messages? any new messages?" (polling), you give the other service (Meta/WhatsApp) a URL, and they call you the moment something happens.
    
@app.route("/webhook", methods=["POST"])  # Flask decorator that tells your app: "when someone sends an HTTP POST request to the URL path /webhook, run the function defined right below this line."
def receive_webhook():
    data = request.get_json()
    try:
        value = data["entry"][0]["changes"][0]["value"]
        for msg in value.get("messages", []):
            msg_type = msg["type"]
            # Files can come as document, image, audio, or video
            if msg_type in ("document", "image", "audio", "video"):
                media_id = msg[msg_type]["id"]
                filename = msg[msg_type].get("filename", f"{media_id}.bin")
                save_path = f"downloads/{filename}"
                import os
                os.makedirs("downloads", exist_ok=True)
                download_file(media_id, save_path)
                print(f"Saved incoming file to {save_path}")
    except (KeyError, IndexError) as e:
        print(f"Unexpected payload: {e}")
    return jsonify({"status": "received"}), 200


if __name__ == "__main__":
    # Example: send a file (uncomment to test)
    # send_file("911234567890", "report.pdf", caption="Here's the report")
    app.run(port=5000, debug=True)