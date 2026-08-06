import os
from dotenv import load_dotenv
from supabase import create_client, Client
from flask import Flask, request, jsonify , redirect
from datetime import datetime ,timezone , timedelta
import database.UserDB as dbimp
import authnew as au
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Set SUPABASE_URL and SUPABASE_KEY in your environment or .env file")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = Flask(__name__)

@app.route("/login", methods=["POST"])
def login():
    mail = request.args.get("email")
    passw = request.args.get("password")
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
    mail = request.args.get("email")
    passw = request.args.get("password")
    if not mail or not passw:
        return jsonify({"error": "email and password are required"}), 400
    try:
        res = supabase.auth.sign_up({"email": mail, "password": passw})
        if res.user is None:
            return jsonify({"message": "signup started, check email to confirm"}), 202
        insert = dbimp.insert_rows("users" , {"user_id" : res.user.id , "created_at": datetime.now(timezone.utc)})
        token = au.jsonspoof(user_id=res.user.id , timestamp= datetime.now(timezone.utc)) 
        if not insert:
            return jsonify({"Token": token, "Statusdb" : False}), 200
        redirect()
        return jsonify({"Token": token, "Statusdb" : True}), 200
    except Exception as e:
        return jsonify({"error": "signup failed", "detail": str(e)}), 400

@app.route("/details")
def details():
    token = request.args.get("token")
    tokench = au.process(token=token)
    if not tokench["status"] :
        return jsonify({"status": "failed" , "reason": tokench["reason"]})
    user_id = tokench['user_id']
    name = request.args.get("name")
    gmail = request.args.get("Gmail")
    phone = request.args.get("phone")
    address = request.args.get("address")
    profession = request.args.get("profession")
    if not name or not gmail or not address or not phone :
        return jsonify({"status":False , "reason": "address,phone,gmail,name one of them is missing "})
    try :
        up = dbimp.update_rows("users", {"name": name , "Phone_number" : phone , "Address" : address , "Gmail":gmail, "Profession" : profession}, {"user_id":user_id})
    except :
        return jsonify({"details": True, "Statusdb" : False}), 200
    return jsonify({"details": True, "Statusdb" : True}), 200
