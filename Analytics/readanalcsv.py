import hashlib
from datetime import datetime , timezone 
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os
import base64

# approach to portect the analytics report integrity : we use the hashing for the protection of the (checks the file if chnages using the sha256) and add some noise (timestampz) with the hashing , creating a unquie identifier and then encrypt that identifier with my own key (AES) , then use the key while analysis to decrypt the identifier , if the decryption goes smoothly then the file isn't chnaged

def sha256_of_text(text):
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))
    return h.hexdigest()

def identifier(text) : 
    tim = datetime.now(timezone.utc).isoformat()
    if not text : 
        return "text should be empty"
    has = sha256_of_text(text=text)
    fuc = f"{has},{tim}"
    if not os.path.exists("key.key") :
        key = generate_key()
    key = retrieve()
    print(f"{key}+-+{has}+-+{tim}")
    en = encrypt(text=fuc, key=key)
    print(en)
    ne = decrypt(encrypted_text=en , key=key)
    print(ne)
    
def generate_key():
    x = AESGCM.generate_key(bit_length=256)
    with open("key.key" , "wb") as f:
        f.write(x)
    return x

def retrieve():
    with open("key.key" ,"rb") as f :
        x = f.read()
    return x

def encrypt(text, key):
    aes = AESGCM(key)
    # 12 bytes is the recommended nonce size for GCM
    nonce = os.urandom(12)
    encrypted = aes.encrypt( nonce , text.encode("utf-8"), None)
    # Store nonce together with encrypted data
    result = nonce + encrypted
    return base64.b64encode(result).decode("utf-8")

def decrypt(encrypted_text, key):
    aes = AESGCM(key)
    data = base64.b64decode(encrypted_text)
    nonce = data[:12]
    encrypted = data[12:]
    decrypted = aes.decrypt( nonce, encrypted, None )
    return decrypted.decode("utf-8")

identifier("hello")