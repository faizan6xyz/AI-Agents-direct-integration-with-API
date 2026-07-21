import os
import time
import hmac
import hashlib
import logging
import sqlite3
import threading
import requests
from decimal import Decimal, ROUND_HALF_UP
from flask import Flask, request, jsonify
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",)
logger = logging.getLogger("payment")
app = Flask(__name__)
KEY_ID = os.environ["RAZORPAY_KEY_ID"]
KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
BASE_URL = "https://api.razorpay.com/v1"
LOCAL_API_URL = "http://localhost:5000"
AUTH = (KEY_ID, KEY_SECRET)
DB_PATH = os.environ.get("PAYMENT_DB_PATH", "payments.db")
_STORE_TTL_SECONDS = 24 * 60 * 60
PRICE_TABLE_PAISE = {"basic_monthly": 20000,     } # 2000
ALLOWED_CURRENCIES = {"INR"}

class RazorpayError(Exception):
    pass

def _get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn

def _init_db():
    with _get_db() as conn:
        conn.execute(""" CREATE TABLE IF NOT EXISTS processed_webhook_events (event_id   TEXT PRIMARY KEY,event_type TEXT,created_at REAL NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS order_creation_cache (idempotency_key TEXT PRIMARY KEY,response_json   TEXT NOT NULL,created_at      REAL NOT NULL )""")
        conn.commit()

def _prune_table(conn, table: str):
    cutoff = time.time() - _STORE_TTL_SECONDS
    conn.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))

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

