import time
import threading
import requests
import paypal_payments as pp
LOCAL_API_URL = "http://localhost:5000"
DEMO_CART_ID = "demo-cart-1" 
DEMO_USER_ID = "demo-user-1" # it wuld be fetches by the db 
DEMO_AMOUNT = "20.00"
DEMO_CURRENCY = "USD"

def _start_server_in_background():
    thread = threading.Thread( target=lambda: pp.app.run(port=5000, debug=False, use_reloader=False), daemon=True )
    thread.start()
    time.sleep(1.5)

def seed_demo_cart_via_api(cart_id: str, user_id: str, amount: str, currency: str) -> dict:
    resp = requests.post(f"{LOCAL_API_URL}/api/demo/seed-cart", 
                         json={"cart_id": cart_id, "user_id": user_id, "amount": amount, "currency": currency}, )
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to seed demo cart: {resp.status_code} {resp.text}")
    return resp.json()

def run_payment_pipeline(cart_id: str = DEMO_CART_ID, user_id: str = DEMO_USER_ID) -> dict:
    session = requests.Session()
    session.post(f"{LOCAL_API_URL}/api/auth/demo-login", json={"user_id": user_id})
    create_resp = session.post( f"{LOCAL_API_URL}/api/payment/create",
                                json={"cart_id": cart_id},
                                headers={"Idempotency-Key": f"pipeline-{cart_id}"}, )
    if create_resp.status_code != 200:
        return {"success": False, "stage": "create", "error": create_resp.text}
    data = create_resp.json()
    order_id = data["order_id"]
    approval_link = data["approval_link"]
    print(f"Order created: {order_id}")
    print(f"\nGo approve the payment here:\n{approval_link}\n")
    input("Press Enter once you've approved the payment on PayPal...")
    print("Checking order status...")
    status_resp = session.get(f"{LOCAL_API_URL}/api/payment/status/{order_id}")
    if status_resp.status_code != 200:
        return {"success": False, "stage": "status_check", "error": status_resp.text}
    status = status_resp.json().get("status")
    print(f"Status: {status}")
    print("Capturing payment...")
    capture_resp = session.post(f"{LOCAL_API_URL}/api/payment/capture/{order_id}")
    if capture_resp.status_code != 200:
        return {"success": False, "stage": "capture", "error": capture_resp.text, "order_id": order_id}
    capture_data = capture_resp.json()
    if capture_data.get("status") == "Payment Done":
        print("Payment completed successfully.")
        return {"success": True, "order_id": order_id, "status": "Payment Done"}
    return {"success": False, "stage": "capture", "status": capture_data.get("status"), "order_id": order_id}

if __name__ == "__main__":
    _start_server_in_background()
    seed_demo_cart_via_api(DEMO_CART_ID, DEMO_USER_ID, DEMO_AMOUNT, DEMO_CURRENCY)
    result = run_payment_pipeline()
    print(result)