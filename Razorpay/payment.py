import os
import time
import json
import hmac
import hashlib
import logging
import sqlite3
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests
load_dotenv()
logging.basicConfig( level=logging.INFO , format="%(asctime)s %(levelname)s %(name)s: %(message)s", )
logger = logging.getLogger("payment")
app = Flask(__name__)
def _require(key):
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val

KEY_ID = _require("RAZORPAY_KEY_ID")
KEY_SECRET = _require("RAZORPAY_KEY_SECRET")
WEBHOOK_SECRET = _require("RAZORPAY_WEBHOOK_SECRET")
RATE_LIMIT_STORAGE_URI = _require("RATE_LIMIT_STORAGE_URI")
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024  # 256KB request body cap (item #12)
limiter = Limiter( key_func=get_remote_address , app=app , default_limits=[] , storage_uri=RATE_LIMIT_STORAGE_URI , )
BASE_URL = "https://api.razorpay.com/v1"
AUTH = (KEY_ID, KEY_SECRET)
DB_PATH = os.environ.get("PAYMENT_DB_PATH", "payments.db")
_STORE_TTL_SECONDS = 18 * 60 * 60
PRICE_TABLE_PAISE = { "basic_monthly": 20000, }
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
        conn.executescript(""" CREATE TABLE IF NOT EXISTS processed_webhook_events (
                                event_id   TEXT PRIMARY KEY,
                                event_type TEXT,
                                created_at REAL NOT NULL );
                            
                            CREATE TABLE IF NOT EXISTS order_creation_cache (
                                idempotency_key TEXT PRIMARY KEY,
                                response_json   TEXT,
                                created_at      REAL NOT NULL ); 
                                
                            CREATE TABLE IF NOT EXISTS orders (
                                order_id   TEXT PRIMARY KEY,
                                plan_id    TEXT,
                                amount     INTEGER,
                                currency   TEXT,
                                status     TEXT NOT NULL DEFAULT 'created',
                                created_at REAL NOT NULL,
                                updated_at REAL NOT NULL );
                                
                            CREATE TABLE IF NOT EXISTS verify_cache (
                                payment_id  TEXT PRIMARY KEY,
                                response_json TEXT NOT NULL,
                                created_at  REAL NOT NULL );
                                
                            CREATE INDEX IF NOT EXISTS idx_processed_created ON processed_webhook_events(created_at);
                            CREATE INDEX IF NOT EXISTS idx_ordercache_created ON order_creation_cache(created_at);
                            CREATE INDEX IF NOT EXISTS idx_verify_created ON verify_cache(created_at);""")
        
def _prune_table(conn, table: str):
    cutoff = time.time() - _STORE_TTL_SECONDS
    conn.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))

def _release_idempotency_claim(idempotency_key: str):
    if not idempotency_key:
        return
    with _get_db() as conn:
        conn.execute("DELETE FROM order_creation_cache WHERE idempotency_key = ? AND response_json IS NULL",
            (idempotency_key,),)
        conn.commit()

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

@app.route("/checkout")
def checkout_page():
    plan_id = request.args.get("plan_id" , "basic_monthly")
    if plan_id not in PRICE_TABLE_PAISE:
        return jsonify({"error": "invalid_plan_id"}), 400
    return render_template("checkout.html", plan_id=plan_id, key_id=KEY_ID)

@app.route("/api/payment/create", methods=["POST"])
@limiter.limit("20 per minute")
def create_payment():
    body = request.get_json(silent=True) or {}
    plan_id = body.get("plan_id")
    if not plan_id or plan_id not in PRICE_TABLE_PAISE:
        return jsonify({"error": "invalid_plan_id"}), 400
    amount_paise = PRICE_TABLE_PAISE[plan_id]
    currency = body.get("currency", "INR")
    if currency not in ALLOWED_CURRENCIES:
        return jsonify({"error": "unsupported_currency"}), 400
    receipt = body.get("receipt") or f"rcpt_{int(time.time() * 1000)}"
    idempotency_key = request.headers.get("Idempotency-Key") or body.get("idempotency_key")
    with _get_db() as conn:
        _prune_table(conn, "order_creation_cache")
        conn.commit()
        if idempotency_key:
            row = conn.execute("SELECT response_json FROM order_creation_cache WHERE idempotency_key = ?",
                               (idempotency_key,),).fetchone()
            if row:
                if row[0] is None:
                    return jsonify({"error": "request_in_progress"}), 409
                return jsonify(json.loads(row[0]))
            try:
                conn.execute("INSERT INTO order_creation_cache (idempotency_key, response_json, created_at) "
                             "VALUES (?, NULL, ?)",
                             (idempotency_key, time.time()),)
                conn.commit()
            except sqlite3.IntegrityError:
                return jsonify({"error": "request_in_progress"}), 409
    payload = {"amount": amount_paise , "currency": currency , "receipt": receipt , "payment_capture": 1, }
    try:
        resp = _request("POST", "/orders", json=payload)
    except RazorpayError as e:
        logger.error("order_creation_failed (network): %s", e)
        _release_idempotency_claim(idempotency_key)
        return jsonify({"error": "order_creation_failed", "details": str(e)}), 502
    if resp.status_code not in (200, 201):
        logger.error("order_creation_failed (razorpay %s): %s", resp.status_code, resp.text)
        _release_idempotency_claim(idempotency_key)
        return jsonify({"error": "order_creation_failed", "details": resp.text}), 502
    order = resp.json()
    result = { "order_id": order["id"] , "amount": order["amount"] , "currency": order["currency"] , "key_id": KEY_ID ,}
    now = time.time()
    with _get_db() as conn:
        conn.execute(""" INSERT OR IGNORE INTO orders 
                     (order_id, plan_id, amount, currency, status, created_at, updated_at) 
                     VALUES (?, ?, ?, ?, 'created', ?, ?) """, 
                     (order["id"], plan_id, order["amount"], order["currency"], now, now),)
        conn.commit()
    if idempotency_key:
        with _get_db() as conn:
            conn.execute("UPDATE order_creation_cache SET response_json = ?, created_at = ? WHERE idempotency_key = ?",
                (json.dumps(result), time.time(), idempotency_key),)
            conn.commit()
    return jsonify(result)

