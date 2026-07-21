import os
from typing import Any, Optional
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client
from Paypal.optimzied import run_payment_pipeline

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
mail = os.environ.get("email")
passw = os.environ.get("pass")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Set SUPABASE_URL and SUPABASE_KEY in your environment or .env file")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TABLE_NAME = "users"
try:
    res = supabase.auth.sign_in_with_password({"email": mail, "password": passw})
except Exception:
    res = supabase.auth.sign_up({"email": mail, "password": passw})

def get_all_rows(limit: int = 100) -> list[dict]:
    response = supabase.table(TABLE_NAME).select("*").limit(limit).execute()
    return response.data

all_rows = get_all_rows()
for row in all_rows:
        print(row)
        payment_status = row["Payment_check"]
        print(payment_status)

if payment_status == False :
    print("Payment Not made ")
    method = input("Paypal or UPI : ")

    if method.lower() == "payapl" :
        result = run_payment_pipeline(amount="20.00")
        print(result)   