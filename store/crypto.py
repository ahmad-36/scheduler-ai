import base64
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet

def derive_fernet_key(passcode: str, user_salt: bytes, app_secret: str) -> bytes:
    """
    Derive a symmetric key from (passcode + per-user salt + app secret).
    Server never stores passcode. If user forgets passcode, secrets are unrecoverable.
    """
    salt = user_salt + app_secret.encode("utf-8")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    return base64.urlsafe_b64encode(kdf.derive(passcode.encode("utf-8")))

def encrypt(passcode: str, user_salt: bytes, app_secret: str, plaintext: str) -> bytes:
    f = Fernet(derive_fernet_key(passcode, user_salt, app_secret))
    return f.encrypt(plaintext.encode("utf-8"))

def decrypt(passcode: str, user_salt: bytes, app_secret: str, ciphertext: bytes) -> str:
    f = Fernet(derive_fernet_key(passcode, user_salt, app_secret))
    return f.decrypt(ciphertext).decode("utf-8")
