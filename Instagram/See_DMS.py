
import requests
GRAPH_API_VERSION = "v19.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
ACCESS_TOKEN = "YOUR_LONG_LIVED_ACCESS_TOKEN"
IG_BUSINESS_ID = "YOUR_IG_BUSINESS_ACCOUNT_ID"
PAGE_ID = "YOUR_FACEBOOK_PAGE_ID"

def get_recent_media(limit=10):
    url = f"{BASE_URL}/{IG_BUSINESS_ID}/media"
    params = {"fields": "id,caption,timestamp,permalink",
        "limit": limit,
        "access_token": ACCESS_TOKEN,}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json().get("data", [])

def get_comments_for_media(media_id):
    url = f"{BASE_URL}/{media_id}/comments"
    params = {"fields": "id,text,username,timestamp,like_count",
        "access_token": ACCESS_TOKEN,}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json().get("data", [])

def get_all_comments():
    media_items = get_recent_media()
    all_comments = {}
    for media in media_items:
        media_id = media["id"]
        comments = get_comments_for_media(media_id)
        all_comments[media_id] = {"caption": media.get("caption", ""),
            "permalink": media.get("permalink"),
            "comments": comments,}

    return all_comments

def get_conversations(limit=25):
    url = f"{BASE_URL}/{PAGE_ID}/conversations"
    params = {"platform": "instagram",
        "fields": "participants,updated_time",
        "limit": limit,
        "access_token": ACCESS_TOKEN,}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json().get("data", [])

def get_messages_in_conversation(conversation_id):
    url = f"{BASE_URL}/{conversation_id}"
    params = {"fields": "messages{message,from,to,created_time}",
        "access_token": ACCESS_TOKEN,}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()

if __name__ == "__main__":
    comments_by_post = get_all_comments()
    for media_id, data in comments_by_post.items():
        print(f"\nPost: {data['permalink']}")
        print(f"Caption: {data['caption'][:60]}...")
        for c in data["comments"]:
            print(f"  - {c['username']}: {c['text']}")

    conversations = get_conversations()
    for convo in conversations:
        print(f"\nConversation ID: {convo['id']}")
        thread = get_messages_in_conversation(convo["id"])
        for msg in thread.get("messages", {}).get("data", []):
            sender = msg.get("from", {}).get("username", "unknown")
            print(f"  {sender}: {msg.get('message')}")