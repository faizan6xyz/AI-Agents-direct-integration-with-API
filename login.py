import os
from dotenv import load_dotenv
from supabase import create_client, Client
from flask import Flask, request, jsonify
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Set SUPABASE_URL and SUPABASE_KEY in your environment or .env file")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = Flask(__name__)

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    mail = data.get("email")
    passw = data.get("password")
    if not mail or not passw:
        return jsonify({"error": "email and password are required"}), 400
    try:
        res = supabase.auth.sign_in_with_password({"email": mail, "password": passw})
        if res.user is None:
            return jsonify({"error": "invalid credentials"}), 401
        return jsonify({"user_id": res.user.id}), 200
    except Exception as e:
        return jsonify({"error": "invalid credentials", "detail": str(e)}), 401

@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    mail = data.get("email")
    passw = data.get("password")
    if not mail or not passw:
        return jsonify({"error": "email and password are required"}), 400
    try:
        res = supabase.auth.sign_up({"email": mail, "password": passw})
        if res.user is None:
            # e.g. email confirmation required before a session exists
            return jsonify({"message": "signup started, check email to confirm"}), 202
        return jsonify({"user_id": res.user.id}), 201
    except Exception as e:
        return jsonify({"error": "signup failed", "detail": str(e)}), 400