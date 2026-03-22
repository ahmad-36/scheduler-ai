import os
import requests
from typing import Optional, Any, Dict

from core.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

def _headers():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in env.")
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def _url(path: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{path}"

def get_or_create_user(username: str) -> Dict[str, Any]:
    # try fetch
    r = requests.get(_url(f"users?username=eq.{username}&select=id,username,passcode_salt"),
                     headers=_headers(), timeout=20)
    r.raise_for_status()
    rows = r.json()
    if rows:
        row = rows[0]
        row["passcode_salt"] = bytes.fromhex(row["passcode_salt"][2:]) if isinstance(row["passcode_salt"], str) and row["passcode_salt"].startswith("\\x") else row["passcode_salt"]
        return row

    # create
    import secrets
    salt = secrets.token_bytes(16)
    payload = {"username": username, "passcode_salt": salt.hex()}  # store as hex text if bytea is awkward
    r = requests.post(_url("users"), headers=_headers(), json=payload, timeout=20)
    r.raise_for_status()
    # fetch again
    return get_or_create_user(username)

def set_secret(user_id: str, key: str, ciphertext: bytes) -> None:
    headers = _headers()
    headers["Prefer"] = "resolution=merge-duplicates"
    # Fernet tokens are base64url-encoded ASCII — store as plain text string
    payload = {"user_id": user_id, "key": key, "ciphertext": ciphertext.decode("utf-8")}
    r = requests.post(_url("secrets"), headers=headers, json=payload, timeout=20)
    r.raise_for_status()

def get_secret_cipher(user_id: str, key: str) -> Optional[bytes]:
    r = requests.get(_url(f"secrets?user_id=eq.{user_id}&key=eq.{key}&select=ciphertext"),
                     headers=_headers(), timeout=20)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None
    val = rows[0]["ciphertext"]
    if isinstance(val, str):
        # Strip Supabase bytea \x prefix if present, then hex-decode (old format)
        if val.startswith("\\x"):
            try:
                return bytes.fromhex(val[2:])
            except ValueError:
                pass
        # New format: plain Fernet base64 string
        return val.encode("utf-8")
    return bytes(val)

def set_tasks(user_id: str, task_json: Any) -> None:
    headers = _headers()
    headers["Prefer"] = "resolution=merge-duplicates"
    payload = {"user_id": user_id, "task_json": task_json}
    r = requests.post(_url("tasks"), headers=headers, json=payload, timeout=20)
    r.raise_for_status()

def get_tasks(user_id: str) -> Optional[Any]:
    r = requests.get(_url(f"tasks?user_id=eq.{user_id}&select=task_json&limit=1&order=updated_at.desc"),
                     headers=_headers(), timeout=20)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None
    return rows[0]["task_json"]
