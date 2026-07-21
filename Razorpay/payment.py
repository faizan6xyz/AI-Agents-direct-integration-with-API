import os
import time
import hmac
import hashlib
import threading
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
load_dotenv()
app = Flask(__name__)
KEY_ID = os.environ["RAZORPAY_KEY_ID"]
KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
BASE_URL = "https://api.razorpay.com/v1"
LOCAL_API_URL = "http://localhost:5000"
AUTH = (KEY_ID, KEY_SECRET)
_processed_webhook_events = {}
_order_creation_cache = {}
_STORE_LOCK = threading.Lock()
_STORE_TTL_SECONDS = 24 * 60 * 60

class RazorpayError(Exception):
    pass

def _prune_store(store: dict):
    cutoff = time.time() - _STORE_TTL_SECONDS
    expired = [k for k, v in store.items() if v.get("_ts", 0) < cutoff]
    for k in expired:
        store.pop(k, None)

def _request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.request(method, url, auth=AUTH, timeout=10, **kwargs)
        except requests.RequestException as e:
            last_exc = e
            if attempt == 2:
                raise RazorpayError(f"Network error after retries: {e}") from e
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code >= 500 and attempt < 2:
            time.sleep(1.5 * (attempt + 1))
            continue
        return resp
    raise RazorpayError(f"Request failed after retries: {last_exc}")

