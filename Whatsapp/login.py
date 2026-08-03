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
WA_APP_ID = os.getenv("WA_APP_ID")
WA_APP_SECRET = os.getenv("WA_APP_SECRET")
WA_REDIRECT_URI = os.getenv("WA_REDIRECT_URI")
GRAPH_VERSION = os.getenv("GRAPH_API_VERSION", "v20.0")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TABLE_NAME = "WhatsApp"
SCOPE = "whatsapp_business_management,whatsapp_business_messaging,business_management"
def check_user_id(uuser_id):
    exist = dbimp.select_rows(TABLE_NAME, select="id", filters={"id": uuser_id})
    if not exist:
        return False
    return True

def refresh_token(user_id, access_token):
    resp = requests.get(
        f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token",
        params={ "grant_type": "fb_exchange_token", "client_id": WA_APP_ID, "client_secret": WA_APP_SECRET, "fb_exchange_token": access_token, },).json()
    new_token = resp.get("access_token")
    seconds = resp.get("expires_in")
    if new_token and seconds:
        new_expire = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        dbimp.update_rows( TABLE_NAME, {"Access_token": new_token, "Token_expire": new_expire.isoformat()}, filters={"id": user_id}, )
        return new_token
    return access_token

@app.route("/auth/whatsapp/login")
def whatsapp_login():
    user_id = request.args.get("user_id")  # http://localhost:5000/auth/whatsapp/login?user_id=<some_id>
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    params = { "client_id": WA_APP_ID, "redirect_uri": WA_REDIRECT_URI, "scope": SCOPE, "response_type": "code", "state": user_id,}
    auth_url = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?" + urlencode(params)
    return redirect(auth_url)


@app.route("/auth/whatsapp/callback")
def whatsapp_callback():
    code = request.args.get("code")
    user_id = request.args.get("state")
    if not code:
        return jsonify({"error": "missing code"}), 400
    if not user_id:
        return jsonify({"error": "missing user id"}), 400
    if not check_user_id(user_id):
        return jsonify({"error": "invalid user id"}), 400
    token_resp = requests.get(
        f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token",
        params={ "client_id": WA_APP_ID, "client_secret": WA_APP_SECRET, "redirect_uri": WA_REDIRECT_URI, "code": code, },).json()
    short_token = token_resp.get("access_token")
    if not short_token:
        return jsonify({"error": "token exchange failed", "details": token_resp}), 400
    long_resp = requests.get(
        f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token",
        params={ "grant_type": "fb_exchange_token", "client_id": WA_APP_ID, "client_secret": WA_APP_SECRET, "fb_exchange_token": short_token, },).json()
    long_token = long_resp.get("access_token")
    seconds = long_resp.get("expires_in")
    if not long_token or not seconds:
        return jsonify({"error": "token exchange failed", "details": long_resp}), 400
    expire_time = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    debug = requests.get(f"https://graph.facebook.com/{GRAPH_VERSION}/debug_token", params={"input_token": long_token, "access_token": f"{WA_APP_ID}|{WA_APP_SECRET}"},).json()
    granular_scopes = debug.get("data", {}).get("granular_scopes", [])
    waba_ids = []
    for scope in granular_scopes:
        if scope.get("scope") == "whatsapp_business_management":
            waba_ids.extend(scope.get("target_ids", []))
    waba_id = waba_ids[0] if waba_ids else None
    phone_number_id = None
    display_number = None
    if waba_id:
        phones = requests.get( f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/phone_numbers", params={"access_token": long_token}, ).json()
        numbers = phones.get("data", [])
        if numbers:
            phone_number_id = numbers[0].get("id")
            display_number = numbers[0].get("display_phone_number")
    try:
        dbimp.update_rows(TABLE_NAME, {"Access_token": long_token, "Timestamp": datetime.now(timezone.utc).isoformat(), "Token_expire": expire_time.isoformat(), "WABA_id": waba_id,"Phone_number_id": phone_number_id, "Display_number": display_number, }, filters={"id": user_id}, )
    except Exception as e:
        return jsonify({"error": "token stored failed to save", "details": str(e)}), 500
    return jsonify({"user_id": user_id, "waba_id": waba_id, "phone_number_id": phone_number_id, "access_token": long_token,})