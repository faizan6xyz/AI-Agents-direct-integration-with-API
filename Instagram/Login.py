import database.UserDB as dbimp
import os
import requests
from urllib.parse import urlencode
from flask import Flask, request, redirect, jsonify
from supabase import create_client, Client
from datetime import datetime, timezone, timedelta
import Instagram.upload as uploadd
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
app = Flask(__name__)
IG_APP_ID = os.getenv("IG_APP_ID")
IG_APP_SECRET = os.getenv("IG_APP_SECRET")
IG_REDIRECT_URI = os.getenv("IG_REDIRECT_URI")
mail = os.environ.get("email")
passw = os.environ.get("pass")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TABLE_NAME = "Instagram"
SCOPE = "instagram_business_basic,instagram_business_content_publish,instagram_business_manage_comments,"

def check_user_id(uuser_id):
    exist = dbimp.select_rows(TABLE_NAME, select="id", filters={"id": uuser_id})
    if not exist:
        return False
    return True

def _validate_int(name: str, value) -> bool:
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return True
    
def refresh_token(user_id, access_token):
    resp = requests.get("https://graph.instagram.com/refresh_access_token",params={"grant_type": "ig_refresh_token", "access_token": access_token},).json()
    new_token = resp.get("access_token")
    seconds = resp.get("expires_in")
    if new_token and seconds:
        new_expire = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        dbimp.update_rows(TABLE_NAME, {"Access_token": new_token, "Token_expire": new_expire.isoformat()},filters={"id": user_id},)
        return new_token
    return access_token

@app.route("/auth/instagram/login") 
def instagram_login():
    user_id = request.args.get("user_id")   # takes user_id from http://localhost:5000/auth/instagram/login?user_id=<some_id>
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    params = {"client_id": IG_APP_ID, "redirect_uri": IG_REDIRECT_URI, "scope": SCOPE, "response_type": "code"}
    auth_url = "https://www.instagram.com/oauth/authorize?" + urlencode(params)
    return redirect(auth_url)

@app.route("/auth/instagram/callback")
def instagram_callback():
    code = request.args.get("code")
    user_id = request.args.get("state")
    if not code:
        return jsonify({"error": "missing code"}), 400
    if not user_id:
        return jsonify({"error": "missing user id"}), 400
    if not check_user_id(user_id):
        return jsonify({"error": "invalid user id"}), 400
    token_resp = requests.post("https://api.instagram.com/oauth/access_token",data={"client_id": IG_APP_ID, "client_secret": IG_APP_SECRET,"grant_type": "authorization_code","redirect_uri": IG_REDIRECT_URI,"code": code,},).json()
    short_token = token_resp.get("access_token")
    ig_user_id = token_resp.get("user_id")
    if not short_token:
        return jsonify({"error": "token exchange failed", "details": token_resp}), 400
    long_resp = requests.get("https://graph.instagram.com/access_token",params={"grant_type": "ig_exchange_token", "client_secret": IG_APP_SECRET, "access_token": short_token, },).json()
    long_token = long_resp.get("access_token")
    seconds = long_resp.get("expires_in")
    if not long_token or not seconds:
        return jsonify({"error": "token exchange failed", "details": long_resp}), 400
    expire_time = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    about = requests.get( "https://graph.instagram.com/me", params={"fields": "id,username,account_type,media_count", "access_token": long_token}).json()
    account = about.get("username")
    account_id = about.get("id")
    try:
        dbimp.update_rows( TABLE_NAME, { "Access_token": long_token, "Timestamp": datetime.now(timezone.utc).isoformat(), "Token_expire": expire_time.isoformat(), "Username" : account , "Account_id": account_id},filters={"id": user_id},)
    except Exception as e:
        return jsonify({"error": "token stored failed to save", "details": str(e)}), 500
    return jsonify({"user_id": ig_user_id, "access_token": long_token})

