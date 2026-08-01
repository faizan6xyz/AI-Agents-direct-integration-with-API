import os
import re
import time
import json
import logging
import requests
from urllib.parse import urlparse
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ig_post")
GRAPH_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"
MAX_REEL_SECONDS = 15 * 60      # 15 min
MAX_STORY_SECONDS = 60          # 60 sec
MAX_VIDEO_SECONDS = 60 * 60     # 60 min
MIN_VIDEO_SECONDS = 3           # IG rejects clips shorter than this
MAX_CAPTION_CHARS = 2170
MAX_HASHTAGS = 5
MAX_PHOTO_BYTES = 8 * 1024 * 1024        # 8 MB
MAX_VIDEO_BYTES = 1024 * 1024 * 1024     # 1 GB
MIN_ASPECT_RATIO = 4 / 5    # tallest allowed (portrait)
MAX_ASPECT_RATIO = 1.91     # widest allowed (landscape)
REQUEST_TIMEOUT = 30                 # seconds, for every HTTP call
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2               # seconds; doubles each retry
RETRYABLE_IG_ERROR_CODES = {4, 17, 32}   # IG rate-limit / throttling codes
ALLOWED_URL_SCHEMES = {"https"}

def _redact(text: str, access_token: str = None) -> str:
    if access_token:
        text = text.replace(access_token, "[REDACTED]")
    return text

def _validate_media_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise ValueError(f"Refusing to fetch '{url}': only {ALLOWED_URL_SCHEMES} URLs are allowed.")
    if not parsed.netloc:
        raise ValueError(f"'{url}' is not a valid absolute URL.")

def _request_with_retry(method: str, url: str, access_token: str = None, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            logger.warning(_redact(f"Network error on attempt {attempt}/{MAX_RETRIES}: {e}", access_token))
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
    raise RuntimeError(_redact(f"Request to '{url}' failed after {MAX_RETRIES} attempts: {last_exc}", access_token))


def _post(endpoint: str, params: dict) -> dict:
    token = params.get("access_token")
    resp = _request_with_retry("POST", f"{BASE_URL}/{endpoint}", data=params, access_token=token)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(_redact(f"Instagram API error: {data['error']}", token))
    return data

def _get(endpoint: str, params: dict) -> dict:
    token = params.get("access_token")
    resp = _request_with_retry("GET", f"{BASE_URL}/{endpoint}", params=params, access_token=token)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(_redact(f"Instagram API error: {data['error']}", token))
    return data

def check_ig_username(target_username, ig_user_id, access_token) -> bool:
    params = {"fields": f"business_discovery.username({target_username})" "{username,id,followers_count,media_count,biography}","access_token": access_token,}
    resp = _request_with_retry("GET", f"{BASE_URL}/{ig_user_id}", params=params, access_token=access_token)
    try:
        payload = resp.json()
    except ValueError:
        return False
    if resp.status_code == 200 and "business_discovery" in payload:
        return True   # username exists (as a Business/Creator account)
    return False       # not found, or exists but isn't a business/creator account

def _check_caption(caption: str) -> str:
    if len(caption) > MAX_CAPTION_CHARS:
        caption = caption[:MAX_CAPTION_CHARS]
    hashtags = list(re.finditer(r"(?<!\w)#\w+", caption))
    if len(hashtags) > MAX_HASHTAGS:
        cutoff = hashtags[MAX_HASHTAGS].start()
        caption = caption[:cutoff].rstrip()
    match = re.search(r"(?<!\w)#\w+$", caption)
    if match and len(caption) == MAX_CAPTION_CHARS:
        caption = caption[:match.start()].rstrip()
    return caption

# Container is the object that holds the media and other info before publishing
def wait_for_container(access_token: str, container_id: str, timeout: int = 300, interval: int = 5) -> None:
    elapsed = 0
    while elapsed < timeout:
        status = _get(container_id, {"fields": "status_code", "access_token": access_token})
        code = status.get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise RuntimeError(f"Container {container_id} failed to process")
        time.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"Container {container_id} did not finish within {timeout}s")

