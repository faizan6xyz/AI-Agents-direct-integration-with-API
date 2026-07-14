import os
import re
import json
import time
import logging
import requests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ig_engagement")
ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "YOUR_LONG_LIVED_TOKEN")
IG_USER_ID = os.environ.get("IG_USER_ID", "YOUR_IG_USER_ID")
GRAPH_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Fail fast if credentials were never configured.
if ACCESS_TOKEN in (None, "", "YOUR_LONG_LIVED_TOKEN"):
    raise RuntimeError(
        "IG_ACCESS_TOKEN is not set. Export it as an environment variable "
        "rather than hardcoding it in source."
    )
if IG_USER_ID in (None, "", "YOUR_IG_USER_ID"):
    raise RuntimeError("IG_USER_ID is not set as an environment variable.")
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2
RETRYABLE_IG_ERROR_CODES = {4, 17, 32}  # IG rate-limit / throttling codes
MAX_COMMENT_REPLY_CHARS = 2200
MAX_DM_CHARS = 1000
ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
SPAM_LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
SPAM_MIN_HASHTAGS_FOR_FLAG = 5

def _redact(text: str) -> str:
    if ACCESS_TOKEN:
        text = text.replace(ACCESS_TOKEN, "[REDACTED]")
    return text

def _validate_id(object_id: str, label: str = "ID") -> None:
    if not object_id or not ID_RE.match(str(object_id)):
        raise ValueError(f"Invalid {label}: {object_id!r}")

def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            logger.warning(_redact(f"Network error on attempt {attempt}/{MAX_RETRIES}: {e}"))
            time.sleep(RETRY_BACKOFF_BASE ** attempt)
            continue
        if resp.status_code == 429:
            logger.warning(f"Rate limited (HTTP 429) on attempt {attempt}/{MAX_RETRIES}")
            time.sleep(RETRY_BACKOFF_BASE ** attempt)
            continue
        try:
            body = resp.json()
        except ValueError:
            return resp
        err_code = body.get("error", {}).get("code")
        if err_code in RETRYABLE_IG_ERROR_CODES and attempt < MAX_RETRIES:
            logger.warning(f"IG error code {err_code} (throttled), retrying "
                            f"{attempt}/{MAX_RETRIES}")
            time.sleep(RETRY_BACKOFF_BASE ** attempt)
            continue
        return resp
    raise RuntimeError(_redact(f"Request to '{url}' failed after {MAX_RETRIES} attempts: {last_exc}"))

def _get(endpoint: str, params: dict) -> dict:
    resp = _request_with_retry("GET", f"{BASE_URL}/{endpoint}", params=params)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(_redact(f"Instagram API error: {data['error']}"))
    return data

def _post(endpoint: str, params: dict) -> dict:
    resp = _request_with_retry("POST", f"{BASE_URL}/{endpoint}", data=params)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(_redact(f"Instagram API error: {data['error']}"))
    return data

def _delete(endpoint: str, params: dict) -> dict:
    resp = _request_with_retry("DELETE", f"{BASE_URL}/{endpoint}", params=params)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(_redact(f"Instagram API error: {data['error']}"))
    return data

def _get_all_pages(endpoint: str, params: dict, max_pages: int = 20) -> list[dict]:
    results = []
    next_params = dict(params)
    next_url = f"{BASE_URL}/{endpoint}"
    for _ in range(max_pages):
        resp = _request_with_retry("GET", next_url, params=next_params)
        data = resp.json()
        if "error" in data:
            raise RuntimeError(_redact(f"Instagram API error: {data['error']}"))
        results.extend(data.get("data", []))
        next_url = data.get("paging", {}).get("next")
        if not next_url:
            break
        next_params = {}  # cursor URL already includes all needed params
    return results

def get_recent_media(limit: int = 25, all_pages: bool = False) -> list[dict]:
    params = {
        "fields": "id,caption,media_type,timestamp,permalink",
        "limit": limit,
        "access_token": ACCESS_TOKEN,
    }
    if all_pages:
        return _get_all_pages(f"{IG_USER_ID}/media", params)
    return _get(f"{IG_USER_ID}/media", params).get("data", [])

