import requests
from flask import Flask, request, jsonify
import datetime
import os
ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"
PHONE_NUMBER_ID = "YOUR_PHONE_NUMBER_ID"
VERIFY_TOKEN = "YOUR_CUSTOM_VERIFY_TOKEN"
GRAPH_URL = "https://graph.facebook.com/v19.0"
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

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
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verification failed", 403
    
@app.route("/webhook", methods=["POST"])
def receive_webhook():
    data = request.get_json()
    try:
        value = data["entry"][0]["changes"][0]["value"]
        
        # Check if messages exist in the payload
        if "messages" in value:
            for msg in value["messages"]:
                msg_type = msg["type"]
                
                # Files can come as document, image, audio, or video
                if msg_type in ("document", "image", "audio", "video"):
                    media_id = msg[msg_type]["id"]
                    
                    # [CHANGED] 1. Get the user's phone number
                    user_number = msg.get("from", "unknown_user")
                    
                    # [CHANGED] 2. Get the current timestamp
                    # Format: YYYYMMDD_HHMMSS (e.g., 20260716_143000)
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    
                    # [CHANGED] 3. Determine the file extension
                    # WhatsApp sometimes provides a 'mime_type' or 'filename'. 
                    # We try to get the original extension, otherwise default to .bin
                    original_filename = msg[msg_type].get("filename", "")
                    mime_type = msg[msg_type].get("mime_type", "")
                    
                    ext = ".bin" # Default extension
                    if original_filename and "." in original_filename:
                        ext = original_filename.split(".")[-1]
                    elif "image" in mime_type:
                        ext = "jpg"
                    elif "pdf" in mime_type:
                        ext = "pdf"
                    elif "audio" in mime_type:
                        ext = "mp3"
                    elif "video" in mime_type:
                        ext = "mp4"
                        
                    # [CHANGED] 4. Construct the new filename: usernumber_timestamp.ext
                    new_filename = f"{user_number}_{timestamp}.{ext}"
                    save_path = f"downloads/{new_filename}"
                    
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