import os
import time
import requests
ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "YOUR_LONG_LIVED_TOKEN")
IG_USER_ID = os.environ.get("IG_USER_ID", "YOUR_IG_USER_ID")
GRAPH_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"

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


def post_photo(image_url: str, caption: str = "") -> str:
    """Post a single JPEG image. Returns the published media id."""
    container = _post(f"{IG_USER_ID}/media", {
        "image_url": image_url,
        "caption": caption,
        "access_token": ACCESS_TOKEN,
    })
    creation_id = container["id"]

    published = _post(f"{IG_USER_ID}/media_publish", {
        "creation_id": creation_id,
        "access_token": ACCESS_TOKEN,
    })
    return published["id"]


def post_video(video_url: str, caption: str = "", as_reel: bool = True) -> str:
    params = {
        "video_url": video_url,
        "caption": caption,
        "media_type": "REELS" if as_reel else "VIDEO",
        "access_token": ACCESS_TOKEN,
    }
    container = _post(f"{IG_USER_ID}/media", params)
    creation_id = container["id"]

    wait_for_container(creation_id)

    published = _post(f"{IG_USER_ID}/media_publish", {
        "creation_id": creation_id,
        "access_token": ACCESS_TOKEN,
    })
    return published["id"]


def post_carousel(media_urls: list[str], is_video: list[bool], caption: str = "") -> str:
    if len(media_urls) != len(is_video):
        raise ValueError("media_urls and is_video must be the same length")
    if not (2 <= len(media_urls) <= 10):
        raise ValueError("Carousels need 2-10 items")
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

    container = _post(f"{IG_USER_ID}/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
        "access_token": ACCESS_TOKEN,
    })
    creation_id = container["id"]

    published = _post(f"{IG_USER_ID}/media_publish", {
        "creation_id": creation_id,
        "access_token": ACCESS_TOKEN,
    })
    return published["id"]


if __name__ == "__main__":
    # Example usage - replace with your own public media URLs
    media_id = post_photo(
        image_url="https://example.com/photo.jpg",
        caption="Posted via API #test",
    )
    print(f"Published media id: {media_id}")