import re
import database.UserDB as dbimp
import authnew as au
import Instagram.Login as inn
import Drive.dep as dpp
import Whatsapp.login as what
import Gmail.Read_mails as gc
from flask import Flask,request , jsonify 
from datetime import datetime , timezone , timedelta
import os
import logging
app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gmail_api")

@app.route('/campaign', methods=['POST'])
# @limiter.limit("5 per minute")
# @require_api_key
def campaign():
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"status": False}), 403
    token = data.get("token")
    platform = data.get("platofrm")
    campaign_id = data.get("campain_id")
    campaign_name = data.get("campain_name")
    target = data.get("target")
    body = data.get("body")
    names = data.get("name")
    if not token:
        return jsonify({"error": "'token' is required"}), 400
    if not isinstance(platform, str) or platform.strip().lower() not in ("gmail", "whatsapp"):
        return jsonify({"error": "'platform' must be 'gmail' or 'whatsapp'"}), 400
    platform = platform.strip().lower()
    if not isinstance(target, list) or not target:
        return jsonify({"error": "'target' must be a non-empty list"}), 400
    if not isinstance(names, list) or not names:
        return jsonify({"error": "'name' must be a non-empty list"}), 400
    if len(target) != len(names):
        return jsonify({"error": "'target' and 'name' must be the same length"}), 400
    MAX_TARGETS = 2000
    if len(target) > MAX_TARGETS:
        return jsonify({"error": f"'target' exceeds max of {MAX_TARGETS}"}), 400
    if not isinstance(body, str) or not body.strip():
        return jsonify({"error": "'body' is required"}), 400
    if platform == "whatsapp":
        WA_ID_RE = re.compile(r'^\d{10,15}$')
        invalid = [t for t in target if not isinstance(t, str) or not WA_ID_RE.match(t)]
        if invalid:
            return jsonify({"error": "invalid entries in 'target'", "invalid": invalid[:10]}), 400
    elif platform == "gmail":
        EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
        invalid = [t for t in target if not isinstance(t, str) or not EMAIL_RE.match(t)]
        if invalid:
            return jsonify({"error": "invalid entries in 'target'", "invalid": invalid[:10]}), 400
    tokench = au.process(token=token)
    if not tokench["status"]:
        return jsonify({"status": "failed", "reason": tokench["reason"]}), 403
    user_id = tokench["user_id"]
    if not user_id:
        return jsonify({"status": False}), 403
    db_rows = dbimp.select_rows(token, "users", select="user_id", filters={"id": user_id})
    db_row = db_rows[0] if db_rows else None
    if not db_row or db_row.get("user_id") != user_id:
        return jsonify({"status": False}), 403
    results = []
    if platform == "gmail":
        try:
            service = gc.get_service(token=token, user_id=user_id)
        except Exception:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        if not service:
            return jsonify({"error": "not connected", "connect_url": "/connect-gmail"}), 401
        for recipient, recipient_name in zip(target, names):
            now = datetime.now(timezone.utc).isoformat()
            # email,campaign_id,campaign_name,send_time,receive_time,interest
            content = f"{recipient},{campaign_id},{campaign_name},{now},,"
            try:
                dpp.append_to_file(token=token, platform=platform, filename="campaigns.txt", data_to_append=content)
                gc.send_message(service=service, to=recipient, subject=campaign_name or "", body_text=body, name=recipient_name)
                results.append({"to": recipient, "status": "sent"})
            except Exception as e:
                logger.exception("campaign send failed for %s", recipient)
                results.append({"to": recipient, "status": "failed", "error": str(e)})
    elif platform == "whatsapp":
        rows = dbimp.select_rows(token, "Whatsapp", select="Access_token,Account_id,Token_expire", filters={"id": user_id})
        row = rows[0] if rows else None
        if not row:
            return jsonify({"error": "not connected", "connect_url": "/connect-whatsapp"}), 401
        account_id = row["Account_id"]
        acc = row["Access_token"]
        expire = row["Token_expire"]
        try:
            token_expiry = datetime.fromisoformat(expire)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid stored token expiry"}), 500
        if token_expiry - datetime.now(timezone.utc) < timedelta(days=2):
            refreshed = what.refresh_token(tokench["token"], user_id, acc)
            if not refreshed:
                return jsonify({"error": "token refresh failed, please reconnect WhatsApp"}), 502
            acc = refreshed  # use the refreshed token going forward
        for recipient, recipient_name in zip(target, names):
            now = datetime.now(timezone.utc).isoformat()
            # phone_no,campaign_id,campaign_name,send_time,receive_time,interest
            content = f"{recipient},{campaign_id},{campaign_name},{now},,"
            try:
                dpp.append_to_file(token=token, platform=platform, filename="campaigns.txt", data_to_append=content)
                what.send_whatsapp_message(PHONE_NUMBER_ID=account_id, ACCESS_TOKEN=acc, recipient_number=recipient, message_body=body)
                results.append({"to": recipient, "status": "sent"})
            except Exception as e:
                logger.exception("campaign send failed for %s", recipient)
                results.append({"to": recipient, "status": "failed", "error": str(e)})
    return jsonify({"count": len(results), "results": results})