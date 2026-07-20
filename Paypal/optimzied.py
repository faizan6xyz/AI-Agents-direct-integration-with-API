import os
import time
import uuid
import threading
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
load_dotenv()
app = Flask(__name__)
CLIENT_ID = os.environ["PAYPAL_CLIENT_ID"]
SECRET = os.environ["PAYPAL_SECRET"]
WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID")
RETURN_URL = os.environ.get("RETURN_URL", "https://example.com/success")
CANCEL_URL = os.environ.get("CANCEL_URL", "https://example.com/cancel")
BASE_URL = ("https://api-m.paypal.com"
    if os.environ.get("PAYPAL_ENV", "sandbox") == "live"
    else "https://api-m.sandbox.paypal.com")
_token_lock = threading.Lock()
_token_cache = {"access_token": None, "expires_at": 0}
_processed_webhook_events = {}          # event_id -> result, with timestamp for pruning
_order_creation_cache = {}              # client_idempotency_key -> order response
_STORE_LOCK = threading.Lock()
_STORE_TTL_SECONDS = 24 * 60 * 60        # prune entries older than 24h

class PayPalError(Exception):
    pass

def _prune_store(store: dict):
    cutoff = time.time() - _STORE_TTL_SECONDS
    expired = [k for k, v in store.items() if v.get("_ts", 0) < cutoff]
    for k in expired:
        store.pop(k, None)

def _request(method, path, retry_on_auth_fail=True, **kwargs):
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
            return _request(method, path, retry_on_auth_fail=False, **kwargs)
        if resp.status_code >= 500 and attempt < 2:
            time.sleep(1.5 * (attempt + 1))
            continue
        return resp
    raise PayPalError(f"Request failed after retries: {last_exc}")


def get_access_token():
    with _token_lock:
        if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
            return _token_cache["access_token"]
        resp = requests.post(
            f"{BASE_URL}/v1/oauth2/token",
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
    return {"Content-Type": "application/json","Authorization": f"Bearer {get_access_token()}",}

@app.route("/api/payment/create", methods=["POST"])
def create_payment():
    body = request.get_json(silent=True) or {}
    amount = str(body.get("amount", "20.00"))
    currency = body.get("currency", "USD")
    idempotency_key = request.headers.get("Idempotency-Key") or body.get("idempotency_key")
    with _STORE_LOCK:
        _prune_store(_order_creation_cache)
        if idempotency_key and idempotency_key in _order_creation_cache:
            return jsonify(_order_creation_cache[idempotency_key]["response"])
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {"currency_code": currency, "value": amount}}],
        "application_context": {
            "return_url": RETURN_URL,
            "cancel_url": CANCEL_URL,
            "user_action": "PAY_NOW",},}
    headers = paypal_headers()
    headers["PayPal-Request-Id"] = idempotency_key or str(uuid.uuid4())
    try:
        resp = _request("POST", "/v2/checkout/orders", headers=headers, json=payload)
    except PayPalError as e:
        return jsonify({"error": "order_creation_failed", "details": str(e)}), 502
    if resp.status_code not in (200, 201):
        return jsonify({"error": "order_creation_failed", "details": resp.text}), 502
    order = resp.json()
    approval_link = next((l["href"] for l in order["links"] if l["rel"] == "approve"), None)
    result = {"order_id": order["id"], "approval_link": approval_link}
    if idempotency_key:
        with _STORE_LOCK:
            _order_creation_cache[idempotency_key] = {"response": result, "_ts": time.time()}
    return jsonify(result)


@app.route("/api/payment/status/<order_id>", methods=["GET"])
def payment_status(order_id):
    try:
        resp = _request("GET", f"/v2/checkout/orders/{order_id}", headers=paypal_headers())
    except PayPalError as e:
        return jsonify({"error": "paypal_unavailable", "details": str(e)}), 503
    if resp.status_code == 404:
        return jsonify({"error": "order_not_found"}), 404
    if resp.status_code != 200:
        return jsonify({"error": "status_check_failed", "details": resp.text}), 502
    status = resp.json().get("status")
    if status == "COMPLETED":
        return jsonify({"status": "Payment Done"})
    return jsonify({"status": status})

@app.route("/api/payment/capture/<order_id>", methods=["POST"])
def capture_payment(order_id):
    try:
        status_resp = _request("GET", f"/v2/checkout/orders/{order_id}", headers=paypal_headers())
        if status_resp.status_code == 200 and status_resp.json().get("status") == "COMPLETED":
            return jsonify({"status": "Payment Done"})
        resp = _request("POST",
            f"/v2/checkout/orders/{order_id}/capture",
            headers=paypal_headers(),)
    except PayPalError as e:
        return jsonify({"error": "paypal_unavailable", "details": str(e)}), 503
    if resp.status_code == 422 and "ALREADY_CAPTURED" in resp.text.upper():
        return jsonify({"status": "Payment Done"})
    if resp.status_code not in (200, 201):
        return jsonify({"error": "capture_failed", "details": resp.text}), 502
    data = resp.json()
    if data.get("status") == "COMPLETED":
        # TODO: mark order as paid in your own database here.
        return jsonify({"status": "Payment Done"})
    return jsonify({"status": data.get("status")})

@app.route("/api/paypal/webhook", methods=["POST"])
def paypal_webhook():
    headers = request.headers
    event = request.get_json(silent=True)
    if event is None:
        return jsonify({"error": "invalid_json"}), 400
    event_id = event.get("id")
    if not event_id:
        return jsonify({"error": "missing_event_id"}), 400
    with _STORE_LOCK:
        _prune_store(_processed_webhook_events)
        if event_id in _processed_webhook_events:
            return jsonify({"received": True, "duplicate": True}), 200
    verify_payload = {"auth_algo": headers.get("Paypal-Auth-Algo"),
        "cert_url": headers.get("Paypal-Cert-Url"),
        "transmission_id": headers.get("Paypal-Transmission-Id"),
        "transmission_sig": headers.get("Paypal-Transmission-Sig"),
        "transmission_time": headers.get("Paypal-Transmission-Time"),
        "webhook_id": WEBHOOK_ID,
        "webhook_event": event,}
    try:
        resp = _request("POST",
            "/v1/notifications/verify-webhook-signature",
            headers=paypal_headers(),
            json=verify_payload,)
    except PayPalError as e:
        return jsonify({"error": "verification_unavailable", "details": str(e)}), 503
    if resp.status_code != 200 or resp.json().get("verification_status") != "SUCCESS":
        return jsonify({"error": "invalid_signature"}), 400
    event_type = event.get("event_type")
    try:
        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            # TODO: update your database — mark the related order as paid.
            pass
    except Exception as e:
        return jsonify({"error": "processing_failed", "details": str(e)}), 500
    with _STORE_LOCK:
        _processed_webhook_events[event_id] = {"_ts": time.time()}
    return jsonify({"received": True}), 200

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    return jsonify({"error": "internal_error", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(port=5000, debug=False)