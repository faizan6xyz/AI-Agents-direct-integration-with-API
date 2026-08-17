from datetime import datetime, timezone
import time
import upload as aaaa
import sqlite3

DB = "schedule.db"

def get_conn():
    return sqlite3.connect(DB)

def init_db():
    conn = get_conn()
    conn.execute(""" CREATE TABLE IF NOT EXISTS schedule (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    time TEXT NOT NULL,
                    container_id TEXT NOT NULL,
                    access_token TEXT NOT NULL) """)
    conn.commit()
    conn.close()

def insert_time(user_id, container_id, scheduled_time, access_token):
    conn = get_conn()
    conn.execute(
        "INSERT INTO schedule (user_id, container_id, time, access_token) VALUES (?, ?, ?, ?)",(user_id, container_id, scheduled_time.isoformat(), access_token))
    conn.commit()
    conn.close()

def get_containers_due(now):
    conn = get_conn()
    cur = conn.execute("SELECT id, container_id, access_token, user_id FROM schedule WHERE time < ?", (now,))
    rows = cur.fetchall()
    conn.close()
    return rows

def delete_by_id(row_id):
    conn = get_conn()
    conn.execute("DELETE FROM schedule WHERE id = ?", (row_id,))
    conn.commit()
    conn.close()

init_db()

while True:
    now = datetime.now(timezone.utc).isoformat()
    due = get_containers_due(now)

    for row_id, container_id, access_tok, user_id in due:
        aaaa.publish_container(user_id=user_id, access_token=access_tok, creation_id=container_id)
        delete_by_id(row_id)

    time.sleep(0.5)