@app.route("/api/payment/verify", methods=["POST"])
@limiter.limit("30 per minute")
def verify_payment():
    body = request.get_json(silent=True) or {}
    order_id = body.get("razorpay_order_id")
    payment_id = body.get("razorpay_payment_id")
    signature = body.get("razorpay_signature")
    if not all([order_id, payment_id, signature]):
        return jsonify({"error": "missing_fields"}), 400
    if not verify_payment_signature(order_id, payment_id, signature):
        logger.warning("invalid_signature order_id=%s payment_id=%s", order_id, payment_id)
        return jsonify({"error": "invalid_signature"}), 400
    with _get_db() as conn:
        _prune_table(conn, "verify_cache")
        conn.commit()
        row = conn.execute( "SELECT response_json FROM verify_cache WHERE payment_id = ?", (payment_id,), ).fetchone()
        if row:
            return jsonify(json.loads(row[0]))
    try:
        resp = _request("GET", f"/payments/{payment_id}")
    except RazorpayError as e:
        logger.error("razorpay_unavailable during verify: %s", e)
        return jsonify({"error": "razorpay_unavailable", "details": str(e)}), 503
    if resp.status_code != 200:
        logger.error("status_check_failed (verify, %s): %s", resp.status_code, resp.text)
        return jsonify({"error": "status_check_failed", "details": resp.text}), 502
    status = resp.json().get("status")
    result = {"status": "Payment Done"} if status == "captured" else {"status": status}
    _TERMINAL_STATUSES = {"captured", "failed"}
    if status in _TERMINAL_STATUSES:
        with _get_db() as conn:
            conn.execute("""INSERT OR REPLACE INTO verify_cache 
                         (payment_id, response_json, created_at)
                         VALUES (?, ?, ?)""",
                         (payment_id, json.dumps(result), time.time()))
            conn.commit()
    return jsonify(result)

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
        if status_resp.status_code == 404:
            return jsonify({"error": "payment_not_found"}), 404
        if status_resp.status_code != 200:
            logger.error("capture_status_check_failed (%s): %s", status_resp.status_code, status_resp.text)
            return jsonify({"error": "capture_status_check_failed", "details": status_resp.text}), 502
        amount_paise = status_resp.json().get("amount")
        currency = status_resp.json().get("currency", "INR")
        if body.get("amount") is not None:
            logger.warning( "capture_payment received client-supplied amount for payment_id=%s; ignoring it", payment_id , )
        resp = _request( "POST" , f"/payments/{payment_id}/capture" , json={"amount": amount_paise, "currency": currency}, )
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

def _set_order_status(order_id: str, status: str):
    if not order_id:
        return
    with _get_db() as conn:
        conn.execute( "UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?", 
                     (status, time.time(), order_id),)
        conn.commit()

def _handle_payment_captured(event: dict):
    payment_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id")
    order_id = payment_entity.get("order_id")
    logger.info("payment.captured received for payment_id=%s order_id=%s", payment_id, order_id)
    _set_order_status(order_id, "captured")
    # TODO: provision access, send confirmation email.

def _handle_payment_failed(event: dict):
    payment_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id")
    order_id = payment_entity.get("order_id")
    error_desc = payment_entity.get("error_description")
    logger.warning("payment.failed for payment_id=%s order_id=%s: %s", payment_id, order_id, error_desc)
    _set_order_status(order_id, "failed")
    # TODO: notify user, trigger dunning/retry flow.

def _handle_order_paid(event: dict):
    order_entity = event.get("payload", {}).get("order", {}).get("entity", {})
    order_id = order_entity.get("id")
    logger.info("order.paid received for order_id=%s", order_id)
    _set_order_status(order_id, "paid")
    # TODO: fulfil order.

_WEBHOOK_HANDLERS = {"payment.captured": _handle_payment_captured , "payment.failed": _handle_payment_failed , "order.paid": _handle_order_paid , }

@app.route("/api/razorpay/webhook", methods=["POST"])
@limiter.limit("120 per minute")
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
            conn.execute( '''INSERT INTO processed_webhook_events 
                         (event_id, event_type, created_at) 
                         VALUES (?, ?, ?)''',
                         (event_id, event_type, time.time()),)
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
            conn.execute("DELETE FROM processed_webhook_events WHERE event_id = ?", (event_id,))
            conn.commit()
        return jsonify({"error": "processing_failed", "details": str(e)}), 500
    return jsonify({"received": True}), 200

@app.route("/healthz")
def healthz():
    try:
        with _get_db() as conn:
            conn.execute("SELECT 1").fetchone()
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("healthz_failed: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 503

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    logger.exception("Unhandled exception")
    return jsonify({"error": "internal_error", "details": str(e)}), 500

_init_db()

if __name__ == "__main__":
# Local dev only. In production run:
#   gunicorn -w 4 -b 0.0.0.0:5000 app:app
    app.run(port=5000, debug=False)