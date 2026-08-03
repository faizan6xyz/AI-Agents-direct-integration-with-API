import os
from flask import Flask, request, jsonify
import Gmail.Read_mails as gc  # rename to match your actual module filename
app = Flask(__name__)

@app.route('/messages', methods=['GET'])
def list_messages():
    user_id = request.args.get("user_id")
    query = request.args.get('q', 'is:unread')
    max_results = int(request.args.get('max_results', 10))
    all_pages = request.args.get('all_pages', 'false').lower() == 'true'
    try:
        service = gc.get_service(user_id=user_id)
        messages = gc.list_messages(service, query=query, max_results=max_results, all_pages=all_pages, verbose=False)
        return jsonify({"count": len(messages), "messages": messages})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/messages/send', methods=['POST'])
def send_message():
    user_id = request.args.get("user_id")
    data = request.get_json(force=True) or {}
    to = data.get('to')
    subject = data.get('subject', '')
    body_text = data.get('body_text', '')
    name = data.get('name', '')
    if not to:
        return jsonify({"error": "'to' is required."}), 400
    try:
        service = gc.get_service(user_id=user_id)
        result = gc.send_message(service, to, subject, body_text, name)
        return jsonify({"id": result.get('id'), "threadId": result.get('threadId')})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/messages/send-with-attachments', methods=['POST'])
def send_message_with_attachments():
    user_id = request.args.get("user_id")
    to = request.form.get('to')
    subject = request.form.get('subject', '')
    body_text = request.form.get('body_text', '')
    name = request.form.get('name', '')
    if not to:
        return jsonify({"error": "'to' is required."}), 400
    files = request.files.getlist('attachments')
    if not files:
        return jsonify({"error": "At least one attachment is required."}), 400
    upload_dir = os.path.join('uploads', 'tmp')
    os.makedirs(upload_dir, exist_ok=True)
    saved_paths = []
    try:
        for f in files:
            path = os.path.join(upload_dir, f.filename)
            f.save(path)
            saved_paths.append(path)
        service = gc.get_service(user_id=user_id)
        result = gc.send_message_with_attachments( service, to, subject, body_text, saved_paths, name=name, allowed_dir=upload_dir )
        return jsonify({"id": result.get('id'), "threadId": result.get('threadId')})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        for p in saved_paths:
            if os.path.exists(p):
                os.remove(p)

@app.route('/messages/<message_id>/read', methods=['POST'])
def mark_as_read(message_id):
    user_id = request.args.get("user_id")
    try:
        service = gc.get_service(user_id=user_id)
        result = gc.mark_as_read(service, message_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/messages/<message_id>/unread', methods=['POST'])
def mark_as_unread(message_id):
    user_id = request.args.get("user_id")
    try:
        service = gc.get_service(user_id=user_id)
        result = gc.mark_as_unread(service, message_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/messages/<message_id>/attachments', methods=['GET'])
def download_attachments(message_id):
    user_id = request.args.get("user_id")
    out_dir = request.args.get('out_dir', os.path.join('attachments', message_id))
    try:
        service = gc.get_service(user_id=user_id)
        saved = gc.download_attachments(service, message_id, out_dir=out_dir)
        return jsonify({"saved_files": saved})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/filters', methods=['GET'])
def list_filters():
    user_id = request.args.get("user_id")
    try:
        service = gc.get_service(user_id=user_id)
        return jsonify(gc.list_filters(service))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/filters', methods=['POST'])
def create_filter():
    user_id = request.args.get("user_id")
    data = request.get_json(force=True) or {}
    criteria = data.get('criteria')
    action = data.get('action')
    if not criteria or not action:
        return jsonify({"error": "'criteria' and 'action' are required."}), 400
    try:
        service = gc.get_service(user_id=user_id)
        result = gc.create_filter(service, criteria, action)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/filters/<filter_id>', methods=['DELETE'])
def delete_filter(filter_id):
    user_id = request.args.get("user_id")
    try:
        service = gc.get_service(user_id=user_id)
        gc.delete_filter(service, filter_id)
        return jsonify({"deleted": filter_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/labels', methods=['GET'])
def list_labels():
    user_id = request.args.get("user_id")
    try:
        service = gc.get_service(user_id=user_id)
        return jsonify(gc.list_labels(service))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/labels', methods=['POST'])
def create_label():
    user_id = request.args.get("user_id")
    data = request.get_json(force=True) or {}
    name = data.get('name')
    if not name:
        return jsonify({"error": "'name' is required."}), 400
    list_visibility = data.get('list_visibility', 'labelShow')
    label_visibility = data.get('label_visibility', 'labelShow')
    try:
        service = gc.get_service(user_id=user_id)
        result = gc.create_label(service, name, list_visibility, label_visibility)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True, port=5000)