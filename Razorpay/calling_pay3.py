import requests
LOCAL_API_URL = "http://localhost:5000"

def run_payment_pipeline(plan_id: str = "basic_monthly", currency: str = "INR") -> dict:
    resp = requests.post( f"{LOCAL_API_URL}/api/payment/create", json={"plan_id": plan_id , "currency": currency} ,)
    if resp.status_code != 200:
        return {"success": False, "stage": "create", "error": resp.text}
    data = resp.json()
    order_id = data["order_id"]
    print(f"Order created: {order_id}")
    print(f"\nOpen this in a browser instead for the real flow: " f"{LOCAL_API_URL}/checkout?plan_id={plan_id}")
    print(f"Or, to test /verify directly without a browser, use Razorpay's " f"test-mode checkout with:")
    print(f"  key: {data['key_id']}")
    print(f"  order_id: {order_id}")
    print(f"  amount: {data['amount']}  currency: {data['currency']}\n")
    payment_id = input("Paste razorpay_payment_id after checkout completes: ").strip()
    signature = input("Paste razorpay_signature: ").strip()
    print("Verifying payment...")
    verify_resp = requests.post(f"{LOCAL_API_URL}/api/payment/verify",
        json={"razorpay_order_id": order_id , "razorpay_payment_id": payment_id , "razorpay_signature": signature ,},)
    if verify_resp.status_code != 200:
        return {"success": False, "stage": "verify", "error": verify_resp.text, "order_id": order_id}
    verify_data = verify_resp.json()
    if verify_data.get("status") == "Payment Done":
        print("Payment completed successfully.")
        return {"success": True, "order_id": order_id, "payment_id": payment_id, "status": "Payment Done"}
    return {"success": False, "stage": "verify", "status": verify_data.get("status"), "order_id": order_id}

if __name__ == "__main__":
    result = run_payment_pipeline(plan_id="basic_monthly")
    print(result)