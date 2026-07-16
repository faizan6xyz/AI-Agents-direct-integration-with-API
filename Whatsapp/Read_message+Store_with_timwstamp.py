import os
import csv
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from openpyxl import Workbook, load_workbook
VERIFY_TOKEN = "your_custom_verify_token"   # must match what you set in Meta App dashboard
CSV_FILE = "whatsapp_messages.csv"
EXCEL_FILE = "whatsapp_messages.xlsx"
CSV_HEADERS = ["Timestamp", "Sender Number", "Message"]
file_lock = threading.Lock()
app = Flask(__name__)
def ensure_csv_exists():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)

def ensure_excel_exists():
    if not os.path.exists(EXCEL_FILE):
        wb = Workbook()
        ws = wb.active
        ws.title = "Messages"
        ws.append(CSV_HEADERS)
        wb.save(EXCEL_FILE)

def log_message(timestamp: str, sender: str, message: str):
    with file_lock:
        ensure_csv_exists()
        ensure_excel_exists()
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, sender, message])
        wb = load_workbook(EXCEL_FILE)
        ws = wb["Messages"]
        ws.append([timestamp, sender, message])
        wb.save(EXCEL_FILE)

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def receive_webhook_messgae():
    data = request.get_json(silent=True) or {}
    try:
        entries = data.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    sender = msg.get("from", "unknown")
                    wa_timestamp = msg.get("timestamp")
                    if wa_timestamp:
                        timestamp = datetime.fromtimestamp(int(wa_timestamp)).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    else:
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    msg_type = msg.get("type")
                    if msg_type == "text":
                        message_text = msg["text"]["body"]
                    else:
                        message_text = f"[Unsupported message type: {msg_type}]"
                    print(f"New message from {sender}: {message_text}")
                    log_message(timestamp, sender, message_text)
    except Exception as e:
        print(f"Error processing webhook payload: {e}")
    return jsonify({"status": "received"}), 200

if __name__ == "__main__":
    ensure_csv_exists()
    ensure_excel_exists()
    app.run(host="0.0.0.0", port=5000, debug=True)