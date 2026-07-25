import os
import time
import json
import hmac
import hashlib
from datetime import datetime, timezone
import logging
import functools
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests
from supabase import create_client, Client
import database.UserDB as dbimp
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("payment")
app = Flask(__name__)

def _now():
    return datetime.now(timezone.utc)

def _require(key):
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val

SUPABASE_URL = _require("SUPABASE_URL")
SUPABASE_KEY = _require("SUPABASE_KEY")
mail = _require("email")
passw = _require("pass")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
try:
    res = supabase.auth.sign_in_with_password({"email": mail, "password": passw})
except Exception:
    res = supabase.auth.sign_up({"email": mail, "password": passw})
KEY_ID = _require("RAZORPAY_KEY_ID")
KEY_SECRET = _require("RAZORPAY_KEY_SECRET")
WEBHOOK_SECRET = _require("RAZORPAY_WEBHOOK_SECRET")
RATE_LIMIT_STORAGE_URI = _require("RATE_LIMIT_STORAGE_URI")
INTERNAL_API_KEY = _require("INTERNAL_API_KEY")
Plan = _require("RAZORPAY_Plan")
app.secret_key = _require("FLASK_SECRET_KEY")
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=[], storage_uri=RATE_LIMIT_STORAGE_URI)
BASE_URL = "https://api.razorpay.com/v1"
AUTH = (KEY_ID, KEY_SECRET)
TABLE_NAME = "Razorpay"
TABLE_NAME_verify = "Razorpay_verify"

class RazorpayError(Exception):
    pass

@app.route("/api/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    body = request.get_json(silent=True) or {}
    email = body.get("email")
    password = body.get("password")
    if not email or not password:
        return jsonify({"error": "missing_credentials"}), 400
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
    except Exception:
        logger.warning("login_failed for email=%s", email)
        return jsonify({"error": "invalid_credentials"}), 401
    if not res or not res.session or not res.user:
        return jsonify({"error": "invalid_credentials"}), 401
    return jsonify({ "access_token": res.session.access_token, "refresh_token": res.session.refresh_token, "user_id": res.user.id, })

@app.route("/api/logout", methods=["POST"])
def logout():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            supabase.auth.admin.sign_out(token)
        except Exception:
            pass
    return jsonify({"ok": True})

def require_user(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "missing_token"}), 401
        token = auth_header.split(" ", 1)[1]
        try:
            user_resp = supabase.auth.get_user(token)
        except Exception:
            return jsonify({"error": "invalid_token"}), 401
        if not user_resp or not user_resp.user:
            return jsonify({"error": "invalid_token"}), 401
        request.user = user_resp.user
        return f(*args, **kwargs)
    return wrapper

def _require_internal_api_key():
    provided = request.headers.get("X-Internal-Api-Key", "")
    return hmac.compare_digest(provided, INTERNAL_API_KEY)

def _release_idempotency_claim(idempotency_key: str):
    if not idempotency_key:
        return
    dbimp.delete_rows( TABLE_NAME_verify,{"Idempotency_key_creation": idempotency_key, "Response_json_creation": ""},)

def _request(method, path, idempotent=True, **kwargs):
    url = f"{BASE_URL}{path}"
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.request(method, url, auth=AUTH, timeout=10, **kwargs)
        except requests.RequestException as e:
            last_exc = e
            if not idempotent or attempt == 2:
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
    plan_id = request.args.get("plan_id", "basic_monthly")
    if plan_id not in Plan:
        return jsonify({"error": "invalid_plan_id"}), 400
    return render_template("checkout.html", plan_id=plan_id, key_id=KEY_ID)

