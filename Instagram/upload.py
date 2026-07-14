import os
import re
import time
import json
import subprocess
import requests
ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "YOUR_LONG_LIVED_TOKEN")
IG_USER_ID = os.environ.get("IG_USER_ID", "YOUR_IG_USER_ID")
GRAPH_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"
MAX_REEL_SECONDS = 15 * 60      # 15 min
MAX_STORY_SECONDS = 60          # 60 sec
MAX_VIDEO_SECONDS = 60 * 60     # 60 min
MIN_VIDEO_SECONDS = 3           # IG rejects clips shorter than this
MAX_CAPTION_CHARS = 2200
MAX_HASHTAGS = 30
MAX_PHOTO_BYTES = 8 * 1024 * 1024        # 8 MB
MAX_VIDEO_BYTES = 1024 * 1024 * 1024     # 1 GB
MIN_ASPECT_RATIO = 4 / 5    # tallest allowed (portrait)
MAX_ASPECT_RATIO = 1.91     # widest allowed (landscape)

def _post(endpoint: str, params: dict) -> dict:
    resp = requests.post(f"{BASE_URL}/{endpoint}", data=params)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Instagram API error: {data['error']}")
    return data

def _get(endpoint: str, params: dict) -> dict:
    resp = requests.get(f"{BASE_URL}/{endpoint}", params=params)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Instagram API error: {data['error']}")
    return data

def get_video_duration_seconds(video_url: str, timeout: int = 30) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        video_url,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=True
        )
    except FileNotFoundError:
        raise RuntimeError(
            "ffprobe not found. Install ffmpeg (e.g. `apt install ffmpeg`) "
            "to enable duration checks."
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe failed to read '{video_url}': {e.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffprobe timed out probing '{video_url}'")
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        raise RuntimeError(f"Could not parse duration for '{video_url}'")
    return duration

def _check_duration_limit(video_url: str, max_seconds: int, label: str, min_seconds: int = MIN_VIDEO_SECONDS) -> None:
    duration = get_video_duration_seconds(video_url)
    if duration > max_seconds:
        raise ValueError(
            f"{label} video is {duration:.1f}s long, which exceeds the "
            f"{max_seconds}s ({max_seconds / 60:.0f} min) limit. "
            f"URL: {video_url}"
        )
    if duration < min_seconds:
        raise ValueError(
            f"{label} video is only {duration:.1f}s long, which is below "
            f"the {min_seconds}s minimum. URL: {video_url}"
        )

def get_video_resolution(video_url: str, timeout: int = 30) -> tuple[int, int]:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        video_url,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=True
        )
    except FileNotFoundError:
        raise RuntimeError(
            "ffprobe not found. Install ffmpeg (e.g. `apt install ffmpeg`) "
            "to enable resolution checks."
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe failed to read '{video_url}': {e.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffprobe timed out probing '{video_url}'")
    try:
        stream = json.loads(result.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, ValueError, json.JSONDecodeError):
        raise RuntimeError(f"Could not parse resolution for '{video_url}'")

def _check_aspect_ratio(width: int, height: int, label: str, url: str) -> None:
    ratio = width / height
    if not (MIN_ASPECT_RATIO - 0.01 <= ratio <= MAX_ASPECT_RATIO + 0.01):
        raise ValueError(
            f"{label} has aspect ratio {ratio:.2f} ({width}x{height}), which "
            f"falls outside Instagram's accepted range of {MIN_ASPECT_RATIO:.2f} "
            f"(4:5 portrait) to {MAX_ASPECT_RATIO:.2f} (1.91:1 landscape). URL: {url}"
        )

def get_remote_file_size(url: str, timeout: int = 15) -> int:
    resp = requests.head(url, timeout=timeout, allow_redirects=True)
    size = resp.headers.get("Content-Length")
    if size is None:
        raise RuntimeError(
            f"Could not determine file size for '{url}' "
            "(server did not return Content-Length)."
        )
    return int(size)

def _check_file_size(url: str, max_bytes: int, label: str) -> None:
    size = get_remote_file_size(url)
    if size > max_bytes:
        raise ValueError(
            f"{label} file is {size / (1024 * 1024):.1f} MB, which exceeds "
            f"the {max_bytes / (1024 * 1024):.0f} MB limit. URL: {url}"
        )

def _check_caption(caption: str) -> None:
    if len(caption) > MAX_CAPTION_CHARS:
        raise ValueError(
            f"Caption is {len(caption)} characters, which exceeds Instagram's "
            f"{MAX_CAPTION_CHARS} character limit."
        )
    hashtag_count = len(re.findall(r"(?<!\w)#\w+", caption))
    if hashtag_count > MAX_HASHTAGS:
        raise ValueError(
            f"Caption has {hashtag_count} hashtags, which exceeds Instagram's "
            f"{MAX_HASHTAGS} hashtag limit."
        )

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

def _build_tagging_params(user_tags: list[dict] = None, location_id: str = None) -> dict:
    extra = {}
    if user_tags:
        extra["user_tags"] = json.dumps(user_tags)
    if location_id:
        extra["location_id"] = location_id
    return extra

def post_photo(image_url: str, caption: str = "", user_tags: list[dict] = None, location_id: str = None, publish: bool = True,) -> str:
    _check_caption(caption)
    _check_file_size(image_url, MAX_PHOTO_BYTES, "Photo")
    params = {
        "image_url": image_url,
        "caption": caption,
        "access_token": ACCESS_TOKEN,
        **_build_tagging_params(user_tags, location_id),
    }
    container = _post(f"{IG_USER_ID}/media", params)
    creation_id = container["id"]
    if not publish:
        return creation_id
    return publish_container(creation_id)

def post_video(video_url: str, caption: str = "", as_reel: bool = True, user_tags: list[dict] = None, location_id: str = None, thumb_offset_ms: int = None, publish: bool = True,) -> str:
    _check_caption(caption)
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
        **_build_tagging_params(user_tags, location_id),
    }
    if thumb_offset_ms is not None:
        params["thumb_offset"] = thumb_offset_ms  # cover frame, in milliseconds
    container = _post(f"{IG_USER_ID}/media", params)
    creation_id = container["id"]
    wait_for_container(creation_id)
    if not publish:
        return creation_id
    return publish_container(creation_id)

def post_carousel(media_urls: list[str], is_video: list[bool], caption: str = "", location_id: str = None, publish: bool = True,) -> str:
    if len(media_urls) != len(is_video):
        raise ValueError("media_urls and is_video must be the same length")
    if not (2 <= len(media_urls) <= 10):
        raise ValueError("Carousels need 2-10 items")
    _check_caption(caption)
    for url, vid in zip(media_urls, is_video):
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
    if location_id:
        params["location_id"] = location_id
    container = _post(f"{IG_USER_ID}/media", params)
    creation_id = container["id"]
    if not publish:
        return creation_id
    return publish_container(creation_id)

def post_story(media_url: str, is_video: bool = False, publish: bool = True) -> str:
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

if __name__ == "__main__":
    '''
    # Example: single photo
    media_id = post_photo(
        image_url="https://example.com/photo.jpg",
        caption="Posted via API #test",
    )
    print(f"Published media id: {media_id}")

    # Example: photo with a user tag and location
    post_photo(
        image_url="https://example.com/photo.jpg",
        caption="At the beach!",
        user_tags=[{"username": "some_user", "x": 0.5, "y": 0.5}],
        location_id="123456789",
    )

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