def publish_container(access_token: str, ig_user_id: str, creation_id: str) -> str:
    published = _post(f"{ig_user_id}/media_publish", {"creation_id": creation_id, "access_token": access_token})
    return published["id"]

def post_photo(access_token: str, ig_user_id: str, image_url: str, caption: str = "", media_size: int = None, publish: bool = True, ) -> str:
    _validate_media_url(image_url)
    caption = _check_caption(caption)
    if media_size is not None and media_size > MAX_PHOTO_BYTES:
        raise ValueError(f"Photo exceeds max size of {MAX_PHOTO_BYTES} bytes")
    params = {"image_url": image_url, "caption": caption, "access_token": access_token, }
    container = _post(f"{ig_user_id}/media", params)
    creation_id = container["id"]
    if not publish:
        return creation_id
    return publish_container(access_token, ig_user_id, creation_id)

def post_video(access_token: str, ig_user_id: str, height: int, width: int, video_url: str, media_size: int, caption: str = "", as_reel: bool = True, cover_url: str = None,publish: bool = True, media_duration: int = 0, ) -> str:
    _validate_media_url(video_url)
    if cover_url is not None:
        if not as_reel:
            raise ValueError("cover_url (custom thumbnail) is only supported for Reels")
        _validate_media_url(cover_url)
    caption = _check_caption(caption)
    if media_size > MAX_VIDEO_BYTES:
        raise ValueError(f"Video exceeds max size of {MAX_VIDEO_BYTES} bytes")
    if media_duration < MIN_VIDEO_SECONDS:
        raise ValueError(f"Video is shorter than the minimum of {MIN_VIDEO_SECONDS}s")
    if as_reel:
        if media_duration > MAX_REEL_SECONDS:
            raise ValueError(f"Reel exceeds max duration of {MAX_REEL_SECONDS}s")
    else:
        if media_duration > MAX_VIDEO_SECONDS:
            raise ValueError(f"Video exceeds max duration of {MAX_VIDEO_SECONDS}s")
    ratio = width / height
    if not (MIN_ASPECT_RATIO - 0.01 <= ratio <= MAX_ASPECT_RATIO + 0.01):
        raise ValueError(f"Aspect ratio {ratio:.2f} is outside the allowed range")
    params = {"video_url": video_url,"caption": caption,"media_type": "REELS" if as_reel else "VIDEO", "access_token": access_token, }
    if cover_url is not None:
        params["cover_url"] = cover_url  # custom thumbnail image; takes precedence over thumb_offset
    container = _post(f"{ig_user_id}/media", params)
    creation_id = container["id"]
    wait_for_container(access_token, creation_id)
    if not publish:
        return creation_id
    return publish_container(access_token, ig_user_id, creation_id)
 
