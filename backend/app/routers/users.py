"""
用户管理路由（超级管理员专用）+ 自助改密（任意登录用户）。
拆分自原 app.py 的 /api/users/* 与 /api/users/me/change-password。
"""
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException

from ..auth_utils import get_current_user, require_super_admin
from ..crypto import hash_password, verify_password
from ..db import get_db
from ..schemas import UserCreate, UserUpdate, ChangePassword

router = APIRouter()


@router.post("/api/users/me/change-password")
async def change_my_password(data: ChangePassword, user: dict = Depends(get_current_user)):
    """用户自助修改密码（需验证当前密码，任何登录用户可用）"""
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    if data.old_password == data.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user["uid"],))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="用户不存在")
    if not verify_password(data.old_password, row["password_hash"]):
        conn.close()
        raise HTTPException(status_code=400, detail="当前密码错误")
    cur.execute(
        "UPDATE users SET password_hash = ?, password_version = password_version + 1 WHERE id = ?",
        (hash_password(data.new_password), user["uid"]),
    )
    conn.commit()
    conn.close()
    return {"status": "updated"}


@router.get("/api/users")
async def list_users(_: dict = Depends(require_super_admin)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, is_active, created_at FROM users ORDER BY created_at ASC")
    rows = cur.fetchall()
    conn.close()
    users = [dict(r) for r in rows]
    # created_at is a float, keep as-is for frontend
    return {"users": users}


@router.post("/api/users")
async def create_user(data: UserCreate, _: dict = Depends(require_super_admin)):
    username = data.username.strip()
    if not username or not data.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if data.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=400, detail="无效的角色")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cur.fetchone():
        conn.close()
        raise HTTPException(status_code=409, detail="用户名已存在")
    user_id = str(uuid.uuid4())[:12]
    cur.execute(
        "INSERT INTO users (id, username, password_hash, role, is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
        (user_id, username, hash_password(data.password), data.role, time.time()),
    )
    conn.commit()
    conn.close()
    return {"id": user_id, "username": username, "role": data.role}


@router.put("/api/users/{user_id}")
async def update_user(user_id: str, data: UserUpdate, _: dict = Depends(require_super_admin)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="用户不存在")
    if data.role is not None and data.role not in ("super_admin", "admin"):
        conn.close()
        raise HTTPException(status_code=400, detail="无效的角色")
    # Prevent disabling/demoting the last super admin
    if row["role"] == "super_admin" and (data.role != "super_admin" or data.is_active == 0):
        cur.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'super_admin' AND is_active = 1")
        if cur.fetchone()["cnt"] <= 1:
            conn.close()
            raise HTTPException(status_code=400, detail="不能禁用或降级最后一个超级管理员")

    updates = []
    params = []
    if data.password:
        updates.append("password_hash = ?, password_version = password_version + 1")
        params.append(hash_password(data.password))
    if data.role is not None:
        updates.append("role = ?")
        params.append(data.role)
    if data.is_active is not None:
        updates.append("is_active = ?")
        params.append(data.is_active)
    if updates:
        params.append(user_id)
        cur.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    conn.close()
    return {"status": "updated"}


@router.delete("/api/users/{user_id}")
async def delete_user(user_id: str, _: dict = Depends(require_super_admin)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="用户不存在")
    if row["role"] == "super_admin":
        cur.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'super_admin' AND is_active = 1")
        if cur.fetchone()["cnt"] <= 1:
            conn.close()
            raise HTTPException(status_code=400, detail="不能删除最后一个超级管理员")
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}
