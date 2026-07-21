import os
import re
import time
import json
import uuid
import base64
import zlib
import sqlite3
import logging
import threading
from decimal import Decimal, InvalidOperation
from contextlib import contextmanager
import functools
import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography import x509
load_dotenv()

def _require(key):
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val

CLIENT_ID = _require("PAYPAL_CLIENT_ID")
SECRET = _require("PAYPAL_SECRET")
WEBHOOK_ID = _require("PAYPAL_WEBHOOK_ID")
FLASK_SECRET_KEY = _require("FLASK_SECRET_KEY")
RETURN_URL = os.environ.get("RETURN_URL", "https://example.com/success")
CANCEL_URL = os.environ.get("CANCEL_URL", "https://example.com/cancel")
DB_PATH = os.environ.get("DB_PATH", "payments.db")
RATE_LIMIT_STORAGE_URI = os.environ.get("RATE_LIMIT_STORAGE_URI")
PAYPAL_ENV = os.environ.get("PAYPAL_ENV", "sandbox")
BASE_URL = ("https://api-m.paypal.com" if PAYPAL_ENV == "live" else "https://api-m.sandbox.paypal.com")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("paypal_app")
ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
TRUSTED_CERT_HOSTS = ("api.paypal.com", "api.sandbox.paypal.com")

class PayPalError(Exception):
    pass

_local = threading.local()

def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def get_conn():
    if not hasattr(_local, "conn"):
        _local.conn = _connect()
    conn = _local.conn
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def init_db():
    with get_conn() as conn:
        conn.executescript(""" CREATE TABLE IF NOT EXISTS carts ( 
                           cart_id TEXT PRIMARY KEY,
                           user_id TEXT NOT NULL,
                           amount TEXT NOT NULL,
                           currency TEXT NOT NULL );
                
                        CREATE TABLE IF NOT EXISTS orders (
                            paypal_order_id TEXT PRIMARY KEY,
                            cart_id TEXT NOT NULL,
                            user_id TEXT NOT NULL,
                            amount TEXT NOT NULL,
                            currency TEXT NOT NULL,
                            status TEXT NOT NULL DEFAULT 'CREATED',
                            paid INTEGER NOT NULL DEFAULT 0,
                            created_at REAL NOT NULL );
                
                        CREATE TABLE IF NOT EXISTS idempotency_cache (
                            idempotency_key TEXT PRIMARY KEY,
                            response TEXT NOT NULL,
                            created_at REAL NOT NULL);
                            
                        CREATE TABLE IF NOT EXISTS webhook_events (
                            event_id TEXT PRIMARY KEY,
                            created_at REAL NOT NULL);
                            
                        CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency_cache(created_at);
                        CREATE INDEX IF NOT EXISTS idx_webhook_created ON webhook_events(created_at); """)

def seed_demo_cart(cart_id, user_id, amount, currency):
    with get_conn() as conn:
        conn.execute( "INSERT OR IGNORE INTO carts (cart_id, user_id, amount, currency) VALUES (?, ?, ?, ?)", (cart_id, user_id, amount, currency),)

