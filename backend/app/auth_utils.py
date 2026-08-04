"""
认证与防护工具（依赖 db / crypto / config，但 db 不反向依赖本模块，避免循环导入）：
- get_current_user / require_super_admin：FastAPI 依赖，校验 Bearer token 与角色
- 登录限流：内存级双维度（用户名 + IP）计数
- mask_id_card：身份证脱敏（导出合规）
- get_current_token：QR token 轮转与宽限期校验
拆分自原 app.py 的 Auth Utils / Token Management 区块。
"""
import time
import uuid

from fastapi import HTTPException, Header, Depends
from typing import Optional, Dict, Any

from .config import TOKEN_GRACE_PERIOD, LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW, LOGIN_LOCKOUT
from .crypto import verify_token
from .db import get_db


def get_current_user(authorization: str = Header(None)) -> dict:
    """FastAPI dependency: require a valid Bearer token.
    若用户改密/被重置密码（密码版本号变化），旧 token 立即失效。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    payload = verify_token(authorization[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    # Invalidate token when password changed after it was issued
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT password_version FROM users WHERE id = ?", (payload["uid"],))
    row = cur.fetchone()
    conn.close()
    if not row or row["password_version"] != payload.get("pv", 0):
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return payload


def require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    """FastAPI dependency: require super admin role"""
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return user


# ==================== Login Rate Limiting ====================
_login_fail: dict = {}       # key -> {"count": int, "first": float}


def _rate_limit_allowed(key: str):
    rec = _login_fail.get(key)
    if not rec:
        return True, 0
    now = time.time()
    if rec["count"] >= LOGIN_MAX_ATTEMPTS:
        waited = now - rec["first"]
        if waited < LOGIN_LOCKOUT:
            return False, int(LOGIN_LOCKOUT - waited)
        del _login_fail[key]  # 锁定期已过，重置计数器
    return True, 0


def _rate_limit_register_fail(key: str):
    now = time.time()
    rec = _login_fail.get(key)
    if not rec or (now - rec["first"]) > LOGIN_WINDOW:
        _login_fail[key] = {"count": 1, "first": now}
    else:
        rec["count"] += 1


def _rate_limit_clear(key: str):
    _login_fail.pop(key, None)


def mask_id_card(value) -> str:
    """身份证号脱敏：保留前 4 后 4，中间掩码；长度不足 8 则全掩。导出 CSV 时使用。"""
    s = str(value or "").strip()
    if not s:
        return ""
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "*" * (len(s) - 8) + s[-4:]


# ==================== Token Management ====================
def get_current_token(session_id: str) -> dict:
    """获取当前有效 token，如果过期则生成新的"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    if row["status"] != "active":
        conn.close()
        raise HTTPException(status_code=400, detail="Session is closed")

    now = time.time()
    interval = row["refresh_interval"]
    token_updated = row["token_updated_at"] or 0

    # Check if token needs refresh
    if not row["current_token"] or (now - token_updated) >= interval:
        new_token = uuid.uuid4().hex[:16]
        cur.execute(
            "UPDATE sessions SET current_token = ?, token_updated_at = ? WHERE id = ?",
            (new_token, now, session_id),
        )
        # Save token to history for grace period validation
        cur.execute(
            "INSERT INTO qr_tokens (id, session_id, token, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4())[:12], session_id, new_token, now),
        )
        # Clean up tokens older than 5 minutes
        cur.execute("DELETE FROM qr_tokens WHERE created_at < ?", (now - 300,))
        conn.commit()
        current_token = new_token
        token_updated = now
    else:
        current_token = row["current_token"]

    expires_in = max(0, interval - (now - token_updated))
    conn.close()
    return {
        "token": current_token,
        "expires_in": round(expires_in, 1),
        "interval": interval,
    }
