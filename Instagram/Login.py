import os
import requests
from urllib.parse import urlencode
from flask import Flask, request, redirect, jsonify
from supabase import create_client, Client
import database.UserDB as dbimp
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
if res : 
    user_id = res.user.id
SCOPE = "instagram_business_basic,instagram_business_content_publish"
@app.route("/auth/instagram/login")
def instagram_login():
    params = {
        "client_id": IG_APP_ID,
        "redirect_uri": IG_REDIRECT_URI,
        "scope": SCOPE,
        "response_type": "code",
    }
    auth_url = "https://www.instagram.com/oauth/authorize?" + urlencode(params)
    return redirect(auth_url)

@app.route("/auth/instagram/callback")
def instagram_callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "missing code"}), 400
    token_resp = requests.post(
        "https://api.instagram.com/oauth/access_token",
        data={"client_id": IG_APP_ID,
            "client_secret": IG_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": IG_REDIRECT_URI,
            "code": code, },).json()
    short_token = token_resp.get("access_token")
    user_id = token_resp.get("user_id")
    if not short_token:
        return jsonify({"error": "token exchange failed", "details": token_resp}), 400
    long_resp = requests.get(
        "https://graph.instagram.com/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": IG_APP_SECRET,
            "access_token": short_token,
        },).json()
    long_token = long_resp.get("access_token")
    dbimp()
    return jsonify({"user_id": user_id, "access_token": long_token})

@app.route("/instagram/posts")
def get_instagram_posts():
    access_token = request.args.get("access_token")
    if not access_token:
        return jsonify({"error": "missing access_token"}), 400
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
        params = None  # 'next' url already contains all query params
    return jsonify({"count": len(posts), "posts": posts})


if __name__ == "__main__":
    app.run(port=5000, debug=True)