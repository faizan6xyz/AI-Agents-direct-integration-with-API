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
    is_video = request.args.get("is_video")  # fixed: args (not arg), is_video (not is_vedio)
    if not media_url:
        return jsonify({"error": "url is required"}), 400
    video_type = str(is_video).strip().lower() == "true"
    id_post = uploadd.post_story(access_token, account_id, media_url, video_type)
    if id_post:
        return jsonify({"success": True, "media_id": id_post}), 200
    else:
        return jsonify({"success": False, "message": "Unable to post story."}), 500
    
    
    
    
    
    
    
if __name__ == "__main__":
    app.run(port=5000, debug=True)