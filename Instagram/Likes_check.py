import os
import time
import requests
import pandas as pd
from datetime import datetime
ACCESS_TOKEN = "YOUR_INSTAGRAM_ACCESS_TOKEN"
IG_USER_ID = "YOUR_INSTAGRAM_BUSINESS_ACCOUNT_ID"  # <-- was missing, required by get_all_reel_ids()
CHECK_INTERVAL_SECONDS = 5400  # 1.5 hours
EXCEL_PATH = "Data/Instagram_Engagement.xlsx"
previous_likes = {}

def get_all_reels():
    url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    params = {
        "fields": "id,caption,media_product_type",
        "access_token": ACCESS_TOKEN
    }
    response = requests.get(url, params=params).json()
    reels = [
        {"id": item["id"], "caption": item.get("caption", "")}
        for item in response.get("data", [])
        if item.get("media_product_type") == "REELS"
    ]
    return reels

def get_all_posts():
    url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    params = {
        "fields": "id,caption,media_product_type,media_type",
        "access_token": ACCESS_TOKEN
    }
    response = requests.get(url, params=params).json()
    posts = [
        {"id": item["id"], "caption": item.get("caption", "")}
        for item in response.get("data", [])
        if item.get("media_product_type") != "REELS" and item.get("media_type") in ("IMAGE", "CAROUSEL_ALBUM")
    ]
    return posts


def load_previous_state(media_items):
    if os.path.exists(EXCEL_PATH):
        existing = pd.read_excel(EXCEL_PATH)
        for item in media_items:
            post_rows = existing[existing["media_id"] == item["id"]]
            if not post_rows.empty:
                previous_likes[item["id"]] = int(post_rows.iloc[-1]["likes"])


def check_likes(media_items, media_type_label):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Checking {media_type_label} likes... ({timestamp})")
    rows = []
    for item in media_items:
        media_id = item["id"]
        caption = item.get("caption", "")

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
            prev = previous_likes.get(media_id)
            gained = current_likes - prev if prev is not None else None
            print(f"{media_type_label.capitalize()} {media_id} now has {current_likes} likes."
                  f"{f' (+{gained} since last check)' if gained is not None else ' (first check)'}")
            rows.append({
                "media_id": media_id,
                "type": media_type_label,
                "caption": caption,
                "timestamp": timestamp,
                "likes": current_likes,
                "gained": gained
            })
            previous_likes[media_id] = current_likes
        else:
            print(f"Error fetching data for {media_id}: {data}")
    if rows:
        save_to_excel(pd.DataFrame(rows))

def save_to_excel(new_df):
    os.makedirs(os.path.dirname(EXCEL_PATH), exist_ok=True)
    if os.path.exists(EXCEL_PATH):
        existing_df = pd.read_excel(EXCEL_PATH)
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined_df = new_df
    combined_df.to_excel(EXCEL_PATH, index=False)
    print(f"Saved {len(new_df)} new row(s) to {EXCEL_PATH} (total: {len(combined_df)})")


def runit():
    global IG_USER_ID 
    IG_USER_ID = input("Enter the Username For the Analysis : ")
    reels = get_all_reels()
    posts = get_all_posts()
    if not reels and not posts:
        print("No Reels or Posts found for this account.")
        return
    load_previous_state(reels + posts)
    while True:
        if reels:
            check_likes(reels, "reel")
        if posts:
            check_likes(posts, "post")
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    runit()