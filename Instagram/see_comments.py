
import os
import requests

ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "YOUR_LONG_LIVED_TOKEN")
IG_USER_ID = os.environ.get("IG_USER_ID", "YOUR_IG_USER_ID")
GRAPH_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"


def _get(endpoint: str, params: dict) -> dict:
    resp = requests.get(f"{BASE_URL}/{endpoint}", params=params)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Instagram API error: {data['error']}")
    return data

def _post(endpoint: str, params: dict) -> dict:
    resp = requests.post(f"{BASE_URL}/{endpoint}", data=params)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Instagram API error: {data['error']}")
    return data

def get_recent_media(limit: int = 25) -> list[dict]:
    data = _get(f"{IG_USER_ID}/media", {
        "fields": "id,caption,media_type,timestamp,permalink",
        "limit": limit,
        "access_token": ACCESS_TOKEN,
    })
    return data.get("data", [])


def get_comments(media_id: str) -> list[dict]:
    data = _get(f"{media_id}/comments", {
        "fields": "id,text,username,timestamp,like_count",
        "access_token": ACCESS_TOKEN,
    })
    return data.get("data", [])

def get_comment_replies(comment_id: str) -> list[dict]:
    """Get replies to a specific comment."""
    data = _get(f"{comment_id}/replies", {
        "fields": "id,text,username,timestamp",
        "access_token": ACCESS_TOKEN,
    })
    return data.get("data", [])

def reply_to_comment(comment_id: str, message: str) -> str:
    result = _post(f"{comment_id}/replies", {
        "message": message,
        "access_token": ACCESS_TOKEN,
    })
    return result["id"]

def hide_comment(comment_id: str, hide: bool = True) -> bool:
    result = _post(comment_id, {
        "hide": "true" if hide else "false",
        "access_token": ACCESS_TOKEN,
    })
    return result.get("success", False)

def delete_comment(comment_id: str) -> bool:
    resp = requests.delete(f"{BASE_URL}/{comment_id}", params={"access_token": ACCESS_TOKEN})
    return resp.json().get("success", False)


def get_conversations(limit: int = 20) -> list[dict]:
    data = _get(f"{IG_USER_ID}/conversations", {
        "platform": "instagram",
        "fields": "id,updated_time,participants",
        "limit": limit,
        "access_token": ACCESS_TOKEN,
    })
    return data.get("data", [])

def get_messages(conversation_id: str, limit: int = 25) -> list[dict]:
    data = _get(conversation_id, {
        "fields": f"messages.limit({limit}){{id,message,from,to,created_time}}",
        "access_token": ACCESS_TOKEN,
    })
    return data.get("messages", {}).get("data", [])


def send_message(recipient_id: str, message: str) -> str:
    result = _post("me/messages", {
        "recipient": f'{{"id":"{recipient_id}"}}',
        "message": f'{{"text":"{message}"}}',
        "access_token": ACCESS_TOKEN,
    })
    return result.get("message_id", "")


if __name__ == "__main__":
    posts = get_recent_media(limit=1)
    if posts:
        latest_post = posts[0]
        print(f"Latest post: {latest_post.get('permalink')}")
        for c in get_comments(latest_post["id"]):
            print(f"  {c['username']}: {c['text']}")

    for convo in get_conversations(limit=5):
        print(f"Conversation {convo['id']} updated {convo['updated_time']}")