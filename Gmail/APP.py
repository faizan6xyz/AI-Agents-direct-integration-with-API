import logging
from flask import Flask, request, jsonify, send_file
from googleapiclient.errors import HttpError
import Gmail.Read_mails as gc
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
app = Flask(__name__)
logger = logging.getLogger("gmail_api")
_service = None
limiter = Limiter( app=app, key_func=get_remote_address,default_limits=["200 per hour"])

def get_service():
    global _service
    if _service is None:
        _service = gc.get_service()
    return _service

@app.errorhandler(ValueError)
def handle_value_error(e):
    return jsonify({"error": str(e)}), 400

@app.errorhandler(FileNotFoundError)
def handle_not_found(e):
    return jsonify({"error": str(e)}), 404

@app.errorhandler(HttpError)
def handle_http_error(e):
    status = getattr(e, "status_code", None) or getattr(e.resp, "status", 500)
    return jsonify({"error": str(e)}), status

@app.route("/messages", methods=["GET"])
@limiter.limit("20 per minute")
def api_list_messages():
    query = request.args.get("query", "is:unread")
    max_results = int(request.args.get("max_results", 10))
    all_pages = request.args.get("all_pages", "false").lower() == "true"
    messages = gc.list_messages(get_service(), query=query, max_results=max_results, all_pages=all_pages, verbose=False)
    return jsonify({"count": len(messages), "messages": messages})

@app.route("/messages/send", methods=["POST"])
@limiter.limit("10 per minute")
def api_send_message():
    data = request.get_json(force=True, silent=True) or {}
    to = data.get("to")
    name = data.get("name", "")
    name = data.get("name", "")
    subject = data.get("subject", "")
    body_text = data.get("body_text", "")
    if not subject :
        return jsonify({"error": "'subject' must not be empty"}), 400
    if not to:
        return jsonify({"error": "'to' is required"}), 400
    result = gc.send_message(get_service(), to, subject, body_text),name
    return jsonify({"id": result.get("id"), "status": "sent"}), 201

@app.route("/messages/sendmultiple", methods=["POST"])
@limiter.limit("5 per minute")
def api_send_message_multiple():
    data = request.get_json(force=True, silent=True) or {}
    to = data.get("to")
    name = data.get("name", "")
    subject = data.get("subject", "")
    body_text = data.get("body_text", "")
    if not subject :
        return jsonify({"error": "'subject' must not be empty"}), 400
    if not to or not isinstance(to, list):
        return jsonify({"error": "'to' must be a non-empty list of email addresses"}), 400
    results = []
    for recipient in to:
        try:
            result = gc.send_message(get_service(), recipient, subject, body_text,name)
            results.append({"to": recipient, "status": "sent", "id": result.get("id")})
        except (ValueError, HttpError) as e:
            results.append({"to": recipient, "status": "failed", "error": str(e)})

    sent_count = sum(1 for r in results if r["status"] == "sent")
    status_code = 201 if sent_count == len(to) else 207  # 207 = partial success
    return jsonify({"results": results, "sent": sent_count, "total": len(to)}), status_code

@app.route("/messages/send-with-attachments", methods=["POST"])
@limiter.limit("5 per minute")
def api_send_message_with_attachments():
    data = request.get_json(force=True, silent=True) or {}
    to = data.get("to")
    subject = data.get("subject", "")
    name = data.get("name", "")
    body_text = data.get("body_text", "")
    name = data.get("name", "")
    file_paths = data.get("file_paths")
    allowed_dir = data.get("allowed_dir")
    if not subject :
        return jsonify({"error": "'subject' must not be empty"}), 400
    if not to:
        return jsonify({"error": "'to' is required"}), 400
    if not file_paths or not isinstance(file_paths, list):
        return jsonify({"error": "'file_paths' must be a non-empty list"}), 400
    result = gc.send_message_with_attachments(get_service(), to, subject, body_text, file_paths,name, allowed_dir=allowed_dir)
    return jsonify({"id": result.get("id"), "status": "sent"}), 201

@app.route("/messages/<message_id>/read", methods=["POST"])
@limiter.limit("10 per minute")
def api_mark_as_read(message_id):
    gc.mark_as_read(get_service(), message_id)
    return jsonify({"id": message_id, "status": "read"})

@app.route("/messages/<message_id>/unread", methods=["POST"])
@limiter.limit("10 per minute")
def api_mark_as_unread(message_id):
    gc.mark_as_unread(get_service(), message_id)
    return jsonify({"id": message_id, "status": "unread"})

@app.route("/messages/<message_id>/attachments", methods=["GET"])
@limiter.limit("10 per minute")
def api_download_attachments(message_id):
    out_dir = request.args.get("out_dir", "attachments")
    allow_executable_types = request.args.get("allow_executable_types", "false").lower() == "true"
    saved = gc.download_attachments(get_service(), message_id, out_dir=out_dir, allow_executable_types=allow_executable_types)
    return jsonify({"id": message_id, "saved_files": saved, "count": len(saved)})

@app.route("/messages/attachments/download-multiple", methods=["POST"])
@limiter.limit("5 per minute")
def api_download_attachments_multiple():
    data = request.get_json(force=True, silent=True) or {}
    message_ids = data.get("message_ids")
    out_dir = data.get("out_dir", "attachments")
    allow_executable_types = bool(data.get("allow_executable_types", False))
    if not message_ids or not isinstance(message_ids, list):
        return jsonify({"error": "'message_ids' must be a non-empty list"}), 400
    results = []
    for message_id in message_ids:
        try:
            saved = gc.download_attachments(get_service(), message_id, out_dir=out_dir, allow_executable_types=allow_executable_types,)
            results.append({"id": message_id, "status": "downloaded", "saved_files": saved, "count": len(saved), })
        except (ValueError, FileNotFoundError, HttpError) as e:
            results.append({"id": message_id, "status": "failed", "error": str(e)})
    success_count = sum(1 for r in results if r["status"] == "downloaded")
    status_code = 201 if success_count == len(message_ids) else 207  # 207 = partial success
    return jsonify({ "results": results, "downloaded": success_count, "total": len(message_ids), }), status_code

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)