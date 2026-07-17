
import requests
PAYPAL_CLIENT_ID = "YOUR_CLIENT_ID"
PAYPAL_SECRET = "YOUR_SECRET"
PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"
ORDER_AMOUNT = "10.00"
ORDER_CURRENCY = "USD"
RETURN_URL = "https://example.com/payment-success"
CANCEL_URL = "https://example.com/payment-cancel"

def get_access_token():
    response = requests.post(f"{PAYPAL_BASE_URL}/v1/oauth2/token",
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
        data={"grant_type": "client_credentials"},
        auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),)
    response.raise_for_status()
    return response.json()["access_token"]

def check_order_status(order_id, access_token):
    response = requests.get(f"{PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}",
        headers={"Authorization": f"Bearer {access_token}"},)
    if response.status_code != 200:
        return None
    return response.json().get("status")

def create_payment_link(access_token):
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
                "amount": {
                    "currency_code": ORDER_CURRENCY,
                    "value": ORDER_AMOUNT,}}],
        "application_context": {
            "return_url": RETURN_URL,
            "cancel_url": CANCEL_URL,
            "user_action": "PAY_NOW",},}
    response = requests.post(f"{PAYPAL_BASE_URL}/v2/checkout/orders",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",},
        json=payload,)
    response.raise_for_status()
    order = response.json()
    approval_link = next((link["href"] for link in order["links"] if link["rel"] == "approve"),None,)
    return order["id"], approval_link

def check_or_request_payment(order_id=None):
    access_token = get_access_token()
    if order_id:
        status = check_order_status(order_id, access_token)
        if status == "COMPLETED":
            print("Payment Done")
            return
    new_order_id, link = create_payment_link(access_token)
    print(f"Payment not completed. New Order ID: {new_order_id}")
    print(f"Pay here: {link}")
    
if __name__ == "__main__":
    # Example usage:
    # 1) First run with no order_id -> get a payment link, client pays via that link
    # 2) Save the returned order_id, then re-run passing that ID to verify payment
    existing_order_id = None  # e.g. "5O190127TN364715T" once you have one
    check_or_request_payment(existing_order_id)
    
    
# How this works:

    # 1. get_access_token() — authenticates with PayPal using your Client ID/Secret.
    # 2. check_order_status(order_id) — checks an existing order's status (COMPLETED = paid).
    # 3. create_payment_link() — if not paid, creates a new PayPal order and returns the approval URL the client can click to pay.
    # 4. check_or_request_payment() — ties it together: pass an order_id you already have, and it either prints Payment Done or hands you a fresh payment link.