def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    payload = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(KEY_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    expected = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")

@app.route("/api/payment/create", methods=["POST"])
def create_payment():
    body = request.get_json(silent=True) or {}
    amount_rupees = str(body.get("amount", "20.00"))
    amount_paise = int(round(float(amount_rupees) * 100))
    currency = body.get("currency", "INR")
    receipt = body.get("receipt") or f"rcpt_{int(time.time() * 1000)}"
    idempotency_key = request.headers.get("Idempotency-Key") or body.get("idempotency_key")
    with _STORE_LOCK:
        _prune_store(_order_creation_cache)
        if idempotency_key and idempotency_key in _order_creation_cache:
            return jsonify(_order_creation_cache[idempotency_key]["response"])
    payload = {"amount": amount_paise,
        "currency": currency,
        "receipt": receipt,
        "payment_capture": 1,}
    try:
        resp = _request("POST", "/orders", json=payload)
    except RazorpayError as e:
        return jsonify({"error": "order_creation_failed", "details": str(e)}), 502
    if resp.status_code not in (200, 201):
        return jsonify({"error": "order_creation_failed", "details": resp.text}), 502
    order = resp.json()
    result = {"order_id": order["id"],
        "amount": order["amount"],
        "currency": order["currency"],
        "key_id": KEY_ID,}
    if idempotency_key:
        with _STORE_LOCK:
            _order_creation_cache[idempotency_key] = {"response": result, "_ts": time.time()}
    return jsonify(result)

@app.route("/api/payment/verify", methods=["POST"])
def verify_payment():
    body = request.get_json(silent=True) or {}
    order_id = body.get("razorpay_order_id")
    payment_id = body.get("razorpay_payment_id")
    signature = body.get("razorpay_signature")
    if not all([order_id, payment_id, signature]):
        return jsonify({"error": "missing_fields"}), 400
    if not verify_payment_signature(order_id, payment_id, signature):
        return jsonify({"error": "invalid_signature"}), 400
    try:
        resp = _request("GET", f"/payments/{payment_id}")
    except RazorpayError as e:
        return jsonify({"error": "razorpay_unavailable", "details": str(e)}), 503
    if resp.status_code != 200:
        return jsonify({"error": "status_check_failed", "details": resp.text}), 502
    status = resp.json().get("status")
    if status == "captured":
        return jsonify({"status": "Payment Done"})
    return jsonify({"status": status})

@app.route("/api/payment/status/<payment_id>", methods=["GET"])
def payment_status(payment_id):
    try:
        resp = _request("GET", f"/payments/{payment_id}")
    except RazorpayError as e:
        return jsonify({"error": "razorpay_unavailable", "details": str(e)}), 503
    if resp.status_code == 404:
        return jsonify({"error": "payment_not_found"}), 404
    if resp.status_code != 200:
        return jsonify({"error": "status_check_failed", "details": resp.text}), 502
    status = resp.json().get("status")
    if status == "captured":
        return jsonify({"status": "Payment Done"})
    return jsonify({"status": status})

@app.route("/api/payment/capture/<payment_id>", methods=["POST"])
def capture_payment(payment_id):
    body = request.get_json(silent=True) or {}
    try:
        status_resp = _request("GET", f"/payments/{payment_id}")
        if status_resp.status_code == 200 and status_resp.json().get("status") == "captured":
            return jsonify({"status": "Payment Done"})
        amount_paise = body.get("amount") or status_resp.json().get("amount")
        currency = body.get("currency") or status_resp.json().get("currency", "INR")
        resp = _request("POST", f"/payments/{payment_id}/capture",
            json={"amount": amount_paise, "currency": currency},)
    except RazorpayError as e:
        return jsonify({"error": "razorpay_unavailable", "details": str(e)}), 503
    if resp.status_code not in (200, 201):
        return jsonify({"error": "capture_failed", "details": resp.text}), 502
    data = resp.json()
    if data.get("status") == "captured":
        return jsonify({"status": "Payment Done"})
    return jsonify({"status": data.get("status")})

@app.route("/api/razorpay/webhook", methods=["POST"])
def razorpay_webhook():
    raw_body = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature")
    if not verify_webhook_signature(raw_body, signature):
        return jsonify({"error": "invalid_signature"}), 400
    event = request.get_json(silent=True)
    if event is None:
        return jsonify({"error": "invalid_json"}), 400
    event_id = event.get("id") or request.headers.get("X-Razorpay-Event-Id")
    if not event_id:
        return jsonify({"error": "missing_event_id"}), 400
    with _STORE_LOCK:
        _prune_store(_processed_webhook_events)
        if event_id in _processed_webhook_events:
            return jsonify({"received": True, "duplicate": True}), 200
    event_type = event.get("event")
    try:
        if event_type == "payment.captured":
            pass
    except Exception as e:
        return jsonify({"error": "processing_failed", "details": str(e)}), 500
    with _STORE_LOCK:
        _processed_webhook_events[event_id] = {"_ts": time.time()}
    return jsonify({"received": True}), 200

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    return jsonify({"error": "internal_error", "details": str(e)}), 500

def run_payment_pipeline(amount: str = "20.00", currency: str = "INR") -> dict:
    resp = requests.post(f"{LOCAL_API_URL}/api/payment/create",
        json={"amount": amount, "currency": currency},)
    if resp.status_code != 200:
        return {"success": False, "stage": "create", "error": resp.text}
    data = resp.json()
    order_id = data["order_id"]
    print(f"Order created: {order_id}")
    print(f"\nOpen Razorpay Checkout on the frontend with:")
    print(f"  key: {data['key_id']}")
    print(f"  order_id: {order_id}")
    print(f"  amount: {data['amount']}  currency: {data['currency']}\n")
    payment_id = input("Paste razorpay_payment_id after checkout completes: ").strip()
    signature = input("Paste razorpay_signature: ").strip()
    print("Verifying payment...")
    verify_resp = requests.post(f"{LOCAL_API_URL}/api/payment/verify",
        json={"razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,},)
    if verify_resp.status_code != 200:
        return {"success": False, "stage": "verify", "error": verify_resp.text, "order_id": order_id}
    verify_data = verify_resp.json()
    if verify_data.get("status") == "Payment Done":
        print("Payment completed successfully.")
        return {"success": True, "order_id": order_id, "payment_id": payment_id, "status": "Payment Done"}
    else:
        return {"success": False, "stage": "verify", "status": verify_data.get("status"), "order_id": order_id}

def _start_server_in_background():
    thread = threading.Thread(target=lambda: app.run(port=5000, debug=False, use_reloader=False),
        daemon=True,)
    thread.start()
    time.sleep(1.5)

if __name__ == "__main__":
    _start_server_in_background()
    result = run_payment_pipeline(amount="20.00")
    print(result)