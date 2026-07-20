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

def create_row(data: dict[str, Any]) -> list[dict]:
    response = supabase.table(TABLE_NAME).insert(data).execute()
    return response.data
 
def create_rows(rows: list[dict[str, Any]]) -> list[dict]:
    response = supabase.table(TABLE_NAME).insert(rows).execute()
    return response.data
 
def get_all_rows(limit: int = 100) -> list[dict]:
    response = supabase.table(TABLE_NAME).select("*").limit(limit).execute()
    return response.data
 
def get_row_by_id(row_id: int) -> Optional[dict]:
    response = supabase.table(TABLE_NAME).select("*").eq("id", row_id).execute()
    return response.data[0] if response.data else None
 
def get_rows_by_column(column: str, value: Any) -> list[dict]:
    response = supabase.table(TABLE_NAME).select("*").eq(column, value).execute()
    return response.data
 
def search_rows(column: str, pattern: str) -> list[dict]:
    response = supabase.table(TABLE_NAME).select("*").ilike(column, f"%{pattern}%").execute()
    return response.data
 
def get_rows_paginated(page: int = 1, page_size: int = 20) -> list[dict]:
    start = (page - 1) * page_size
    end = start + page_size - 1
    response = supabase.table(TABLE_NAME).select("*").range(start, end).execute()
    return response.data
 
def update_row(row_id: int, updates: dict[str, Any]) -> list[dict]:
    response = supabase.table(TABLE_NAME).update(updates).eq("id", row_id).execute()
    return response.data

def upsert_row(data: dict[str, Any]) -> list[dict]:
    response = supabase.table(TABLE_NAME).upsert(data).execute()
    return response.data
 
def delete_row(row_id: int) -> list[dict]:
    response = supabase.table(TABLE_NAME).delete().eq("id", row_id).execute()
    return response.data
 
def delete_rows_by_column(column: str, value: Any) -> list[dict]:
    response = supabase.table(TABLE_NAME).delete().eq(column, value).execute()
    return response.data
 
def count_rows(column: Optional[str] = None, value: Any = None) -> int:
    query = supabase.table(TABLE_NAME).select("*", count="exact")
    if column is not None:
        query = query.eq(column, value)
    response = query.execute()
    return response.count
 
def row_exists(column: str, value: Any) -> bool:
    response = (
        supabase.table(TABLE_NAME)
        .select("id", count="exact")
        .eq(column, value)
        .limit(1)
        .execute()
    )
    return (response.count or 0) > 0
 
def get_rows_ordered(order_by: str, ascending: bool = True, limit: int = 100) -> list[dict]:
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .order(order_by, desc=not ascending)
        .limit(limit)
        .execute()
    )
    return response.data
 
def get_rows_multi_filter(filters: dict[str, Any], limit: int = 100) -> list[dict]:
    query = supabase.table(TABLE_NAME).select("*")
    for column, value in filters.items():
        query = query.eq(column, value)
    response = query.limit(limit).execute()
    return response.data
 
def get_rows_in_range(column: str, low: Any, high: Any) -> list[dict]:
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .gte(column, low)
        .lte(column, high)
        .execute()
    )
    return response.data
 
def increment_column(row_id: int, column: str, amount: int = 1) -> list[dict]:
    response = supabase.rpc(
        "increment", {"row_id": row_id, "column_name": column, "amount": amount}
    ).execute()
    return response.data
 
def call_rpc(function_name: str, params: dict[str, Any]) -> Any:
    response = supabase.rpc(function_name, params).execute()
    return response.data
 
def full_text_search(column: str, query_text: str) -> list[dict]:
    response = (
        supabase.table(TABLE_NAME)
        .select("*")
        .text_search(column, query_text)
        .execute()
    )
    return response.data
 
def get_related_rows(local_column: str, foreign_table: str, select: str = "*") -> list[dict]:
    response = supabase.table(TABLE_NAME).select(select).execute()
    return response.data
 
def batch_upsert(rows: list[dict[str, Any]], on_conflict: str = "id") -> list[dict]:
    response = supabase.table(TABLE_NAME).upsert(rows, on_conflict=on_conflict).execute()
    return response.data
 
def subscribe_to_changes(callback) -> Any:
    channel = (
        supabase.channel(f"realtime:{TABLE_NAME}")
        .on_postgres_changes(
            event="*", schema="public", table=TABLE_NAME, callback=callback
        )
        .subscribe()
    )
    return channel
 
if __name__ == "__main__":
    print("\nFetching all rows...")
    all_rows = get_all_rows()
    for row in all_rows:
        print(row)

    