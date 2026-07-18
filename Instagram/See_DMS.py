import os
import re
import time
import json
import logging
import requests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ig_messages")
ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
GRAPH_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2
RETRYABLE_IG_ERROR_CODES = {4, 17, 32}  # IG rate-limit / throttling codes
MAX_DM_CHARS = 1000
MIN_SECONDS_BETWEEN_SENDS = 1.0  # crude self-throttle to avoid spammy burst
ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
if not ACCESS_TOKEN:
    raise RuntimeError("IG_ACCESS_TOKEN is not set. Export it as an environment variable "
        "rather than hardcoding it in source.")
if not IG_USER_ID:
    raise RuntimeError("IG_USER_ID is not set as an environment variable.")
if not ID_RE.match(IG_USER_ID):
    raise RuntimeError("IG_USER_ID does not look like a valid ID.")
_last_send_time = 0.0

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

def get_conversations(limit: int = 20, all_pages: bool = False) -> list[dict]:
    if limit <= 0 or limit > 100:
        raise ValueError("limit must be between 1 and 100.")
    params = {"platform": "instagram",
        "fields": "id,updated_time,participants",
        "limit": limit,
        "access_token": ACCESS_TOKEN,}
    if all_pages:
        return _get_all_pages(f"{IG_USER_ID}/conversations", params)
    return _get(f"{IG_USER_ID}/conversations", params).get("data", [])

def get_messages(conversation_id: str, limit: int = 25) -> list[dict]:
    _validate_id(conversation_id, "conversation_id")
    if limit <= 0 or limit > 100:
        raise ValueError("limit must be between 1 and 100.")
    data = _get(conversation_id, {"fields": f"messages.limit({limit}){{id,message,from,to,created_time}}",
        "access_token": ACCESS_TOKEN,})
    return data.get("messages", {}).get("data", [])

def get_all_conversations_with_messages(convo_limit: int = 20, message_limit: int = 25) -> dict:
    conversations = get_conversations(limit=convo_limit)
    all_convos = {}
    for convo in conversations:
        convo_id = convo["id"]
        try:
            messages = get_messages(convo_id, limit=message_limit)
        except (RuntimeError, ValueError) as e:
            logger.warning(f"Skipping conversation {convo_id}: could not fetch messages: {e}")
            messages = []
        all_convos[convo_id] = {"updated_time": convo.get("updated_time"),
            "participants": convo.get("participants"),
            "messages": messages,}
    return all_convos

def send_message(recipient_id: str, message: str) -> str:
    global _last_send_time
    _validate_id(recipient_id, "recipient_id")
    if not message or not message.strip():
        raise ValueError("Message cannot be empty.")
    if len(message) > MAX_DM_CHARS:
        raise ValueError(f"Message is {len(message)} characters, which exceeds Instagram's "
            f"{MAX_DM_CHARS} character limit.")
    elapsed = time.monotonic() - _last_send_time
    if elapsed < MIN_SECONDS_BETWEEN_SENDS:
        time.sleep(MIN_SECONDS_BETWEEN_SENDS - elapsed)
    result = _post("me/messages", {"recipient": json.dumps({"id": recipient_id}),
        "message": json.dumps({"text": message}),
        "access_token": ACCESS_TOKEN,})
    _last_send_time = time.monotonic()
    return result.get("message_id", "")

if __name__ == "__main__":
    try:
        convos = get_conversations(limit=5)
    except RuntimeError as e:
        logger.error(f"Could not fetch conversations: {e}")
        convos = []
    if convos:
        for convo in convos:
            print(f"Conversation {convo['id']} updated {convo['updated_time']}")
    else:
        print("No recent conversations found.")