def _rupees_to_paise(rupees) -> int:
    d = Decimal(str(rupees)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(d * 100)

@app.route("/api/payment/create", methods=["POST"])
def create_payment():
    body = request.get_json(silent=True) or {}
    plan_id = body.get("plan_id")
    if not plan_id or plan_id not in PRICE_TABLE_PAISE:
        return jsonify({"error": "invalid_plan_id"}), 400
    amount_paise = PRICE_TABLE_PAISE[plan_id]  # already an int, no float math (item #3)
    currency = body.get("currency", "INR")
    if currency not in ALLOWED_CURRENCIES:
        return jsonify({"error": "unsupported_currency"}), 400
    receipt = body.get("receipt") or f"rcpt_{int(time.time() * 1000)}"
    idempotency_key = request.headers.get("Idempotency-Key") or body.get("idempotency_key")
    with _get_db() as conn:
        _prune_table(conn, "order_creation_cache")
        conn.commit()
        if idempotency_key:
            row = conn.execute("SELECT response_json FROM order_creation_cache WHERE idempotency_key = ?",(idempotency_key,),).fetchone()
            if row:
                import json
                return jsonify(json.loads(row[0]))
    payload = {"amount": amount_paise,
        "currency": currency,
        "receipt": receipt,
        "payment_capture": 1,}
    try:
        resp = _request("POST", "/orders", json=payload)
    except RazorpayError as e:
        logger.error("order_creation_failed (network): %s", e)
        return jsonify({"error": "order_creation_failed", "details": str(e)}), 502
    if resp.status_code not in (200, 201):
        logger.error("order_creation_failed (razorpay %s): %s", resp.status_code, resp.text)
        return jsonify({"error": "order_creation_failed", "details": resp.text}), 502
    order = resp.json()
    result = {
        "order_id": order["id"],
        "amount": order["amount"],
        "currency": order["currency"],
        "key_id": KEY_ID,}
    if idempotency_key:
        import json
        with _get_db() as conn:
            conn.execute("""INSERT OR REPLACE INTO order_creation_cache (idempotency_key, response_json, created_at)VALUES (?, ?, ?)""",(idempotency_key, json.dumps(result), time.time()),)
            conn.commit()
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
        logger.warning("invalid_signature for order_id=%s payment_id=%s", order_id, payment_id)
        return jsonify({"error": "invalid_signature"}), 400
    try:
        resp = _request("GET", f"/payments/{payment_id}")
    except RazorpayError as e:
        logger.error("razorpay_unavailable during verify: %s", e)
        return jsonify({"error": "razorpay_unavailable", "details": str(e)}), 503
    if resp.status_code != 200:
        logger.error("status_check_failed (verify, %s): %s", resp.status_code, resp.text)
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
        logger.error("razorpay_unavailable during status check: %s", e)
        return jsonify({"error": "razorpay_unavailable", "details": str(e)}), 503
    if resp.status_code == 404:
        return jsonify({"error": "payment_not_found"}), 404
    if resp.status_code != 200:
        logger.error("status_check_failed (%s): %s", resp.status_code, resp.text)
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
        amount_paise = status_resp.json().get("amount") if status_resp.status_code == 200 else None
        currency = status_resp.json().get("currency", "INR") if status_resp.status_code == 200 else "INR"
        if body.get("amount") is not None:
            logger.warning("capture_payment received client-supplied amount for payment_id=%s; ignoring it",
                payment_id,)
        resp = _request("POST",
            f"/payments/{payment_id}/capture",
            json={"amount": amount_paise, "currency": currency},)
    except RazorpayError as e:
        logger.error("razorpay_unavailable during capture: %s", e)
        return jsonify({"error": "razorpay_unavailable", "details": str(e)}), 503
    if resp.status_code not in (200, 201):
        logger.error("capture_failed (%s): %s", resp.status_code, resp.text)
        return jsonify({"error": "capture_failed", "details": resp.text}), 502
    data = resp.json()
    if data.get("status") == "captured":
        return jsonify({"status": "Payment Done"})
    return jsonify({"status": data.get("status")})

def _handle_payment_captured(event: dict):
    payment_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id")
    logger.info("payment.captured received for payment_id=%s", payment_id)
    # TODO: update subscription/order status, send confirmation email, etc.

def _handle_payment_failed(event: dict):
    payment_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id")
    error_desc = payment_entity.get("error_description")
    logger.warning("payment.failed for payment_id=%s: %s", payment_id, error_desc)
    # TODO: notify the user, trigger dunning/retry flow, etc.

def _handle_order_paid(event: dict):
    order_entity = event.get("payload", {}).get("order", {}).get("entity", {})
    order_id = order_entity.get("id")
    logger.info("order.paid received for order_id=%s", order_id)
    # TODO: reconcile order status, fulfil the order, etc.

_WEBHOOK_HANDLERS = {"payment.captured": _handle_payment_captured,
    "payment.failed": _handle_payment_failed,
    "order.paid": _handle_order_paid,}

@app.route("/api/razorpay/webhook", methods=["POST"])
def razorpay_webhook():
    raw_body = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature")
    if not verify_webhook_signature(raw_body, signature):
        logger.warning("webhook invalid_signature")
        return jsonify({"error": "invalid_signature"}), 400
    event = request.get_json(silent=True)
    if event is None:
        return jsonify({"error": "invalid_json"}), 400
    event_id = event.get("id") or request.headers.get("X-Razorpay-Event-Id")
    if not event_id:
        return jsonify({"error": "missing_event_id"}), 400
    event_type = event.get("event")
    with _get_db() as conn:
        _prune_table(conn, "processed_webhook_events")
        conn.commit()
        try:
            conn.execute("INSERT INTO processed_webhook_events (event_id, event_type, created_at) "
                "VALUES (?, ?, ?)",(event_id, event_type, time.time()),)
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({"received": True, "duplicate": True}), 200
    try:
        handler = _WEBHOOK_HANDLERS.get(event_type)
        if handler:
            handler(event)
        else:
            logger.info("Unhandled webhook event_type=%s event_id=%s", event_type, event_id)
    except Exception as e:
        logger.error("processing_failed for event_id=%s: %s", event_id, e)
        with _get_db() as conn:
            conn.execute("DELETE FROM processed_webhook_events WHERE event_id = ?",(event_id,),)
            conn.commit()
        return jsonify({"error": "processing_failed", "details": str(e)}), 500
    return jsonify({"received": True}), 200

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    logger.exception("Unhandled exception")
    return jsonify({"error": "internal_error", "details": str(e)}), 500

def run_payment_pipeline(plan_id: str = "basic_monthly", currency: str = "INR") -> dict:
    resp = requests.post(f"{LOCAL_API_URL}/api/payment/create",
        json={"plan_id": plan_id, "currency": currency},)
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
    thread = threading.Thread(
        target=lambda: app.run(port=5000, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()
    time.sleep(1.5)

_init_db()

if __name__ == "__main__":
    _start_server_in_background()
    result = run_payment_pipeline(plan_id="basic_monthly")
    print(result)