@app.route("/instagram/posts/<account_id>")
def get_instagram_posts(account_id):
    user_id = request.args.get("user_id")
    x = check_user_id(user_id)
    if not x :
        return " Invalid user id " 
    rows = dbimp.select_rows(TABLE_NAME, select="Access_token,Token_expire" , filters={"id": user_id , "Account_id" : account_id})
    if not rows:
        return jsonify({"error": "no instagram account linked"}), 404
    row = rows[0]
    access_token = row["Access_token"]
    Token_expiry = row["Token_expire"]
    if not access_token or not Token_expiry:
        return jsonify({"error": "missing access_token"}), 400
    Token_expiry = datetime.fromisoformat(Token_expiry)
    if Token_expiry - datetime.now(timezone.utc) < timedelta(days=2):
        access_token = refresh_token(user_id, access_token)
    fields = "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count"
    url = "https://graph.instagram.com/me/media"
    params = {"fields": fields, "access_token": access_token}
    posts = []
    while url:
        resp = requests.get(url, params=params).json()
        if "error" in resp:
            return jsonify(resp), 400
        posts.extend(resp.get("data", []))
        url = resp.get("paging", {}).get("next")
        params = None
    return jsonify({"count": len(posts), "posts": posts})

@app.route("/instagram/comments/<account_id>/<media_id>")
def get_instagram_comments(account_id, media_id):
    user_id = request.args.get("user_id")
    x = check_user_id(user_id)
    if not x :
        return " Invalid user id " 
    rows = dbimp.select_rows(TABLE_NAME, select="Access_token,Token_expire", filters={"id": user_id, "Account_id": account_id})
    if not rows:
        return jsonify({"error": "no instagram account linked"}), 404
    row = rows[0]
    access_token = row["Access_token"]
    Token_expiry = row["Token_expire"]
    if not access_token or not Token_expiry:
        return jsonify({"error": "missing access_token"}), 400
    Token_expiry = datetime.fromisoformat(Token_expiry)
    if Token_expiry.tzinfo is None:
        Token_expiry = Token_expiry.replace(tzinfo=timezone.utc)
    if Token_expiry - datetime.now(timezone.utc) < timedelta(days=2):
        access_token = refresh_token(user_id, access_token)
    fields = "id,text,username,timestamp,like_count"
    url = f"https://graph.instagram.com/{media_id}/comments"
    params = {"fields": fields, "access_token": access_token}
    comments = []
    while url:
        resp = requests.get(url, params=params).json()
        if "error" in resp:
            return jsonify(resp), 400
        comments.extend(resp.get("data", []))
        url = resp.get("paging", {}).get("next")
        params = None
    return jsonify({"count": len(comments), "comments": comments})

