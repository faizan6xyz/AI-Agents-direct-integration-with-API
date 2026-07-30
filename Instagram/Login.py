import database.UserDB as dbimp
import os
import requests
from urllib.parse import urlencode
from flask import Flask, request, redirect, jsonify
from supabase import create_client, Client
from datetime import datetime, timezone, timedelta
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
try:
    res = supabase.auth.sign_in_with_password({"email": mail, "password": passw})
except Exception:
    res = supabase.auth.sign_up({"email": mail, "password": passw})
user_id = res.user.id if res else None
if user_id:
    exist = dbimp.select_rows(TABLE_NAME, select="id", filters={"id": user_id})
    if not exist:
        dbimp.insert_rows(TABLE_NAME, {"id": user_id})
SCOPE = "instagram_business_basic,instagram_business_content_publish"

def refresh_token(user_id, access_token, token_expire):
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
    params = {"client_id": IG_APP_ID, "redirect_uri": IG_REDIRECT_URI, "scope": SCOPE, "response_type": "code"}
    auth_url = "https://www.instagram.com/oauth/authorize?" + urlencode(params)
    return redirect(auth_url)

@app.route("/auth/instagram/callback")
def instagram_callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "missing code"}), 400
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

@app.route("/instagram/posts")
def get_instagram_posts():
    row = dbimp.select_rows(TABLE_NAME, select={"Access_token", "Token_expire"}, filters={"id": user_id})[0]
    access_token = row["Access_token"]
    Token_expiry = row["Token_expire"]
    if not access_token:
        return jsonify({"error": "missing access_token"}), 400
    if Token_expiry - datetime.now(timezone.utc) < timedelta(days=2):
        refresh_token(user_id , access_token,Token_expiry)
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

if __name__ == "__main__":
    app.run(port=5000, debug=True)