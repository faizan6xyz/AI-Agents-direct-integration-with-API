
import os
import hmac
import hashlib
import logging
import time
from functools import wraps
from flask import Flask, request, jsonify
import razorpay
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("razorpay_payment")
RAZORPAY_KEY_ID = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
RAZORPAY_WEBHOOK_SECRET = os.environ["RAZORPAY_WEBHOOK_SECRET"]
RAZORPAY_CURRENCY = os.environ.get("RAZORPAY_CURRENCY", "INR")
client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
app = Flask(__name__)
orders_db = {}
processed_payment_ids = set()

def with_retry(max_attempts=3, base_delay=1.0, exceptions=(Exception,)):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        logger.error("%s failed after %d attempts: %s",fn.__name__, attempt, exc)
                        raise
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning("%s attempt %d/%d failed (%s), retrying in %.1fs",fn.__name__, attempt, max_attempts, exc, delay)
                    time.sleep(delay)
            raise last_exc  # unreachable, satisfies linters
        return wrapper
    return decorator

@with_retry(max_attempts=3, base_delay=1.0, exceptions=(razorpay.errors.ServerError,))
def create_razorpay_order(amount_rupees: float, receipt: str, notes: dict = None):
    amount_paise = int(round(amount_rupees * 100))
    order = client.order.create({"amount": amount_paise,
        "currency": RAZORPAY_CURRENCY,
        "receipt": receipt,
        "payment_capture": 1,  # auto-capture on successful payment
        "notes": notes or {},})
    return order

@app.route("/create-order", methods=["POST"])
def create_order_route():
    body = request.get_json(silent=True) or {}
    receipt = body.get("receipt")
    amount = body.get("amount")  # look this up from YOUR db/catalog in real code, don't trust an arbitrary client-supplied amount
    if not receipt or not amount:
        return jsonify({"error": "receipt and amount are required"}), 400
    try:
        order = create_razorpay_order(float(amount), receipt)
    except Exception as exc:
        logger.exception("Order creation failed for receipt=%s", receipt)
        return jsonify({"error": "could_not_create_order"}), 502
    orders_db[order["id"]] = {"receipt": receipt,"amount": amount,"status": "created",}
    return jsonify({"order_id": order["id"],"amount": order["amount"],"currency": order["currency"],"key_id": RAZORPAY_KEY_ID,})

def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    payload = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

@app.route("/verify-payment", methods=["POST"])
def verify_payment_route():
    body = request.get_json(silent=True) or {}
    order_id = body.get("razorpay_order_id")
    payment_id = body.get("razorpay_payment_id")
    signature = body.get("razorpay_signature")
    if not all([order_id, payment_id, signature]):
        return jsonify({"error": "missing_fields"}), 400
    if not verify_payment_signature(order_id, payment_id, signature):
        logger.warning("Signature mismatch for order=%s payment=%s", order_id, payment_id)
        return jsonify({"error": "invalid_signature"}), 400
    if payment_id in processed_payment_ids:
        return jsonify({"status": "already_processed"}), 200
    order = orders_db.get(order_id)
    if not order:
        logger.error("Verified payment for unknown order_id=%s", order_id)
        return jsonify({"error": "unknown_order"}), 404
    try:
        payment = fetch_payment_with_retry(payment_id)
        if payment["status"] != "captured":
            logger.warning("Payment %s not captured, status=%s", payment_id, payment["status"])
            return jsonify({"error": "payment_not_captured"}), 400
    except Exception:
        logger.exception("Could not confirm payment %s via API after signature check", payment_id)
        return jsonify({"error": "verification_unavailable"}), 502
    order["status"] = "paid"
    processed_payment_ids.add(payment_id)
    logger.info("Order %s marked paid via payment %s", order_id, payment_id)
    # TODO: trigger your fulfilment logic here (grant access, send confirmation, etc.)
    return jsonify({"status": "success"})

@with_retry(max_attempts=3, base_delay=1.0, exceptions=(razorpay.errors.ServerError,))
def fetch_payment_with_retry(payment_id: str):
    return client.payment.fetch(payment_id)

def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

@app.route("/webhook/razorpay", methods=["POST"])
def razorpay_webhook():
    raw_body = request.get_data()  # must read raw bytes BEFORE any JSON parsing
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not signature or not verify_webhook_signature(raw_body, signature):
        logger.warning("Rejected webhook: bad or missing signature")
        return jsonify({"error": "invalid_signature"}), 400
    event = request.get_json(silent=True) or {}
    event_type = event.get("event")
    logger.info("Received webhook event=%s", event_type)
    try:
        if event_type == "payment.captured":
            handle_payment_captured(event)
        elif event_type == "payment.failed":
            handle_payment_failed(event)
        elif event_type == "refund.processed":
            handle_refund_processed(event)
        else:
            logger.info("Unhandled event type=%s (ignored)", event_type)
    except Exception:
        logger.exception("Error handling webhook event=%s", event_type)
        return jsonify({"error": "internal_error"}), 500
    return jsonify({"status": "ok"}), 200

def handle_payment_captured(event):
    payment_entity = event["payload"]["payment"]["entity"]
    payment_id = payment_entity["id"]
    order_id = payment_entity["order_id"]
    if payment_id in processed_payment_ids:
        logger.info("Webhook: payment %s already processed, skipping", payment_id)
        return
    order = orders_db.get(order_id)
    if order:
        order["status"] = "paid"
    processed_payment_ids.add(payment_id)
    logger.info("Webhook confirmed capture for order=%s payment=%s", order_id, payment_id)
    # TODO: fulfilment logic (idempotent — safe to call even if /verify-payment
    # already ran this for the same payment_id)

def handle_payment_failed(event):
    payment_entity = event["payload"]["payment"]["entity"]
    order_id = payment_entity.get("order_id")
    error_reason = payment_entity.get("error_description", "unknown")
    logger.warning("Payment failed for order=%s reason=%s", order_id, error_reason)
    order = orders_db.get(order_id)
    if order:
        order["status"] = "failed"
    # TODO: notify user, offer retry, etc.

def handle_refund_processed(event):
    refund_entity = event["payload"]["refund"]["entity"]
    payment_id = refund_entity["payment_id"]
    logger.info("Refund processed for payment=%s", payment_id)
    # TODO: update order status to refunded


if __name__ == "__main__":
    app.run(port=5000, debug=False)