def get_cart(cart_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM carts WHERE cart_id = ?", (cart_id,)).fetchone()
        return dict(row) if row else None

def save_order(paypal_order_id, cart_id, user_id, amount, currency):
    with get_conn() as conn:
        conn.execute( "INSERT INTO orders (paypal_order_id, cart_id, user_id, amount, currency, created_at)  VALUES (?, ?, ?, ?, ?, ?)",(paypal_order_id, cart_id, user_id, amount, currency, time.time()),)

def get_order(paypal_order_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE paypal_order_id = ?", (paypal_order_id,)).fetchone()
        return dict(row) if row else None

def mark_order_paid(paypal_order_id):
    with get_conn() as conn:
        cur = conn.execute("UPDATE orders SET paid = 1, status = 'COMPLETED' WHERE paypal_order_id = ? AND paid = 0", (paypal_order_id,),)
        return cur.rowcount == 1

def get_idempotent_response(key):
    with get_conn() as conn:
        row = conn.execute("SELECT response FROM idempotency_cache WHERE idempotency_key = ?", (key,) ).fetchone()
        return json.loads(row["response"]) if row else None

def save_idempotent_response(key, response):
    with get_conn() as conn:
        conn.execute( "INSERT OR IGNORE INTO idempotency_cache (idempotency_key, response, created_at) VALUES (?, ?, ?)", (key, json.dumps(response), time.time()), )

def is_duplicate_webhook_event(event_id):
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM webhook_events WHERE event_id = ?", (event_id,)).fetchone()
        if row:
            return True
        try:
            conn.execute( "INSERT INTO webhook_events (event_id, created_at) VALUES (?, ?)", (event_id, time.time()), )
            return False
        except sqlite3.IntegrityError:
            return True

def prune_old_entries(max_age_seconds=24 * 60 * 60):
    cutoff = time.time() - max_age_seconds
    with get_conn() as conn:
        conn.execute("DELETE FROM idempotency_cache WHERE created_at < ?", (cutoff,))
        conn.execute("DELETE FROM webhook_events WHERE created_at < ?", (cutoff,))

_token_lock = threading.Lock()
_token_cache = {"access_token": None, "expires_at": 0}
_cert_cache = {}
_cert_lock = threading.Lock()
_CERT_TTL = 60 * 60

def get_access_token():
    with _token_lock:
        if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
            return _token_cache["access_token"]
        resp = requests.post(f"{BASE_URL}/v1/oauth2/token",
            headers={"Accept": "application/json"},
            data={"grant_type": "client_credentials"},
            auth=(CLIENT_ID, SECRET),
            timeout=10,)
        if resp.status_code != 200:
            raise PayPalError(f"Auth failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = time.time() + data["expires_in"] - 60
        return _token_cache["access_token"]

def paypal_headers():
    return {"Content-Type": "application/json", "Authorization": f"Bearer {get_access_token()}"}

def paypal_request(method, path, retry_on_auth_fail=True, **kwargs):
    url = f"{BASE_URL}{path}"
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.request(method, url, timeout=10, **kwargs)
        except requests.RequestException as e:
            last_exc = e
            if attempt == 2:
                raise PayPalError(f"Network error after retries: {e}") from e
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code == 401 and retry_on_auth_fail:
            with _token_lock:
                _token_cache["access_token"] = None
                _token_cache["expires_at"] = 0
            if "headers" in kwargs and "Authorization" in kwargs["headers"]:
                kwargs["headers"]["Authorization"] = f"Bearer {get_access_token()}"
            return paypal_request(method, path, retry_on_auth_fail=False, **kwargs)
        if resp.status_code >= 500 and attempt < 2:
            time.sleep(1.5 * (attempt + 1))
            continue
        return resp
    raise PayPalError(f"Request failed after retries: {last_exc}")

def _get_cert(cert_url):
    with _cert_lock:
        cached = _cert_cache.get(cert_url)
        if cached and time.time() < cached["expires_at"]:
            return cached["cert"]
    host = cert_url.split("/")[2] if "://" in cert_url else ""
    if host not in TRUSTED_CERT_HOSTS:
        raise PayPalError(f"Untrusted cert_url host: {host}")
    resp = requests.get(cert_url, timeout=10)
    if resp.status_code != 200:
        raise PayPalError(f"Could not fetch webhook cert: {resp.status_code}")
    cert = x509.load_pem_x509_certificate(resp.content)
    with _cert_lock:
        _cert_cache[cert_url] = {"cert": cert, "expires_at": time.time() + _CERT_TTL}
    return cert

def verify_webhook_signature_local(headers, raw_body: bytes) -> bool:
    transmission_id = headers.get("Paypal-Transmission-Id")
    transmission_time = headers.get("Paypal-Transmission-Time")
    cert_url = headers.get("Paypal-Cert-Url")
    signature_b64 = headers.get("Paypal-Transmission-Sig")
    if not all([transmission_id, transmission_time, cert_url, signature_b64]):
        return False
    crc = zlib.crc32(raw_body) & 0xFFFFFFFF
    message = f"{transmission_id}|{transmission_time}|{WEBHOOK_ID}|{crc}".encode()
    cert = _get_cert(cert_url)
    signature = base64.b64decode(signature_b64)
    try:
        cert.public_key().verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False

def verify_webhook_signature_remote(headers, event: dict) -> bool:
    payload = { "auth_algo": headers.get("Paypal-Auth-Algo"),
                "cert_url": headers.get("Paypal-Cert-Url"),
                "transmission_id": headers.get("Paypal-Transmission-Id"),
                "transmission_sig": headers.get("Paypal-Transmission-Sig"),
                "transmission_time": headers.get("Paypal-Transmission-Time"),
                "webhook_id": WEBHOOK_ID,
                "webhook_event": event, }
    resp = paypal_request( "POST", "/v1/notifications/verify-webhook-signature", headers=paypal_headers(), json=payload )
    if resp.status_code != 200:
        raise PayPalError(f"Verification call failed: {resp.status_code}")
    return resp.json().get("verification_status") == "SUCCESS"

def verify_webhook_signature(headers, raw_body: bytes, event: dict) -> bool:
    try:
        return verify_webhook_signature_local(headers, raw_body)
    except Exception as e:
        logger.warning("Local webhook verification failed, falling back to API: %s", e)
        return verify_webhook_signature_remote(headers, event)

def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper

def current_user_id():
    return session.get("user_id")

def _authorize_order_access(order_id):
    order = get_order(order_id)
    if not order:
        return None, (jsonify({"error": "order_not_found"}), 404)
    if order["user_id"] != current_user_id():
        return None, (jsonify({"error": "forbidden"}), 403)
    return order, None

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
limiter = Limiter(get_remote_address, app=app, storage_uri=RATE_LIMIT_STORAGE_URI, default_limits=[])
init_db()

@app.route("/api/auth/demo-login", methods=["POST"])
def demo_login():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    session["user_id"] = user_id
    return jsonify({"logged_in_as": user_id})

@app.route("/api/payment/create", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def create_payment():
    body = request.get_json(silent=True) or {}
    cart_id = body.get("cart_id")
    if not cart_id:
        return jsonify({"error": "cart_id required"}), 400
    cart = get_cart(cart_id)
    if not cart:
        return jsonify({"error": "cart_not_found"}), 404
    if cart["user_id"] != current_user_id():
        return jsonify({"error": "forbidden"}), 403
    amount, currency = cart["amount"], cart["currency"]
    try:
        Decimal(amount)
    except InvalidOperation:
        return jsonify({"error": "invalid_amount"}), 400
    if not ISO_CURRENCY_RE.match(currency):
        return jsonify({"error": "invalid_currency"}), 400
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key:
        cached = get_idempotent_response(idempotency_key)
        if cached:
            return jsonify(cached)
    payload = {"intent": "CAPTURE",
        "purchase_units": [{
            "amount": {"currency_code": currency, "value": amount},
            "custom_id": cart_id,}],
        "application_context": {
            "return_url": RETURN_URL,
            "cancel_url": CANCEL_URL,
            "user_action": "PAY_NOW",},}
    headers = paypal_headers()
    headers["PayPal-Request-Id"] = idempotency_key or str(uuid.uuid4())
    try:
        resp = paypal_request("POST", "/v2/checkout/orders", headers=headers, json=payload)
    except PayPalError as e:
        logger.error("Order creation failed: %s", e)
        return jsonify({"error": "order_creation_failed"}), 502
    if resp.status_code not in (200, 201):
        logger.error("PayPal order creation error: %s", resp.text)
        return jsonify({"error": "order_creation_failed"}), 502
    order = resp.json()
    approval_link = next((l["href"] for l in order["links"] if l["rel"] == "approve"), None)
    save_order(order["id"], cart_id, current_user_id(), amount, currency)
    result = {"order_id": order["id"], "approval_link": approval_link}
    if idempotency_key:
        save_idempotent_response(idempotency_key, result)
    logger.info("Order created: %s for user %s", order["id"], current_user_id())
    return jsonify(result)

@app.route("/api/payment/status/<order_id>", methods=["GET"])
@login_required
def payment_status(order_id):
    order, err = _authorize_order_access(order_id)
    if err:
        return err
    try:
        resp = paypal_request("GET", f"/v2/checkout/orders/{order_id}", headers=paypal_headers())
    except PayPalError as e:
        logger.error("Status check failed: %s", e)
        return jsonify({"error": "paypal_unavailable"}), 503
    if resp.status_code == 404:
        return jsonify({"error": "order_not_found"}), 404
    if resp.status_code != 200:
        logger.error("Status check error: %s", resp.text)
        return jsonify({"error": "status_check_failed"}), 502
    status = resp.json().get("status")
    return jsonify({"status": "Payment Done" if status == "COMPLETED" else status})

@app.route("/api/payment/capture/<order_id>", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def capture_payment(order_id):
    order, err = _authorize_order_access(order_id)
    if err:
        return err
    if order["paid"]:
        return jsonify({"status": "Payment Done"})
    try:
        status_resp = paypal_request("GET", f"/v2/checkout/orders/{order_id}", headers=paypal_headers())
        if status_resp.status_code == 200 and status_resp.json().get("status") == "COMPLETED":
            mark_order_paid(order_id)
            return jsonify({"status": "Payment Done"})
        resp = paypal_request("POST", f"/v2/checkout/orders/{order_id}/capture", headers=paypal_headers())
    except PayPalError as e:
        logger.error("Capture failed: %s", e)
        return jsonify({"error": "paypal_unavailable"}), 503
    if resp.status_code == 422 and "ALREADY_CAPTURED" in resp.text.upper():
        mark_order_paid(order_id)
        return jsonify({"status": "Payment Done"})
    if resp.status_code not in (200, 201):
        logger.error("Capture error: %s", resp.text)
        return jsonify({"error": "capture_failed"}), 502
    data = resp.json()
    if data.get("status") == "COMPLETED":
        mark_order_paid(order_id)
        logger.info("Order captured: %s", order_id)
        return jsonify({"status": "Payment Done"})
    return jsonify({"status": data.get("status")})

@app.route("/api/paypal/webhook", methods=["POST"])
def paypal_webhook():
    raw_body = request.get_data()
    event = request.get_json(silent=True)
    if event is None:
        return jsonify({"error": "invalid_json"}), 400
    event_id = event.get("id")
    if not event_id:
        return jsonify({"error": "missing_event_id"}), 400
    if is_duplicate_webhook_event(event_id):
        return jsonify({"received": True, "duplicate": True}), 200
    try:
        verified = verify_webhook_signature(request.headers, raw_body, event)
    except PayPalError as e:
        logger.error("Webhook verification unavailable: %s", e)
        return jsonify({"error": "verification_unavailable"}), 503
    if not verified:
        logger.warning("Webhook signature verification failed for event %s", event_id)
        return jsonify({"error": "invalid_signature"}), 400
    event_type = event.get("event_type")
    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        resource = event.get("resource", {})
        order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        if order_id:
            mark_order_paid(order_id)
            logger.info("Order marked paid via webhook: %s", order_id)
        else:
            logger.warning("Webhook %s missing order_id, could not mark paid", event_id)
    logger.info("Webhook processed: %s (%s)", event_id, event_type)
    return jsonify({"received": True}), 200

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    logger.exception("Unhandled error")
    return jsonify({"error": "internal_error"}), 500

if __name__ == "__main__":
    # Dev server only. In production run: gunicorn -w 4 -b 0.0.0.0:5000 paypal_payments:app
    app.run(port=5000, debug=False)