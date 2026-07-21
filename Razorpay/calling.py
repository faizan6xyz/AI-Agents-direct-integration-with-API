import os
import time
import logging
import sqlite3
import requests
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig( level=logging.INFO , format="%(asctime)s %(levelname)s %(name)s: %(message)s", )
logger = logging.getLogger("reconcile")
KEY_ID = os.environ["RAZORPAY_KEY_ID"]
KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
BASE_URL = "https://api.razorpay.com/v1"
AUTH = (KEY_ID, KEY_SECRET)
DB_PATH = os.environ.get("PAYMENT_DB_PATH", "payments.db")
STUCK_THRESHOLD_SECONDS = int(os.environ.get("RECONCILE_STUCK_THRESHOLD_SECONDS", 30 * 60))

def _get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn

def _fetch_order_payments(order_id: str):
    resp = requests.get(f"{BASE_URL}/orders/{order_id}/payments", auth=AUTH, timeout=10)
    resp.raise_for_status()
    return resp.json().get("items", [])

def reconcile_stuck_orders():
    cutoff = time.time() - STUCK_THRESHOLD_SECONDS
    with _get_db() as conn:
        stuck = conn.execute( """SELECT order_id, status, created_at FROM orders WHERE status IN 
                             ('created', 'authorized') AND created_at < ?""",
                             (cutoff,),).fetchall()
    if not stuck:
        logger.info("No stuck orders found.")
        return
    for order_id, status, created_at in stuck:
        age_minutes = (time.time() - created_at) / 60
        try:
            payments = _fetch_order_payments(order_id)
        except requests.RequestException as e:
            logger.error("Failed to fetch payments for order_id=%s: %s", order_id, e)
            continue
        captured = [p for p in payments if p.get("status") == "captured"]
        failed_only = payments and all(p.get("status") == "failed" for p in payments)
        if captured:
            new_status = "captured"
        elif failed_only:
            new_status = "failed"
        elif not payments:
            logger.warning( "Order %s has no payment attempts after %.0f min (age past threshold).", order_id, age_minutes, )
            continue
        else:
            logger.warning( "Order %s still unresolved after %.0f min (statuses: %s) — " "webhook likely missed, needs manual look.", 
                           order_id, age_minutes, [p.get("status") for p in payments], )
            continue
        with _get_db() as conn:
            conn.execute("UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?", 
                         (new_status, time.time(), order_id),)
            conn.commit()
        logger.info("Reconciled order_id=%s: %s -> %s (webhook must have been missed)", 
                    order_id, status, new_status,)

if __name__ == "__main__":
    reconcile_stuck_orders()