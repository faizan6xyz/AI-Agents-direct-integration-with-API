import base64
import string
import secrets
from datetime import datetime ,timezone
import random 
import database.UserDB as dbimp

def random_text(limit):
    password = [ secrets.choice(string.ascii_uppercase), secrets.choice(string.ascii_lowercase), secrets.choice(string.digits),]
    characters = string.ascii_letters + string.digits
    password.extend(secrets.choice(characters) for _ in range(limit))
    random.SystemRandom().shuffle(password)
    return ''.join(password)


def jsonspoof(user_id, timestamp):
    user_id1 = base64.b64encode(user_id.encode("utf-8")).decode("utf-8")
    time1 = base64.b64encode(str(timestamp).encode("utf-8")).decode("utf-8")
    signature = f"{user_id}++{random_text(6)}--{timestamp}"
    signature1 = base64.b64encode(signature.encode("utf-8")).decode("utf-8")
    return f"{user_id1}.{time1}.{signature1}"


def jp(token):
    token = token.split(".")
    user_id = base64.b64decode(token[0]).decode('utf-8') if token[0] else False
    time = base64.b64decode(token[1]).decode('utf-8') if token[1] else False
    signature = base64.b64decode(token[2]).decode('utf-8') if token[2] else False
    if not user_id or not time or not signature :
        return False
    return {"user" : user_id , "time" : time , "sign" : signature }

def process(token):
    if not token.strip():
        return "Token is needed"
    decd = jp(token)
    user_id = decd["user"] if decd["user"] else False
    time = decd["time"] if decd["time"] else False
    sign = decd["sign"] if decd["sign"] else False
    if not user_id or not time or not sign :
        return "user_id,time,sign of them is missing"
    tok = dbimp.select_rows("users", select="token", filters={"user_id":user_id})
    if not tok or tok != token :
        return "current token mismatch"
    if datetime.now(timezone.utc) > time :
        time = datetime.now(timezone.utc)
        token_new = jsonspoof(user_id=user_id , timestamp=time)
        update = dbimp.update_rows("users" , {"token":token_new},{"user_id":user_id})
        if not update:
            return "unable to update"
        return token_new
        


