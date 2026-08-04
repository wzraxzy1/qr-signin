"""
认证路由：登录（带限流）、当前用户。
拆分自原 app.py 的 /api/auth/login 与 /api/auth/me。
"""
from fastapi import APIRouter, Request, Depends, HTTPException

from ..auth_utils import get_current_user, _rate_limit_allowed, _rate_limit_register_fail, _rate_limit_clear
from ..crypto import verify_password, create_token
from ..db import get_db
from ..schemas import LoginRequest

router = APIRouter()


@router.post("/api/auth/login")
async def login(data: LoginRequest, request: Request):
    """用户登录，返回 token。带登录限流（按用户名 + 来源 IP 双维度）。"""
    client_ip = request.client.host if request.client else "unknown"
    username = data.username.strip()
    for key in (username, f"ip:{client_ip}"):
        allowed, wait = _rate_limit_allowed(key)
        if not allowed:
            raise HTTPException(status_code=429, detail=f"登录尝试过于频繁，请 {wait} 秒后再试")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    if not row or not verify_password(data.password, row["password_hash"]):
        for key in (username, f"ip:{client_ip}"):
            _rate_limit_register_fail(key)
        conn.close()
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not row["is_active"]:
        conn.close()
        raise HTTPException(status_code=403, detail="账号已被禁用")
    for key in (username, f"ip:{client_ip}"):
        _rate_limit_clear(key)
    token = create_token(row["id"], row["role"], row["password_version"])
    return {
        "token": token,
        "user": {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
        },
    }


@router.get("/api/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, is_active, created_at FROM users WHERE id = ?", (user["uid"],))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="用户不存在")
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_active": row["is_active"],
        "created_at": row["created_at"],
    }
