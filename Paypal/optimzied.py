"""
Optimized PayPal Payment Integration (Flask backend)
-----------------
Production-oriented version with:
- Credentials from environment variables (never hardcoded)
- Cached OAuth token (avoids re-authenticating on every request)
- Full order lifecycle: create -> approve (client-side) -> capture
- Webhook endpoint with signature verification
- Basic retry/error handling

Requirements:
    pip install flask requests python-dotenv

Environment variables (.env or system env):
    PAYPAL_CLIENT_ID=xxx
    PAYPAL_SECRET=xxx
    PAYPAL_ENV=sandbox            # or "live"
    PAYPAL_WEBHOOK_ID=xxx         # from PayPal Dashboard > Webhooks
    RETURN_URL=https://yourapp.com/payment/success
    CANCEL_URL=https://yourapp.com/payment/cancel
"""
import os
import time
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

BASE_URL = (
    "https://api-m.paypal.com"
    if os.environ.get("PAYPAL_ENV", "sandbox") == "live"
    else "https://api-m.sandbox.paypal.com"
)

# ---- Simple in-memory token cache (swap for Redis in multi-worker setups) ----
_token_cache = {"access_token": None, "expires_at": 0}

class PayPalError(Exception):
    pass

def _request(method, path, **kwargs):
    """Wrapper around requests with basic retry on transient failures."""
    url = f"{BASE_URL}{path}"
    for attempt in range(3):
        try:
            resp = requests.request(method, url, timeout=10, **kwargs)
            if resp.status_code >= 500 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            return resp
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise PayPalError("Request failed after retries")

def get_access_token():
    """Return a cached OAuth token, refreshing only when expired."""
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    resp = _request(
        "POST",
        "/v1/oauth2/token",
        headers={"Accept": "application/json"},
        data={"grant_type": "client_credentials"},
        auth=(CLIENT_ID, SECRET),
    )
    if resp.status_code != 200:
        raise PayPalError(f"Auth failed: {resp.text}")

    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    # Refresh a bit early (60s buffer) instead of waiting for exact expiry
    _token_cache["expires_at"] = time.time() + data["expires_in"] - 60
    return _token_cache["access_token"]

def paypal_headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_access_token()}",
    }

#  ORDER CREATION 
@app.route("/api/payment/create", methods=["POST"])
def create_payment():
    """Create a PayPal order and return the approval link + order ID."""
    body = request.get_json(force=True)
    amount = str(body.get("amount", "10.00"))
    currency = body.get("currency", "USD")

    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{"amount": {"currency_code": currency, "value": amount}}],
        "application_context": {
            "return_url": RETURN_URL,
            "cancel_url": CANCEL_URL,
            "user_action": "PAY_NOW",
        },
    }

    resp = _request("POST", "/v2/checkout/orders", headers=paypal_headers(), json=payload)
    if resp.status_code not in (200, 201):
        return jsonify({"error": "order_creation_failed", "details": resp.text}), 502

    order = resp.json()
    approval_link = next((l["href"] for l in order["links"] if l["rel"] == "approve"), None)
    return jsonify({"order_id": order["id"], "approval_link": approval_link})

#  STATUS CHECK 
@app.route("/api/payment/status/<order_id>", methods=["GET"])
def payment_status(order_id):
    resp = _request("GET", f"/v2/checkout/orders/{order_id}", headers=paypal_headers())
    if resp.status_code != 200:
        return jsonify({"error": "order_not_found"}), 404

    status = resp.json().get("status")
    if status == "COMPLETED":
        return jsonify({"status": "Payment Done"})
    return jsonify({"status": status})

#  CAPTURE (finalize charge after client approval) 
@app.route("/api/payment/capture/<order_id>", methods=["POST"])
def capture_payment(order_id):
    resp = _request(
        "POST", f"/v2/checkout/orders/{order_id}/capture", headers=paypal_headers()
    )
    if resp.status_code not in (200, 201):
        return jsonify({"error": "capture_failed", "details": resp.text}), 502

    data = resp.json()
    if data.get("status") == "COMPLETED":
        # TODO: mark order as paid in your own database here
        return jsonify({"status": "Payment Done"})
    return jsonify({"status": data.get("status")})

#  WEBHOOK (recommended over polling) 
@app.route("/api/paypal/webhook", methods=["POST"])
def paypal_webhook():
    event_body = request.get_data()
    headers = request.headers
    verify_payload = {
        "auth_algo": headers.get("Paypal-Auth-Algo"),
        "cert_url": headers.get("Paypal-Cert-Url"),
        "transmission_id": headers.get("Paypal-Transmission-Id"),
        "transmission_sig": headers.get("Paypal-Transmission-Sig"),
        "transmission_time": headers.get("Paypal-Transmission-Time"),
        "webhook_id": WEBHOOK_ID,
        "webhook_event": request.get_json(force=True),
    }
    resp = _request(
        "POST",
        "/v1/notifications/verify-webhook-signature",
        headers=paypal_headers(),
        json=verify_payload,
    )
    if resp.status_code != 200 or resp.json().get("verification_status") != "SUCCESS":
        return jsonify({"error": "invalid_signature"}), 400

    event = request.get_json(force=True)
    event_type = event.get("event_type")

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        # TODO: update your database - mark the related order as paid
        pass
    return jsonify({"received": True}), 200


if __name__ == "__main__":
    app.run(port=5000, debug=False)