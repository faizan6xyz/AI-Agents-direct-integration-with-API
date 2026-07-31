import os
import requests
from flask import Blueprint, request, redirect, jsonify

instagram_auth = Blueprint("instagram_auth", __name__)

IG_APP_ID = os.getenv("IG_APP_ID")
IG_APP_SECRET = os.getenv("IG_APP_SECRET")
IG_REDIRECT_URI = os.getenv("IG_REDIRECT_URI")

SCOPES = "instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments"


@instagram_auth.route("/instagram/login")
def instagram_login():
    auth_url = (
        "https://www.instagram.com/oauth/authorize"
        f"?client_id={IG_APP_ID}"
        f"&redirect_uri={IG_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPES}"
    )
    return redirect(auth_url)


@instagram_auth.route("/instagram/callback")
def instagram_callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "missing code"}), 400

    code = code.split("#")[0]

    token_res = requests.post(
        "https://api.instagram.com/oauth/access_token",
        data={
            "client_id": IG_APP_ID,
            "client_secret": IG_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": IG_REDIRECT_URI,
            "code": code,
        },
    )
    token_data = token_res.json()

    if "access_token" not in token_data:
        return jsonify({"error": "token exchange failed", "details": token_data}), 400

    short_lived_token = token_data["access_token"]
    ig_user_id = token_data["user_id"]

    long_res = requests.get(
        "https://graph.instagram.com/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": IG_APP_SECRET,
            "access_token": short_lived_token,
        },
    )
    long_data = long_res.json()

    if "access_token" not in long_data:
        return jsonify({"error": "long-lived exchange failed", "details": long_data}), 400

    long_lived_token = long_data["access_token"]
    expires_in = long_data["expires_in"]

    # store long_lived_token, expires_in, ig_user_id in your encrypted token store here

    return jsonify({
        "ig_user_id": ig_user_id,
        "access_token": long_lived_token,
        "expires_in": expires_in,
    })


def debug_token(token):
    res = requests.get(
        "https://graph.instagram.com/v23.0/debug_token",
        params={"input_token": token, "access_token": token},
    )
    return res.json()


def get_comments(media_id, token):
    res = requests.get(
        f"https://graph.instagram.com/v23.0/{media_id}/comments",
        params={"fields": "id,text,username,timestamp,like_count", "access_token": token},
    )
    return res.json()