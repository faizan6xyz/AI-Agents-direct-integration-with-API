from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
import requests
from flask import Flask, request, redirect, jsonify
from Whatsapp.new import ( WA_APP_ID, WA_REDIRECT_URI, GRAPH_VERSION, SCOPE, APP_SECRET, VERIFY_TOKEN, TABLE_NAME, VALID_MEDIA_TYPES, log,  InvalidPhoneNumberError, MessageTooLongError, FileTooLargeError, is_valid_signature, require_api_key, ensure_csv_exists, ensure_excel_exists, process_single_message, get_user_for_phone_number_id, check_user_id, refresh_token, send_whatsapp_message, send_whatsapp_media, send_whatsapp_location, send_whatsapp_reply_buttons, send_whatsapp_list, )
import database.UserDB as dbimp
import authnew as au
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

@app.route("/auth/whatsapp/login")
def whatsapp_login():
    token = request.args.get("token")
    tokench = au.process(token=token)
    if not tokench["status"] :
        return jsonify({"status": "failed" , "reason": tokench["reason"]})
    user_id = tokench['user_id']
  # /auth/whatsapp/login?user_id=<some_id>
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    params = {"client_id": WA_APP_ID,"redirect_uri": WA_REDIRECT_URI,"scope": SCOPE,"response_type": "code","state": user_id,}
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
    token_resp = requests.get(f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token", params={"client_id": WA_APP_ID,"client_secret": APP_SECRET,"redirect_uri": WA_REDIRECT_URI,"code": code,},).json()
    short_token = token_resp.get("access_token")
    if not short_token:
        return jsonify({"error": "token exchange failed", "details": token_resp}), 400
    long_resp = requests.get(f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token", params={"grant_type": "fb_exchange_token","client_id": WA_APP_ID,"client_secret": APP_SECRET,"fb_exchange_token": short_token,},).json()
    long_token = long_resp.get("access_token")
    seconds = long_resp.get("expires_in")
    if not long_token or not seconds:
        return jsonify({"error": "token exchange failed", "details": long_resp}), 400
    expire_time = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    debug = requests.get(f"https://graph.facebook.com/{GRAPH_VERSION}/debug_token",params={"input_token": long_token, "access_token": f"{WA_APP_ID}|{APP_SECRET}"}, ).json()
    granular_scopes = debug.get("data", {}).get("granular_scopes", [])
    waba_ids = []
    for scope in granular_scopes:
        if scope.get("scope") == "whatsapp_business_management":
            waba_ids.extend(scope.get("target_ids", []))
    waba_id = waba_ids[0] if waba_ids else None
    phone_number_id = None
    display_number = None
    if waba_id:
        phones = requests.get( f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/phone_numbers", params={"access_token": long_token},).json()
        numbers = phones.get("data", [])
        if numbers:
            phone_number_id = numbers[0].get("id")
            display_number = numbers[0].get("display_phone_number")
    try:
        dbimp.update_rows( TABLE_NAME,{"Access_token": long_token,"Timestamp": datetime.now(timezone.utc).isoformat(),"Token_expire": expire_time.isoformat(),"Bussiness_id": waba_id,"Account_id": phone_number_id,"Phone_no": display_number,},filters={"id": user_id},)
    except Exception as e:
        return jsonify({"error": "token stored failed to save", "details": str(e)}), 500
    return jsonify({"user_id": user_id,"waba_id": waba_id,"phone_number_id": phone_number_id,"access_token": long_token,})

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    log.warning("Webhook verification attempt failed (bad mode/verify token).")
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def receive_webhook_message():
    if not is_valid_signature(request):
        log.error("Rejected webhook POST: invalid or missing signature.")
        return jsonify({"status": "invalid signature"}), 403
    data = request.get_json(silent=True) or {}
    try:
        entries = data.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                incoming_id = value.get("metadata", {}).get("phone_number_id")
                user_row = get_user_for_phone_number_id(incoming_id)
                if not user_row:
                    log.warning(f"Rejected webhook payload: unrecognized phone_number_id ({incoming_id!r}).")
                    continue
                messages = value.get("messages", [])
                for msg in messages:
                    try:
                        process_single_message(msg)
                    except Exception as e:
                        log.exception(f"Failed to process message {msg.get('id')}: {e}")
    except Exception as e:
        log.exception(f"Error processing webhook payload: {e}")
    return jsonify({"status": "received", "data" : data}), 200

@app.route("/send-test", methods=["POST"])
def test_send():
    auth_error = require_api_key()
    if auth_error:
        return auth_error
    token = request.args.get("token")
    tokench = au.process(token=token)
    if not tokench["status"] :
        return jsonify({"status": "failed" , "reason": tokench["reason"]})
    user_id = tokench['user_id']

    account_id = request.args.get("account_id")
    if not user_id or not account_id:
        return jsonify({"error": "'user_id' and 'account_id' are required"}), 400
    phone_number_raw = request.args.get("phone_number")
    if not phone_number_raw:
        return jsonify({"error": "'phone_number' query param is required"}), 400
    try:
        phoneno = int(phone_number_raw)
    except ValueError:
        return jsonify({"error": "'phone_number' must be numeric"}), 400
    rows = dbimp.select_rows(TABLE_NAME, select="Access_token,Token_expire", filters={"id": user_id, "Account_id": account_id},)
    if not rows:
        return jsonify({"error": "no whatsapp account linked"}), 404
    row = rows[0]
    access_token = row["Access_token"]
    token_expiry = row["Token_expire"]
    if not access_token or not token_expiry:
        return jsonify({"error": "missing access_token"}), 400
    token_expiry = datetime.fromisoformat(token_expiry)
    if token_expiry.tzinfo is None:
        token_expiry = token_expiry.replace(tzinfo=timezone.utc)
    if token_expiry - datetime.now(timezone.utc) < timedelta(days=2):
        access_token = refresh_token(user_id, access_token)
    data = request.get_json(silent=True)
    if not data or "phone" not in data:
        return jsonify({"error": "Please provide at least 'phone'"}), 400
    phone = data["phone"]
    msg_type = data.get("type", "text")
    try:
        if msg_type == "text":
            if "msg" not in data:
                return jsonify({"error": "'msg' is required for type 'text'"}), 400
            result = send_whatsapp_message(phoneno, access_token, phone, data["msg"])
        elif msg_type in VALID_MEDIA_TYPES:
            if "link" not in data:
                return jsonify({"error": f"'link' is required for type '{msg_type}'"}), 400
            result = send_whatsapp_media( phoneno, access_token, phone, msg_type, link=data["link"], caption=data.get("caption"), filename=data.get("filename"), )
        elif msg_type == "location":
            if "latitude" not in data or "longitude" not in data:
                return jsonify({"error": "'latitude' and 'longitude' are required"}), 400
            result = send_whatsapp_location(phoneno, access_token, phone, data["latitude"], data["longitude"],name=data.get("name"), address=data.get("address"),)
        elif msg_type == "button":
            if "body" not in data or "buttons" not in data:
                return jsonify({"error": "'body' and 'buttons' are required"}), 400
            result = send_whatsapp_reply_buttons(phoneno, access_token, phone, data["body"], data["buttons"])
        elif msg_type == "list":
            if "body" not in data or "button_text" not in data or "sections" not in data:
                return jsonify({"error": "'body', 'button_text', and 'sections' are required"}), 400
            result = send_whatsapp_list(phoneno, access_token, phone, data["body"], data["button_text"], data["sections"])
        else:
            return jsonify({"error": f"Unsupported type '{msg_type}'"}), 400
        return jsonify({"status": "sent", "details": result}), 200
    except InvalidPhoneNumberError as e:
        return jsonify({"error": str(e)}), 400
    except MessageTooLongError as e:
        return jsonify({"error": str(e)}), 400
    except FileTooLargeError as e:
        return jsonify({"error": str(e)}), 413
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except requests.RequestException as e:
        log.error(f"Send failed after retries: {e}")
        return jsonify({"error": "Failed to send message after retries"}), 502
    except Exception as e:
        log.exception(f"Unexpected error in /send-test: {e}")
        return jsonify({"error": "Internal error"}), 500

if __name__ == "__main__":
    ensure_csv_exists()
    ensure_excel_exists()
    # debug=False in production — the Werkzeug debugger is an RCE risk if exposed.
    app.run(host="0.0.0.0", port=5000, debug=False)