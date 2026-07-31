import os
import re
import time
import json
import logging
import subprocess
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

#  strips your access token out of any error message or log line before it surfaces, so a stack trace or log file can't leak it
def _redact(text: str) -> str:
    if ACCESS_TOKEN:
        text = text.replace(ACCESS_TOKEN, "[REDACTED]")
    return text

# ejects anything that isn't https:// before it's fetched, so a malicious or malformed URL (file://, internal IPs, etc.) never reaches requests
def _validate_media_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise ValueError(f"Refusing to fetch '{url}': only {ALLOWED_URL_SCHEMES} URLs are allowed." )
    if not parsed.netloc:
        raise ValueError(f"'{url}' is not a valid absolute URL.")

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

def _post(endpoint: str, params: dict) -> dict:
    resp = _request_with_retry("POST", f"{BASE_URL}/{endpoint}", data=params)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(_redact(f"Instagram API error: {data['error']}"))
    return data

def _get(endpoint: str, params: dict) -> dict:
    resp = _request_with_retry("GET", f"{BASE_URL}/{endpoint}", params=params)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(_redact(f"Instagram API error: {data['error']}"))
    return data








#get video size resolation and other shit things about the file wull be done using the drive 















# using the check username function for the tagging 
def check_ig_username(target_username, ig_user_id , access_token):
    url = f"https://graph.facebook.com/v22.0/{ig_user_id}"
    params = { "fields": f"business_discovery.username({target_username})" "{username,id,followers_count,media_count,biography}","access_token": access_token,}
    resp = requests.get(url, params=params, timeout=10)
    payload = resp.json()
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

# Container is the object that holds the media and the other info beofre publishing
def wait_for_container(container_id: str, timeout: int = 300, interval: int = 5) -> None:
    elapsed = 0
    while elapsed < timeout:
        status = _get(container_id, {
            "fields": "status_code",
            "access_token": ACCESS_TOKEN,
        })
        code = status.get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise RuntimeError(f"Container {container_id} failed to process")
        time.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"Container {container_id} did not finish within {timeout}s")

def _build_tagging_params(user_tags: list[dict] = None) -> dict:
    extra = {}
    if user_tags:
        extra["user_tags"] = json.dumps(user_tags)
    return extra


def post_photo(ACCESS_TOKEN , IG_USER_ID , image_url: str, caption: str = "", user_tags: list[dict] = None,  publish: bool = True,) -> str:
    _validate_media_url(image_url)
    _check_caption(caption)
    usernametag = []
    for i in user_tags:
        x = check_ig_username(i["username"], IG_USER_ID , ACCESS_TOKEN)
        if x :
            usernametag.append(i["username"])
    params = {"image_url": image_url, "caption": caption,"access_token": ACCESS_TOKEN, **_build_tagging_params(usernametag),}
    container = _post(f"{IG_USER_ID}/media", params)
    creation_id = container["id"]
    usernametag.clear()
    if not publish:
        return creation_id
    return publish_container(creation_id)

def post_video(ACCESS_TOKEN , IG_USER_ID , video_url: str, caption: str = "", as_reel: bool = True, user_tags: list[dict] = None,  thumb_offset_ms: int = None, publish: bool = True,) -> str:
    _validate_media_url(video_url)
    _check_caption(caption)
    usernametag = []
    for i in user_tags:
        x = check_ig_username(i["username"], IG_USER_ID , ACCESS_TOKEN)
        if x :
            usernametag.append(i["username"])
    _check_file_size(video_url, MAX_VIDEO_BYTES, "Reel" if as_reel else "Video")
    if as_reel:
        _check_duration_limit(video_url, MAX_REEL_SECONDS, "Reel")
    else:
        _check_duration_limit(video_url, MAX_VIDEO_SECONDS, "Video")
    width, height = get_video_resolution(video_url)
    _check_aspect_ratio(width, height, "Reel" if as_reel else "Video", video_url)
    params = {
        "video_url": video_url,
        "caption": caption,
        "media_type": "REELS" if as_reel else "VIDEO",
        "access_token": ACCESS_TOKEN,
        **_build_tagging_params(user_tags),
    }
    if thumb_offset_ms is not None:
        params["thumb_offset"] = thumb_offset_ms  # cover frame, in milliseconds
    container = _post(f"{IG_USER_ID}/media", params)
    creation_id = container["id"]
    usernametag.clear()
    wait_for_container(creation_id)
    if not publish:
        return creation_id
    return publish_container(creation_id)

