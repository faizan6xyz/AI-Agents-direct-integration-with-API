import os
import re
import time
import logging
import requests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ig_comments")
ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
GRAPH_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2
RETRYABLE_IG_ERROR_CODES = {4, 17, 32}  # IG rate-limit / throttling codes
MAX_COMMENT_REPLY_CHARS = 2200
SPAM_MIN_HASHTAGS_FOR_FLAG = 5
ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
SPAM_LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
if not ACCESS_TOKEN:
    raise RuntimeError("IG_ACCESS_TOKEN is not set. Export it as an environment variable "
        "rather than hardcoding it in source.")
if not IG_USER_ID:
    raise RuntimeError("IG_USER_ID is not set as an environment variable.")
if not ID_RE.match(IG_USER_ID):
    raise RuntimeError("IG_USER_ID does not look like a valid ID.")

def _redact(text: str) -> str:
    if ACCESS_TOKEN:
        text = text.replace(ACCESS_TOKEN, "[REDACTED]")
    return text

def _validate_id(object_id: str, label: str = "ID") -> None:
    if not object_id or not isinstance(object_id, str) or not ID_RE.match(object_id):
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
            logger.warning(f"IG error code {err_code} (throttled), retrying {attempt}/{MAX_RETRIES}")
            time.sleep(RETRY_BACKOFF_BASE ** attempt)
            continue
        return resp
    raise RuntimeError(_redact(f"Request to '{url}' failed after {MAX_RETRIES} attempts: {last_exc}"))

def _get(endpoint: str, params: dict) -> dict:
    resp = _request_with_retry("GET", f"{BASE_URL}/{endpoint}", params=params)
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"Non-JSON response from '{endpoint}' (HTTP {resp.status_code})")
    if "error" in data:
        raise RuntimeError(_redact(f"Instagram API error: {data['error']}"))
    return data

def _post(endpoint: str, params: dict) -> dict:
    resp = _request_with_retry("POST", f"{BASE_URL}/{endpoint}", data=params)
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"Non-JSON response from '{endpoint}' (HTTP {resp.status_code})")
    if "error" in data:
        raise RuntimeError(_redact(f"Instagram API error: {data['error']}"))
    return data

def _delete(endpoint: str, params: dict) -> dict:
    resp = _request_with_retry("DELETE", f"{BASE_URL}/{endpoint}", params=params)
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"Non-JSON response from '{endpoint}' (HTTP {resp.status_code})")
    if "error" in data:
        raise RuntimeError(_redact(f"Instagram API error: {data['error']}"))
    return data

def _get_all_pages(endpoint: str, params: dict, max_pages: int = 20) -> list[dict]:
    results = []
    next_params = dict(params)
    next_url = f"{BASE_URL}/{endpoint}"

    for _ in range(max_pages):
        resp = _request_with_retry("GET", next_url, params=next_params)
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"Non-JSON response while paginating '{endpoint}'")
        if "error" in data:
            raise RuntimeError(_redact(f"Instagram API error: {data['error']}"))
        results.extend(data.get("data", []))
        next_url = data.get("paging", {}).get("next")
        if not next_url:
            break
        next_params = {}  # cursor URL already carries all needed params
    return results

def get_recent_media(limit: int = 25, all_pages: bool = False) -> list[dict]:
    if limit <= 0 or limit > 100:
        raise ValueError("limit must be between 1 and 100.")
    params = {"fields": "id,caption,media_type,timestamp,permalink",
        "limit": limit,
        "access_token": ACCESS_TOKEN,}
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
    params = {"fields": "id,text,username,timestamp",
        "access_token": ACCESS_TOKEN,}
    if all_pages:
        return _get_all_pages(f"{comment_id}/replies", params)
    return _get(f"{comment_id}/replies", params).get("data", [])

def get_comments_with_replies(media_id: str, all_pages: bool = False) -> list[dict]:
    comments = get_comments(media_id, all_pages=all_pages)
    for comment in comments:
        try:
            comment["replies"] = get_comment_replies(comment["id"], all_pages=all_pages)
        except (RuntimeError, ValueError) as e:
            logger.warning(f"Could not fetch replies for comment {comment.get('id')}: {e}")
            comment["replies"] = []
    return comments

def get_all_comments(media_limit: int = 25) -> dict:
    media_items = get_recent_media(limit=media_limit)
    all_comments = {}
    for media in media_items:
        media_id = media["id"]
        try:
            comments = get_comments(media_id)
        except (RuntimeError, ValueError) as e:
            logger.warning(f"Skipping media {media_id}: could not fetch comments: {e}")
            comments = []
        all_comments[media_id] = {"caption": media.get("caption", ""),
            "permalink": media.get("permalink"),
            "comments": comments,}
    return all_comments

def is_probable_spam(comment_text: str) -> bool:
    if not comment_text:
        return False
    if SPAM_LINK_RE.search(comment_text):
        return True
    return comment_text.count("#") >= SPAM_MIN_HASHTAGS_FOR_FLAG

def reply_to_comment(comment_id: str, message: str) -> str:
    _validate_id(comment_id, "comment_id")
    if not message or not message.strip():
        raise ValueError("Reply message cannot be empty.")
    if len(message) > MAX_COMMENT_REPLY_CHARS:
        raise ValueError(f"Reply is {len(message)} characters, which exceeds Instagram's "
            f"{MAX_COMMENT_REPLY_CHARS} character limit.")
    result = _post(f"{comment_id}/replies", {"message": message,
        "access_token": ACCESS_TOKEN,})
    return result["id"]

def hide_comment(comment_id: str, hide: bool = True) -> bool:
    _validate_id(comment_id, "comment_id")
    result = _post(comment_id, {"hide": "true" if hide else "false",
        "access_token": ACCESS_TOKEN,})
    return result.get("success", False)

def delete_comment(comment_id: str, confirm: bool = False) -> bool:
    _validate_id(comment_id, "comment_id")
    if not confirm:
        raise ValueError("delete_comment is permanent. Call with confirm=True to proceed.")
    result = _delete(comment_id, {"access_token": ACCESS_TOKEN})
    return result.get("success", False)

if __name__ == "__main__":
    try:
        posts = get_recent_media(limit=1)
    except RuntimeError as e:
        logger.error(f"Could not fetch media: {e}")
        posts = []
    if posts:
        latest_post = posts[0]
        print(f"Latest post: {latest_post.get('permalink')}")
        try:
            for c in get_comments(latest_post["id"]):
                flag = " [possible spam]" if is_probable_spam(c.get("text", "")) else ""
                print(f"  {c['username']}: {c['text']}{flag}")
        except RuntimeError as e:
            logger.error(f"Could not fetch comments: {e}")
    else:
        print("No recent posts found.")