def get_comments(media_id: str, all_pages: bool = False) -> list[dict]:
    _validate_id(media_id, "media_id")
    params = {
        "fields": "id,text,username,timestamp,like_count",
        "access_token": ACCESS_TOKEN,
    }
    if all_pages:
        return _get_all_pages(f"{media_id}/comments", params)
    return _get(f"{media_id}/comments", params).get("data", [])

def get_comment_replies(comment_id: str, all_pages: bool = False) -> list[dict]:
    _validate_id(comment_id, "comment_id")
    params = {
        "fields": "id,text,username,timestamp",
        "access_token": ACCESS_TOKEN,
    }
    if all_pages:
        return _get_all_pages(f"{comment_id}/replies", params)
    return _get(f"{comment_id}/replies", params).get("data", [])

def is_probable_spam(comment_text: str) -> bool:
    if not comment_text:
        return False
    if SPAM_LINK_RE.search(comment_text):
        return True
    hashtag_count = comment_text.count("#")
    return hashtag_count >= SPAM_MIN_HASHTAGS_FOR_FLAG

def reply_to_comment(comment_id: str, message: str) -> str:
    _validate_id(comment_id, "comment_id")
    if not message or not message.strip():
        raise ValueError("Reply message cannot be empty.")
    if len(message) > MAX_COMMENT_REPLY_CHARS:
        raise ValueError(
            f"Reply is {len(message)} characters, which exceeds Instagram's "
            f"{MAX_COMMENT_REPLY_CHARS} character limit."
        )
    result = _post(f"{comment_id}/replies", {
        "message": message,
        "access_token": ACCESS_TOKEN,
    })
    return result["id"]

def hide_comment(comment_id: str, hide: bool = True) -> bool:
    _validate_id(comment_id, "comment_id")
    result = _post(comment_id, {
        "hide": "true" if hide else "false",
        "access_token": ACCESS_TOKEN,
    })
    return result.get("success", False)

def delete_comment(comment_id: str, confirm: bool = False) -> bool:
    _validate_id(comment_id, "comment_id")
    if not confirm:
        raise ValueError(
            "delete_comment is permanent. Call with confirm=True to proceed."
        )
    result = _delete(comment_id, {"access_token": ACCESS_TOKEN})
    return result.get("success", False)

def get_conversations(limit: int = 20, all_pages: bool = False) -> list[dict]:
    params = {
        "platform": "instagram",
        "fields": "id,updated_time,participants",
        "limit": limit,
        "access_token": ACCESS_TOKEN,
    }
    if all_pages:
        return _get_all_pages(f"{IG_USER_ID}/conversations", params)
    return _get(f"{IG_USER_ID}/conversations", params).get("data", [])

def get_messages(conversation_id: str, limit: int = 25) -> list[dict]:
    _validate_id(conversation_id, "conversation_id")
    data = _get(conversation_id, {
        "fields": f"messages.limit({limit}){{id,message,from,to,created_time}}",
        "access_token": ACCESS_TOKEN,
    })
    return data.get("messages", {}).get("data", [])

def send_message(recipient_id: str, message: str) -> str:
    _validate_id(recipient_id, "recipient_id")
    if not message or not message.strip():
        raise ValueError("Message cannot be empty.")
    if len(message) > MAX_DM_CHARS:
        raise ValueError(
            f"Message is {len(message)} characters, which exceeds Instagram's "
            f"{MAX_DM_CHARS} character limit."
        )
    result = _post("me/messages", {
        "recipient": json.dumps({"id": recipient_id}),
        "message": json.dumps({"text": message}),
        "access_token": ACCESS_TOKEN,
    })
    return result.get("message_id", "")

if __name__ == "__main__":
    posts = get_recent_media(limit=1)
    if posts:
        latest_post = posts[0]
        print(f"Latest post: {latest_post.get('permalink')}")
        for c in get_comments(latest_post["id"]):
            flag = " [possible spam]" if is_probable_spam(c.get("text", "")) else ""
            print(f"  {c['username']}: {c['text']}{flag}")
    for convo in get_conversations(limit=5):
        print(f"Conversation {convo['id']} updated {convo['updated_time']}")