def post_carousel(ACCESS_TOKEN , IG_USER_ID , media_urls: list[str], is_video: list[bool], caption: str = "", publish: bool = True,) -> str:
    if len(media_urls) != len(is_video):
        raise ValueError("media_urls and is_video must be the same length")
    if not (2 <= len(media_urls) <= 10):
        raise ValueError("Carousels need 2-10 items")
    _check_caption(caption)
    for url, vid in zip(media_urls, is_video):
        _validate_media_url(url)
        if vid:
            _check_file_size(url, MAX_VIDEO_BYTES, "Carousel video item")
            _check_duration_limit(url, MAX_VIDEO_SECONDS, "Carousel video item")
        else:
            _check_file_size(url, MAX_PHOTO_BYTES, "Carousel photo item")
    child_ids = []
    for url, vid in zip(media_urls, is_video):
        params = {
            "is_carousel_item": "true",
            "access_token": ACCESS_TOKEN,
        }
        if vid:
            params["media_type"] = "VIDEO"
            params["video_url"] = url
        else:
            params["image_url"] = url
        child = _post(f"{IG_USER_ID}/media", params)
        child_id = child["id"]
        if vid:
            wait_for_container(child_id)
        child_ids.append(child_id)
    params = {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
        "access_token": ACCESS_TOKEN,
    }
    container = _post(f"{IG_USER_ID}/media", params)
    creation_id = container["id"]
    if not publish:
        return creation_id
    return publish_container(creation_id)

def post_story(ACCESS_TOKEN , IG_USER_ID , media_url: str, is_video: bool = False, publish: bool = True) -> str:
    _validate_media_url(media_url)
    if is_video:
        _check_duration_limit(media_url, MAX_STORY_SECONDS, "Story", min_seconds=1)
        _check_file_size(media_url, MAX_VIDEO_BYTES, "Story")
    else:
        _check_file_size(media_url, MAX_PHOTO_BYTES, "Story")
    params = {
        "media_type": "STORIES",
        "access_token": ACCESS_TOKEN,
    }
    if is_video:
        params["video_url"] = media_url
    else:
        params["image_url"] = media_url
    container = _post(f"{IG_USER_ID}/media", params)
    creation_id = container["id"]
    if is_video:
        wait_for_container(creation_id)
    if not publish:
        return creation_id
    return publish_container(creation_id)

def publish_container(creation_id: str) -> str:
    published = _post(f"{IG_USER_ID}/media_publish", {
        "creation_id": creation_id,
        "access_token": ACCESS_TOKEN,
    })
    return published["id"]

'''
if __name__ == "__main__":
    # Example: single photo
    media_id = post_photo(
        image_url="https://example.com/photo.jpg",
        caption="Posted via API #test",
    )
    print(f"Published media id: {media_id}")

    # Example: photo with a user tag 
    post_photo(
        image_url="https://example.com/photo.jpg",
        caption="At the beach!",
        user_tags=[{"username": "some_user", "x": 0.5, "y": 0.5}],)
    # Example: mixed carousel
    post_carousel(
        media_urls=["https://example.com/pic1.jpg", "https://example.com/clip1.mp4"],
        is_video=[False, True],
        caption="Mixed carousel!",
    )

    # Example: story
    post_story("https://example.com/story_clip.mp4", is_video=True)

    # Example: schedule now, publish later
    container_id = post_photo(image_url="https://example.com/photo.jpg", publish=False)
    # ... later ...
    publish_container(container_id)

    # Example: this will raise ValueError before hitting the API
    # if the video is longer than 15 minutes
    post_video("https://example.com/too_long_reel.mp4", as_reel=True)
    '''