@app.route("/api/payment/create", methods=["POST"])
@limiter.limit("20 per minute")
@require_user
def create_payment():
    if not _require_internal_api_key():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    plan_id = body.get("plan_id")
    if not plan_id or plan_id not in Plan:
        return jsonify({"error": "invalid_plan_id"}), 400
    amount_paise = Plan[plan_id]
    currency = body.get("currency", "INR")
    if currency not in Plan["Currency"]:
        return jsonify({"error": "unsupported_currency"}), 400
    receipt = body.get("receipt") or f"rcpt_{int(time.time() * 1000)}"
    idempotency_key = request.headers.get("Idempotency-Key") or body.get("idempotency_key")
    if idempotency_key:
        row = dbimp.select_rows( TABLE_NAME_verify, select={"Response_json_creation"}, filters={"Idempotency_key_creation": idempotency_key}, )
        if row:
            if row[0] is None or row[0] == "":
                return jsonify({"error": "request_in_progress"}), 409
            return jsonify(json.loads(row[0]))
        try:
            dbimp.insert_rows(TABLE_NAME_verify, {"Idempotency_key_creation": idempotency_key, "Response_json_creation": "", "Created_at": _now(), },)
        except Exception:
            return jsonify({"error": "request_in_progress"}), 409
    payload = {"amount": amount_paise, "currency": currency, "receipt": receipt, "payment_capture": 1}
    try:
        resp = _request("POST", "/orders", idempotent=False, json=payload)
    except RazorpayError as e:
        logger.error("order_creation_failed (network): %s", e)
        _release_idempotency_claim(idempotency_key)
        return jsonify({"error": "order_creation_failed", "details": str(e)}), 502
    if resp.status_code not in (200, 201):
        logger.error("order_creation_failed (razorpay %s): %s", resp.status_code, resp.text)
        _release_idempotency_claim(idempotency_key)
        return jsonify({"error": "order_creation_failed", "details": resp.text}), 502
    order = resp.json()
    result = {"order_id": order["id"],"amount": order["amount"],"currency": order["currency"], "key_id": KEY_ID,}
    row = dbimp.select_rows(TABLE_NAME, select={"Order_id"}, filters={"Order_id": order["id"]})
    if not row:
        dbimp.insert_rows( TABLE_NAME, {"Order_id": order["id"], "Plan_id": plan_id,"Status": "created", "Updates_at": _now(),},)
    if idempotency_key:
        dbimp.update_rows(TABLE_NAME_verify,{"Response_json_creation": json.dumps(result), "Created_at": _now()},{"Idempotency_key_creation": idempotency_key},)
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
    row = dbimp.select_rows(TABLE_NAME_verify, select={"Response_json_verify"}, filters={"Payment_id_verify": payment_id})
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
        dbimp.insert_rows(TABLE_NAME_verify, {"Payment_id_verify": payment_id, "Response_json_verify": json.dumps(result)})
    return jsonify(result)

@app.route("/api/payment/status/<payment_id>", methods=["GET"])
@limiter.limit("30 per minute")
@require_user
def payment_status(payment_id):
    if not _require_internal_api_key():
        return jsonify({"error": "unauthorized"}), 401
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
@limiter.limit("10 per minute")
@require_user
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
            logger.warning("capture_payment received client-supplied amount for payment_id=%s; ignoring it", payment_id)
        resp = _request("POST", f"/payments/{payment_id}/capture", idempotent=False, json={"amount": amount_paise, "currency": currency})
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
    dbimp.update_rows(TABLE_NAME, {"Status": status, "Updates_at": _now()}, {"Order_id": order_id})

def _handle_payment_captured(event: dict):
    payment_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id")
    order_id = payment_entity.get("order_id")
    logger.info("payment.captured received for payment_id=%s order_id=%s", payment_id, order_id)
    _set_order_status(order_id, "captured")

def _handle_payment_failed(event: dict):
    payment_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id")
    order_id = payment_entity.get("order_id")
    error_desc = payment_entity.get("error_description")
    logger.warning("payment.failed for payment_id=%s order_id=%s: %s", payment_id, order_id, error_desc)
    _set_order_status(order_id, "failed")

def _handle_order_paid(event: dict):
    order_entity = event.get("payload", {}).get("order", {}).get("entity", {})
    order_id = order_entity.get("id")
    logger.info("order.paid received for order_id=%s", order_id)
    _set_order_status(order_id, "paid")

_WEBHOOK_HANDLERS = {"payment.captured": _handle_payment_captured,"payment.failed": _handle_payment_failed,"order.paid": _handle_order_paid,}

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
    existing = dbimp.select_rows(TABLE_NAME_verify, select={"Status_webhook"}, filters={"Event_id_webhook": event_id})
    if existing:
        prior_status = existing[0]
        if prior_status == "done":
            return jsonify({"received": True, "duplicate": True}), 200
        if prior_status == "processing":
            return jsonify({"error": "processing_in_progress"}), 409
    try:
        dbimp.insert_rows(TABLE_NAME_verify, {"Event_id_webhook": event_id, "Status_webhook": "processing"})
    except Exception:
        return jsonify({"error": "processing_in_progress"}), 409
    try:
        handler = _WEBHOOK_HANDLERS.get(event_type)
        if handler:
            handler(event)
        else:
            logger.info("Unhandled webhook event_id=%s", event_id)
    except Exception as e:
        logger.error("processing_failed for event_id=%s: %s", event_id, e)
        dbimp.update_rows(TABLE_NAME_verify, {"Status_webhook": "failed"}, {"Event_id_webhook": event_id})
        return jsonify({"error": "processing_failed", "details": str(e)}), 500
    dbimp.update_rows(TABLE_NAME_verify, {"Status_webhook": "done"}, {"Event_id_webhook": event_id})
    return jsonify({"received": True}), 200

@app.route("/healthz")
def healthz():
    try:
        supabase.table("users").select("id").limit(1).execute()
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("healthz_failed: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 503

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    logger.exception("Unhandled exception")
    return jsonify({"error": "internal_error", "details": str(e)}), 500

if __name__ == "__main__":
    # Local dev only. In production run:
    #   gunicorn -w 4 -b 0.0.0.0:5000 app:app
    app.run(port=5000, debug=False)