def post_carousel( access_token: str, ig_user_id: str, media_size: list, media_duration: list, media_urls: list, is_video: list, caption: str = "", publish: bool = True, ) -> str:
    if len(media_urls) != len(is_video):
        raise ValueError("media_urls and is_video must be the same length")
    if not (2 <= len(media_urls) <= 10):
        raise ValueError("Carousels need 2-10 items")
    caption = _check_caption(caption)
    for url, vid, siz, dura in zip(media_urls, is_video, media_size, media_duration):
        _validate_media_url(url)
        if vid:
            if siz > MAX_VIDEO_BYTES:
                raise ValueError(f"Video exceeds max size of {MAX_VIDEO_BYTES} bytes")
            if dura > MAX_VIDEO_SECONDS:
                raise ValueError(f"Video exceeds max duration of {MAX_VIDEO_SECONDS}s")
        else:
            if siz > MAX_PHOTO_BYTES:
                raise ValueError(f"Photo exceeds max size of {MAX_PHOTO_BYTES} bytes")
    child_ids = []
    for url, vid in zip(media_urls, is_video):
        params = {"is_carousel_item": "true", "access_token": access_token}
        if vid:
            params["media_type"] = "VIDEO"
            params["video_url"] = url
        else:
            params["image_url"] = url
        child = _post(f"{ig_user_id}/media", params)
        child_id = child["id"]
        if vid:
            wait_for_container(access_token, child_id)
        child_ids.append(child_id)
    params = { "media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption, "access_token": access_token,}
    container = _post(f"{ig_user_id}/media", params)
    creation_id = container["id"]
    if not publish:
        return creation_id
    return publish_container(access_token, ig_user_id, creation_id)

def post_story( access_token: str, ig_user_id: str, media_size: int, media_url: str, is_video: bool = False, publish: bool = True, media_duration: int = 0, ) -> str:
    _validate_media_url(media_url)
    if is_video:
        if media_size > MAX_VIDEO_BYTES:
            raise ValueError(f"Video exceeds max size of {MAX_VIDEO_BYTES} bytes")
        if media_duration > MAX_STORY_SECONDS:
            raise ValueError(f"Story exceeds max duration of {MAX_STORY_SECONDS}s")
    else:
        if media_size > MAX_PHOTO_BYTES:
            raise ValueError(f"Photo exceeds max size of {MAX_PHOTO_BYTES} bytes")
    params = {"media_type": "STORIES", "access_token": access_token}
    if is_video:
        params["video_url"] = media_url
    else:
        params["image_url"] = media_url
    container = _post(f"{ig_user_id}/media", params)
    creation_id = container["id"]
    if is_video:
        wait_for_container(access_token, creation_id)
    if not publish:
        return creation_id
    return publish_container(access_token, ig_user_id, creation_id)

def get_media_insights(media_id, access_token, metrics=("views", "reach", "likes", "comments", "saved", "shares")):
    if not access_token:
        return {"success": False, "data": None, "error": f"missing access_token for {media_id}"}
    url = f"https://graph.facebook.com/v22.0/{media_id}/insights"
    params = {"metric": ",".join(metrics), "access_token": access_token}
    try:
        response = requests.get(url, params=params, timeout=10)
        payload = response.json()
    except requests.RequestException as e:
        return {"success": False, "data": None, "error": f"request failed for {media_id}: {e}"}
    except ValueError as e:
        return {"success": False, "data": None, "error": f"response was not valid JSON for {media_id}: {e}"}
    if "error" in payload:
        return {"success": False, "data": None, "error": f"API error for {media_id}: {payload['error']}"}
    result = {}
    try:
        for item in payload.get("data", []):
            name = item.get("name")
            values = item.get("values", [])
            if name and values:
                result[name] = values[0].get("value")
    except (KeyError, IndexError, TypeError) as e:
        return {"success": False, "data": None, "error": f"unexpected response shape for {media_id}: {e}"}

    return {"success": True, "data": result, "error": None}


'''
if __name__ == "__main__":
    ACCESS_TOKEN = "..."
    IG_USER_ID = "..."

    # Example: single photo
    media_id = post_photo(
        ACCESS_TOKEN, IG_USER_ID,
        image_url="https://example.com/photo.jpg",
        caption="Posted via API #test",
    )
    print(f"Published media id: {media_id}")

    # Example: photo with a user tag
    post_photo(
        ACCESS_TOKEN, IG_USER_ID,
        image_url="https://example.com/photo.jpg",
        caption="At the beach!",
        user_tags=[{"username": "some_user", "x": 0.5, "y": 0.5}],
    )

    # Example: mixed carousel
    post_carousel(
        ACCESS_TOKEN, IG_USER_ID,
        media_size=[500_000, 2_000_000],
        media_duration=[0, 30],
        media_urls=["https://example.com/pic1.jpg", "https://example.com/clip1.mp4"],
        is_video=[False, True],
        caption="Mixed carousel!",
    )

    # Example: story
    post_story(
        ACCESS_TOKEN, IG_USER_ID,
        media_size=1_000_000,
        media_url="https://example.com/story_clip.mp4",
        is_video=True,
        media_duration=10,
    )

    # Example: schedule now, publish later
    container_id = post_photo(
        ACCESS_TOKEN, IG_USER_ID,
        image_url="https://example.com/photo.jpg",
        publish=False,
    )
    # ... later ...
    publish_container(ACCESS_TOKEN, IG_USER_ID, container_id)
'''