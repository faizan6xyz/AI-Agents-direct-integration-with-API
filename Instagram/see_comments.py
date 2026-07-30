import os
import re
import time
import logging
import requests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ig_comments")
ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
GRAPH_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2
RETRYABLE_IG_ERROR_CODES = {4, 17, 32}
MAX_COMMENT_REPLY_CHARS = 2200
ID_RE = re.compile(r"^[A-Za-z0-9_]+$")

if not ACCESS_TOKEN:
    raise RuntimeError("IG_ACCESS_TOKEN is not set.")

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
            time.sleep(RETRY_BACKOFF_BASE ** attempt)
            continue
        try:
            body = resp.json()
        except ValueError:
            return resp
        err_code = body.get("error", {}).get("code")
        if err_code in RETRYABLE_IG_ERROR_CODES and attempt < MAX_RETRIES:
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

def get_comments(media_id: str) -> list[dict]:
    _validate_id(media_id, "media_id")
    params = {"fields": "id,text,username,timestamp,like_count", "access_token": ACCESS_TOKEN}
    return _get(f"{media_id}/comments", params).get("data", [])

def get_comment_replies(comment_id: str) -> list[dict]:
    _validate_id(comment_id, "comment_id")
    params = {"fields": "id,text,username,timestamp", "access_token": ACCESS_TOKEN}
    return _get(f"{comment_id}/replies", params).get("data", [])

def reply_to_comment(comment_id: str, message: str) -> str:
    _validate_id(comment_id, "comment_id")
    if not message or not message.strip():
        raise ValueError("Reply message cannot be empty.")
    if len(message) > MAX_COMMENT_REPLY_CHARS:
        raise ValueError(f"Reply exceeds {MAX_COMMENT_REPLY_CHARS} character limit.")
    result = _post(f"{comment_id}/replies", {"message": message, "access_token": ACCESS_TOKEN})
    return result["id"]

def hide_comment(comment_id: str, hide: bool = True) -> bool:
    _validate_id(comment_id, "comment_id")
    result = _post(comment_id, {"hide": "true" if hide else "false", "access_token": ACCESS_TOKEN})
    return result.get("success", False)

def delete_comment(comment_id: str, confirm: bool = False) -> bool:
    _validate_id(comment_id, "comment_id")
    if not confirm:
        raise ValueError("delete_comment is permanent. Call with confirm=True to proceed.")
    result = _delete(comment_id, {"access_token": ACCESS_TOKEN})
    return result.get("success", False)