import os
import time
import requests
import pandas as pd
from datetime import datetime

ACCESS_TOKEN = "YOUR_INSTAGRAM_ACCESS_TOKEN"
MEDIA_IDS = "132444"  # The IDs of your Reels/Posts
CHECK_INTERVAL_SECONDS = 3600  # 1 hour
CSV_PATH = f"Data/{MEDIA_IDS}.xlsx"
previous_likes = {media_id: None for media_id in MEDIA_IDS}
def load_previous_state():
    if os.path.exists(CSV_PATH):
        existing = pd.read_csv(CSV_PATH)
        for media_id in MEDIA_IDS:
            post_rows = existing[existing["media_id"] == media_id]
            if not post_rows.empty:
                previous_likes[media_id] = int(post_rows.iloc[-1]["likes"])
def check_likes():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Checking likes... ({timestamp})")
    rows = []
    for media_id in MEDIA_IDS:
        url = f"https://graph.facebook.com/v20.0/{media_id}"
        params = {
            "fields": "like_count",
            "access_token": ACCESS_TOKEN
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
        except requests.RequestException as e:
            print(f"Request failed for {media_id}: {e}")
            continue
        if "like_count" in data:
            current_likes = data["like_count"]
            prev = previous_likes[media_id]
            gained = current_likes - prev if prev is not None else None

            print(f"Post {media_id} now has {current_likes} likes."
                  f"{f' (+{gained} since last check)' if gained is not None else ' (first check)'}")
            rows.append({
                "media_id": media_id,
                "timestamp": timestamp,
                "likes": current_likes,
                "gained": gained
            })
            previous_likes[media_id] = current_likes
        else:
            print(f"Error fetching data for {media_id}: {data}")

    if rows:
        df = pd.DataFrame(rows)
        save_to_csv(df)
def save_to_csv(df):
    file_exists = os.path.exists(CSV_PATH)
    df.to_csv(CSV_PATH, mode="a", header=not file_exists, index=False)
    print(f"Saved {len(df)} row(s) to {CSV_PATH}")
if __name__ == "__main__":
    load_previous_state()
    while True:
        check_likes()
        time.sleep(CHECK_INTERVAL_SECONDS)