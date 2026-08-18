import hashlib
import hmac
import os
import database.UserDB as dbimp
import Drive.dep as depppp
SECRET_KEY = os.environ.get("token_secret", "").encode("utf-8")

def mainfileIdentity(user_id, token, tablename, columnn, c_value):
    if not user_id or not token:
        return False
    rows = dbimp.select_rows(token, tablename, select="File,Hash_file", filters={columnn: c_value})
    row = rows[0] if rows else None
    if row is None:
        return False
    hashed = row["Hash_file"]
    file_id = row["File"]
    x = depppp.read_csv_from_dive(file_id=file_id, token=token)
    if not x:
        return False
    x_hash = hmac.new(SECRET_KEY, x.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(x_hash, hashed) :
        return False
    return x

'''
text = { "file1": { "file_id": 345454, "caption": "12345_marketing", "Hash_file": "a3f5c8e9b2d1..." },
  "file2": { "file_id": 987654, "caption": "67890_marketing","Hash_file": "b7e2f1a4c9d3..."},
  "file3": {"file_id": 112233, "caption": "12345_report", "Hash_file": "c1d9e4f7a2b8..." }}
  '''

def fileIdenetiy(user_id, token, text,purpose):
    name = f"{user_id}_{purpose}"
    file_id = None
    file_hash = None
    for key, file_data in text.items():   # key get the dict key values file file1, file2
        if file_data.get("caption") == name:
            file_id = file_data.get("file_id")
            file_hash = file_data.get("Hash_file")
            break
    if file_id is None or file_hash is None:
        return False  
    x = depppp.read_csv_from_dive(file_id=file_id, token=token)
    if not x:
        return False
    x_hash = hmac.new(SECRET_KEY, x.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(x_hash, file_hash):
        return False
    return x
