"""
密码哈希与 token 签发/校验（纯函数层）。
仅依赖 SECRET_KEY，不触碰数据库，方便独立单元测试。
拆分自原 app.py 的 Auth Utils 区块。
"""
import hashlib
import hmac
import secrets
import base64
import json
import time
from typing import Optional

from .config import SECRET_KEY, TOKEN_EXPIRE_HOURS


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """PBKDF2 password hashing with random salt"""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$")
        candidate = hash_password(password, salt)
        return hmac.compare_digest(candidate, stored)
    except Exception:
        return False


def create_token(user_id: str, role: str, password_version: int = 0, expires_hours: int = TOKEN_EXPIRE_HOURS) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({
            "uid": user_id,
            "role": role,
            "pv": password_version,
            "exp": time.time() + expires_hours * 3600,
        }).encode()
    ).decode()
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_token(token: str) -> Optional[dict]:
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None