def _coerce_int(name: str, value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

@app.route("/instagram/upload/<account_id>/story", methods=["POST"])
def story(account_id):
    user_id = request.args.get("user_id")
    x = check_user_id(user_id)
    if not x:
        return " Invalid user id "
    rows = dbimp.select_rows(TABLE_NAME, select="Access_token,Token_expire", filters={"id": user_id, "Account_id": account_id})
    if not rows:
        return jsonify({"error": "no instagram account linked"}), 404
    row = rows[0]
    access_token = row["Access_token"]
    Token_expiry = row["Token_expire"]
    if not access_token or not Token_expiry:
        return jsonify({"error": "missing access_token"}), 400
    Token_expiry = datetime.fromisoformat(Token_expiry)
    if Token_expiry.tzinfo is None:
        Token_expiry = Token_expiry.replace(tzinfo=timezone.utc)
    if Token_expiry - datetime.now(timezone.utc) < timedelta(days=2):
        access_token = refresh_token(user_id, access_token)
    media_url = request.args.get("media_url")
    is_video = request.args.get("is_video")
    media_size = request.args.get("media_size")
    publish = request.args.get("publish")
    duration = request.args.get("duration")
    if not media_url or not media_size:
        return jsonify({"error": "url and media size is required"}), 400
    media_size = _coerce_int("media_size", media_size)
    duration = _coerce_int("duration", duration)
    if media_size is None or duration is None:
        return jsonify({"success": False, "message": "Unable to post story. due to duration / media size int value"}), 400
    try:
        _validate_int("media_size", media_size)
        _validate_int("duration", duration)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    video_type = str(is_video).strip().lower() == "true"
    publish_now = str(publish).strip().lower() == "true"
    try:
        id_post = uploadd.post_story( access_token=access_token, ig_user_id=account_id, media_size=media_size, media_url=media_url, publish=publish_now, is_video=video_type, media_duration=duration, )
    except Exception as e:
        return jsonify({"success": False, "message": f"Unable to post story: {e}"}), 500
    if id_post:
        return jsonify({"success": True, "media_id": id_post}), 200
    else:
        return jsonify({"success": False, "message": "Unable to post story."}), 500

@app.route("/instagram/upload/<account_id>/photo", methods=["POST"])
def photo(account_id):
    user_id = request.args.get("user_id")
    x = check_user_id(user_id)
    if not x:
        return " Invalid user id "
    rows = dbimp.select_rows(TABLE_NAME, select="Access_token,Token_expire", filters={"id": user_id, "Account_id": account_id})
    if not rows:
        return jsonify({"error": "no instagram account linked"}), 404
    row = rows[0]
    access_token = row["Access_token"]
    Token_expiry = row["Token_expire"]
    if not access_token or not Token_expiry:
        return jsonify({"error": "missing access_token"}), 400
    Token_expiry = datetime.fromisoformat(Token_expiry)
    if Token_expiry.tzinfo is None:
        Token_expiry = Token_expiry.replace(tzinfo=timezone.utc)
    if Token_expiry - datetime.now(timezone.utc) < timedelta(days=2):
        access_token = refresh_token(user_id, access_token)
    media_url = request.args.get("media_url")
    media_size = request.args.get("media_size")
    publish = request.args.get("publish")
    caption = request.args.get("caption", "")
    if not media_url or not media_size:
        return jsonify({"error": "url and media size is required"}), 400
    media_size = _coerce_int("media_size", media_size)
    if media_size is None:
        return jsonify({"success": False, "message": "Unable to post photo. due media size int value"}), 400
    try:
        _validate_int("media_size", media_size)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    publish_now = str(publish).strip().lower() == "true"
    try:
        id_post = uploadd.post_photo( access_token=access_token, ig_user_id=account_id, image_url=media_url, caption=caption, media_size=media_size, publish=publish_now,)
    except Exception as e:
        return jsonify({"success": False, "message": f"Unable to post photo: {e}"}), 500
    if id_post:
        return jsonify({"success": True, "media_id": id_post}), 200
    else:
        return jsonify({"success": False, "message": "Unable to post photo."}), 500

@app.route("/instagram/upload/<account_id>/video", methods=["POST"])
def video(account_id):
    user_id = request.args.get("user_id")
    x = check_user_id(user_id)
    if not x:
        return " Invalid user id "
    rows = dbimp.select_rows(TABLE_NAME, select="Access_token,Token_expire", filters={"id": user_id, "Account_id": account_id})
    if not rows:
        return jsonify({"error": "no instagram account linked"}), 404
    row = rows[0]
    access_token = row["Access_token"]
    Token_expiry = row["Token_expire"]
    if not access_token or not Token_expiry:
        return jsonify({"error": "missing access_token"}), 400
    Token_expiry = datetime.fromisoformat(Token_expiry)
    if Token_expiry.tzinfo is None:
        Token_expiry = Token_expiry.replace(tzinfo=timezone.utc)
    if Token_expiry - datetime.now(timezone.utc) < timedelta(days=2):
        access_token = refresh_token(user_id, access_token)
    media_url = request.args.get("media_url")
    cover_url = request.args.get("cover_url")  # optional now, only valid for reels
    media_size = request.args.get("media_size")
    publish = request.args.get("publish")
    caption = request.args.get("caption", "")
    as_reel = request.args.get("as_reel")
    height = request.args.get("height")
    width = request.args.get("width")
    duration = request.args.get("duration")
    if not media_url or not media_size:
        return jsonify({"error": "url and media size is required"}), 400
    media_size = _coerce_int("media_size", media_size)
    duration = _coerce_int("duration", duration)
    width = _coerce_int("width", width)
    height = _coerce_int("height", height)
    if None in (media_size, duration, width, height):
        return jsonify({"success": False, "message": "Unable to post video. due to media size / duration / width / height is not int"}), 400
    try:
        _validate_int("media_size", media_size)
        _validate_int("duration", duration)
        _validate_int("width", width)
        _validate_int("height", height)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    publish_now = str(publish).strip().lower() == "true"
    as_reeel = str(as_reel).strip().lower() == "true"
    if cover_url and not as_reeel:
        return jsonify({"success": False, "message": "cover_url is only supported when as_reel is true"}), 400
    try:
        id_post = uploadd.post_video( access_token=access_token, ig_user_id=account_id, video_url=media_url, media_size=media_size, caption=caption, publish=publish_now, cover_url=cover_url if as_reeel else None, as_reel=as_reeel, media_duration=duration, width=width, height=height,)
    except Exception as e:
        return jsonify({"success": False, "message": f"Unable to post video: {e}"}), 500
    if id_post:
        return jsonify({"success": True, "media_id": id_post}), 200
    else:
        return jsonify({"success": False, "message": "Unable to post video."}), 500
 
@app.route("/instagram/upload/<account_id>/carousel", methods=["POST"])
def carousel(account_id):
    user_id = request.args.get("user_id")
    x = check_user_id(user_id)
    if not x:
        return " Invalid user id "
    rows = dbimp.select_rows(TABLE_NAME, select="Access_token,Token_expire", filters={"id": user_id, "Account_id": account_id})
    if not rows:
        return jsonify({"error": "no instagram account linked"}), 404
    row = rows[0]
    access_token = row["Access_token"]
    Token_expiry = row["Token_expire"]
    if not access_token or not Token_expiry:
        return jsonify({"error": "missing access_token"}), 400
    Token_expiry = datetime.fromisoformat(Token_expiry)
    if Token_expiry.tzinfo is None:
        Token_expiry = Token_expiry.replace(tzinfo=timezone.utc)
    if Token_expiry - datetime.now(timezone.utc) < timedelta(days=2):
        access_token = refresh_token(user_id, access_token)
    publish = request.args.get("publish")
    caption = request.args.get("caption", "")
    media_size = request.args.getlist("media_size")
    media_duration = request.args.getlist("media_duration")
    media_urls = request.args.getlist("media_urls")
    is_video = request.args.getlist("is_video")
    if not media_urls or not is_video or not media_size or not media_duration:
        return jsonify({"success": False, "message": "media_urls, is_video, media_size, and media_duration are all required"}), 400
    if not (len(media_urls) == len(is_video) == len(media_size) == len(media_duration)):
        return jsonify({"success": False, "message": "media_urls, is_video, media_size, and media_duration must all be the same length"}), 400
    is_videoo = [str(p).strip().lower() == "true" for p in is_video]
    media_sizee = [_coerce_int(f"media_size[{i}]", p) for i, p in enumerate(media_size)]
    if any(v is None for v in media_sizee):
        return jsonify({"success": False, "message": "one or more media_size values are not valid ints"}), 400
    media_durationn = [_coerce_int(f"media_duration[{i}]", p) for i, p in enumerate(media_duration)]
    if any(v is None for v in media_durationn):
        return jsonify({"success": False, "message": "one or more media_duration values are not valid ints"}), 400
    publish_now = str(publish).strip().lower() == "true"
    try:
        id_post = uploadd.post_carousel( access_token=access_token, ig_user_id=account_id, is_video=is_videoo, media_size=media_sizee, media_duration=media_durationn, media_urls=media_urls, publish=publish_now, caption=caption, )
    except Exception as e:
        return jsonify({"success": False, "message": f"Unable to post carousel: {e}"}), 500
    if id_post:
        return jsonify({"success": True, "media_id": id_post}), 200
    else:
        return jsonify({"success": False, "message": "Unable to post carousel."}), 500
    
@app.route("/instagram/insight/<account_id>/<media_id>", methods=["POST"])
def carousel(account_id , media_id):
    user_id = request.args.get("user_id")
    x = check_user_id(user_id)
    if not x:
        return " Invalid user id "
    rows = dbimp.select_rows(TABLE_NAME, select="Access_token,Token_expire", filters={"id": user_id, "Account_id": account_id})
    if not rows:
        return jsonify({"error": "no instagram account linked"}), 404
    row = rows[0]
    access_token = row["Access_token"]
    Token_expiry = row["Token_expire"]
    if not access_token or not Token_expiry:
        return jsonify({"error": "missing access_token"}), 400
    Token_expiry = datetime.fromisoformat(Token_expiry)
    if Token_expiry.tzinfo is None:
        Token_expiry = Token_expiry.replace(tzinfo=timezone.utc)
    if Token_expiry - datetime.now(timezone.utc) < timedelta(days=2):
        access_token = refresh_token(user_id, access_token)
    try :
        data = uploadd.get_media_insights(access_token=access_token , media_id=media_id )
    except Exception as e:
        return jsonify({"success": False, "message": f"Unable to fetch insight {e}"}), 500
    if data :
        return jsonify({"success": True , "data" : data})
    else :
        return jsonify({"success": False, "message": f"Unable to fetch insight {e}"}), 500

    
    
if __name__ == "__main__":
    app.run(port=5000, debug=True)