import os
from typing import Any, Optional
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client

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

from typing import Any, Optional

def insert_rows(table_name: str, data: dict[str, Any] | list[dict[str, Any]]) -> list[dict]:
    response = supabase.table(table_name).insert(data).execute()
    return response.data

def update_rows(table_name: str, updates: dict[str, Any], filters: dict[str, Any]) -> list[dict]:
    query = supabase.table(table_name).update(updates)
    for column, value in filters.items():
        query = query.eq(column, value)
    response = query.execute()
    return response.data

def delete_rows(table_name: str, filters: dict[str, Any]) -> list[dict]:
    query = supabase.table(table_name).delete()
    for column, value in filters.items():
        query = query.eq(column, value)
    response = query.execute()
    return response.data

def select_rows( table_name: str, filters: Optional[dict[str, Any]] = None, select: str = "*", order_by: Optional[str] = None, ascending: bool = True, limit: Optional[int] = None,) -> list[dict]:
    query = supabase.table(table_name).select(select)
    if filters:
        for column, value in filters.items():
            query = query.eq(column, value)
    if order_by:
        query = query.order(order_by, desc=not ascending)
    if limit:
        query = query.limit(limit)
    response = query.execute()
    return response.data
 
if __name__ == "__main__":
    print("\nFetching all rows...")
    all_rows = select_rows("users")
    for row in all_rows:
        print(row)


# --- INSERT ---
# Add a single user
insert_rows("users", {"name": "Ayesha", "email": "ayesha@example.com", "role": "admin"})
# Bulk insert multiple rows at once (e.g. importing contacts)
insert_rows("contacts", [
    {"name": "Ravi", "phone": "9990001111"},
    {"name": "Meena", "phone": "9990002222"},
    {"name": "Karan", "phone": "9990003333"},
])
# Insert a new order tied to a user
insert_rows("orders", {"user_id": 12, "product": "Laptop", "amount": 54999, "status": "pending"})
# --- UPDATE ---
# Promote a user
update_rows("users", {"role": "senior"}, {"id": 5})
# Mark an order as shipped
update_rows("orders", {"status": "shipped"}, {"id": 101})
# Update all pending orders for a specific user (multiple filter columns)
update_rows("orders", {"status": "cancelled"}, {"user_id": 12, "status": "pending"})
# Deactivate a user by email instead of id
update_rows("users", {"is_active": False}, {"email": "ayesha@example.com"})
# --- DELETE ---
# Delete a single row by id
delete_rows("users", {"id": 5})
# Delete all orders belonging to a user
delete_rows("orders", {"user_id": 12})
# Delete rows matching multiple conditions (e.g. clean up old failed jobs)
delete_rows("jobs", {"status": "failed", "retry_count": 3})
# --- SELECT (with conditions) ---
# Get all admins
select_rows("users", filters={"role": "admin"})
# Get a user's orders, most recent first
select_rows("orders", filters={"user_id": 12}, order_by="created_at", ascending=False)
# Get top 5 highest-value orders overall
select_rows("orders", order_by="amount", ascending=False, limit=5)
# Fetch only specific columns instead of "*"
select_rows("users", filters={"role": "engineer"}, select="id,name,email")
# Combine multiple filters (AND logic) — active engineers only
select_rows("users", filters={"role": "engineer", "is_active": True})
# Get everything, no filters, capped at 50 rows
select_rows("logs", limit=50)
    