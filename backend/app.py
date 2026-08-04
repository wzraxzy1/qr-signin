"""
动态二维码签到系统 - 后端 API
FastAPI + SQLite
"""
import sqlite3
import json
import uuid
import time
import os
import csv
import io
import hashlib
import hmac
import secrets
import base64
import urllib.parse
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Query, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

# Auth config
# SECRET_KEY：生产环境（APP_ENV=production）必须显式设置，缺失则拒绝启动，
# 禁止回退到公开可猜的默认密钥；开发环境未设置时生成临时密钥（进程重启后失效，仅本地可接受）。
SECRET_KEY = os.environ.get("SECRET_KEY")
_APP_ENV = os.environ.get("APP_ENV", os.environ.get("ENV", "development")).lower()
if not SECRET_KEY:
    if _APP_ENV == "production":
        raise RuntimeError(
            "安全基线：生产环境必须设置环境变量 SECRET_KEY，禁止回退到默认密钥。"
            "请在部署配置中 export SECRET_KEY=<随机32+位十六进制> 后重启服务。"
        )
    SECRET_KEY = secrets.token_hex(32)
    print("[WARN] SECRET_KEY 未设置，已生成临时开发密钥（进程重启后失效）。"
          "生产部署请通过环境变量提供固定的 SECRET_KEY。")
TOKEN_EXPIRE_HOURS = 24

# Render: use persistent disk path if available, otherwise local dir
_RENDER_DATA = os.environ.get("RENDER_DATA_DIR", "")
if _RENDER_DATA:
    DB_PATH = os.path.join(_RENDER_DATA, "signin.db")
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signin.db")

# Frontend dist: look relative to backend dir, fallback to /opt/render/ paths for Render
_backend_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_backend_dir)
FRONTEND_DIST = os.path.join(_project_root, "frontend", "dist")
if not os.path.isdir(FRONTEND_DIST):
    # Render build may place frontend in a different location
    FRONTEND_DIST = os.path.join(os.environ.get("RENDER_PROJECT_DIR", _project_root), "frontend", "dist")

app = FastAPI(title="QR Sign-in System")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Auth Utils ====================
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


# ==================== Database ====================
def get_db():
    # 开启 WAL + busy_timeout，避免 uvicorn 多线程并发下出现间歇性的 "database is locked"，
    # 并将锁等待拉长到 10s 而非默认的 5s 立即失败。
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            refresh_interval INTEGER NOT NULL DEFAULT 10,
            fields_config TEXT NOT NULL DEFAULT '[]',
            current_token TEXT,
            token_updated_at REAL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at REAL NOT NULL,
            expires_at REAL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signins (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            token TEXT,
            field_data TEXT NOT NULL,
            sign_in_time REAL NOT NULL,
            ip_address TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS qr_tokens (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            token TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL
        )
    """)
    # Migration: add password_version column for token invalidation on password change
    try:
        cur.execute("ALTER TABLE users ADD COLUMN password_version INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # column already exists
    # Migration: add start_at column for sign-in start time (optional)
    try:
        cur.execute("ALTER TABLE sessions ADD COLUMN start_at REAL")
    except Exception:
        pass  # column already exists
    # Migration: add max_signins column for capacity limit (optional)
    try:
        cur.execute("ALTER TABLE sessions ADD COLUMN max_signins INTEGER")
    except Exception:
        pass  # column already exists
    # Create default super admin on first run
    cur.execute("SELECT COUNT(*) as cnt FROM users")
    if cur.fetchone()["cnt"] == 0:
        default_user = os.environ.get("DEFAULT_ADMIN_USER", "admin")
        default_pass = os.environ.get("DEFAULT_ADMIN_PASSWORD", "admin123")
        cur.execute(
            "INSERT INTO users (id, username, password_hash, role, is_active, created_at) VALUES (?, ?, ?, 'super_admin', 1, ?)",
            (str(uuid.uuid4())[:12], default_user, hash_password(default_pass), time.time()),
        )
    # Clean up tokens older than 5 minutes on startup
    cur.execute("DELETE FROM qr_tokens WHERE created_at < ?", (time.time() - 300,))
    conn.commit()
    conn.close()

# Token grace period: users get this many seconds after QR generation to submit
TOKEN_GRACE_PERIOD = 120  # 2 minutes


init_db()


# ==================== Models ====================
class SessionCreate(BaseModel):
    name: str
    refresh_interval: int = 10
    fields_config: List[Dict[str, Any]] = []
    start_at: Optional[float] = None
    expires_at: Optional[float] = None
    max_signins: Optional[int] = None


class SessionUpdate(BaseModel):
    name: Optional[str] = None
    refresh_interval: Optional[int] = None
    fields_config: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None
    start_at: Optional[float] = None
    expires_at: Optional[float] = None
    max_signins: Optional[int] = None


class SignInSubmit(BaseModel):
    token: str
    field_data: Dict[str, Any]


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "admin"


class UserUpdate(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[int] = None


class ChangePassword(BaseModel):
    old_password: str
    new_password: str


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


# ==================== API Routes ====================
@app.post("/api/auth/login")
async def login(data: LoginRequest):
    """用户登录，返回 token"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (data.username.strip(),))
    row = cur.fetchone()
    conn.close()
    if not row or not verify_password(data.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    token = create_token(row["id"], row["role"], row["password_version"])
    return {
        "token": token,
        "user": {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
        },
    }


@app.get("/api/auth/me")
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


@app.post("/api/users/me/change-password")
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


# ==================== User Management (Super Admin only) ====================
@app.get("/api/users")
async def list_users(_: dict = Depends(require_super_admin)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, is_active, created_at FROM users ORDER BY created_at ASC")
    rows = cur.fetchall()
    conn.close()
    users = [dict(r) for r in rows]
    # created_at is a float, keep as-is for frontend
    return {"users": users}


@app.post("/api/users")
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


@app.put("/api/users/{user_id}")
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


@app.delete("/api/users/{user_id}")
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


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/sessions")
async def create_session(session: SessionCreate, user: dict = Depends(get_current_user)):
    session_id = str(uuid.uuid4())[:8]
    now = time.time()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO sessions (id, name, refresh_interval, fields_config, status, created_at, start_at, expires_at, max_signins)
           VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
        (
            session_id,
            session.name,
            session.refresh_interval,
            json.dumps(session.fields_config, ensure_ascii=False),
            now,
            session.start_at,
            session.expires_at,
            session.max_signins,
        ),
    )
    conn.commit()
    conn.close()
    return {"id": session_id, "name": session.name, "refresh_interval": session.refresh_interval}


@app.get("/api/sessions")
async def list_sessions(user: dict = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions ORDER BY created_at DESC")
    rows = cur.fetchall()
    sessions = []
    for row in rows:
        sessions.append({
            "id": row["id"],
            "name": row["name"],
            "refresh_interval": row["refresh_interval"],
            "fields_config": json.loads(row["fields_config"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "start_at": row["start_at"],
            "expires_at": row["expires_at"],
            "max_signins": row["max_signins"],
        })
    conn.close()
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    # Get sign-in count
    cur.execute("SELECT COUNT(*) as cnt FROM signins WHERE session_id = ?", (session_id,))
    count = cur.fetchone()["cnt"]
    conn.close()
    return {
        "id": row["id"],
        "name": row["name"],
        "refresh_interval": row["refresh_interval"],
        "fields_config": json.loads(row["fields_config"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "start_at": row["start_at"],
        "expires_at": row["expires_at"],
        "max_signins": row["max_signins"],
        "sign_in_count": count,
    }


@app.put("/api/sessions/{session_id}")
async def update_session(session_id: str, update: SessionUpdate, user: dict = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    updates = []
    params = []
    if update.name is not None:
        updates.append("name = ?")
        params.append(update.name)
    if update.refresh_interval is not None:
        updates.append("refresh_interval = ?")
        params.append(update.refresh_interval)
    if update.fields_config is not None:
        updates.append("fields_config = ?")
        params.append(json.dumps(update.fields_config, ensure_ascii=False))
    if update.status is not None:
        updates.append("status = ?")
        params.append(update.status)
    if update.start_at is not None:
        updates.append("start_at = ?")
        params.append(update.start_at)
    if update.expires_at is not None:
        updates.append("expires_at = ?")
        params.append(update.expires_at)
    if update.max_signins is not None:
        updates.append("max_signins = ?")
        params.append(update.max_signins)

    if updates:
        params.append(session_id)
        cur.execute(f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    conn.close()
    return {"status": "updated"}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM signins WHERE session_id = ?", (session_id,))
    cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


@app.get("/api/sessions/{session_id}/qr")
async def get_qr_info(session_id: str, request: Request, user: dict = Depends(get_current_user)):
    """获取当前 QR 码信息"""
    token_info = get_current_token(session_id)
    # Build the sign-in URL
    base_url = str(request.base_url).rstrip("/")
    signin_url = f"{base_url}/#/signin?session={session_id}&token={token_info['token']}"
    return {
        "url": signin_url,
        "token": token_info["token"],
        "expires_in": token_info["expires_in"],
        "interval": token_info["interval"],
    }


@app.get("/api/sessions/{session_id}/public")
async def get_session_public(session_id: str):
    """公开接口：供手机签到页加载表单字段，无需登录。
    仅返回签到所需的最小信息（不含 token、签到记录等敏感数据）。"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    cur.execute("SELECT COUNT(*) as cnt FROM signins WHERE session_id = ?", (session_id,))
    count = cur.fetchone()["cnt"]
    conn.close()
    return {
        "id": row["id"],
        "name": row["name"],
        "fields_config": json.loads(row["fields_config"]),
        "status": row["status"],
        "start_at": row["start_at"],
        "expires_at": row["expires_at"],
        "max_signins": row["max_signins"],
        "sign_in_count": count,
    }


@app.post("/api/sessions/{session_id}/signin")
async def submit_signin(session_id: str, data: SignInSubmit, request: Request):
    """提交签到"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    if row["status"] != "active":
        conn.close()
        raise HTTPException(status_code=400, detail="签到已关闭")

    now = time.time()
    # Time window enforcement (start_at / expires_at)
    if row["start_at"] and now < row["start_at"]:
        conn.close()
        raise HTTPException(status_code=403, detail="签到尚未开始")
    if row["expires_at"] and now > row["expires_at"]:
        conn.close()
        raise HTTPException(status_code=403, detail="签到已结束")

    # Validate token - check against token history with grace period
    interval = row["refresh_interval"]
    # Token validity: refresh_interval + grace period (for user to fill form)
    token_validity = interval + TOKEN_GRACE_PERIOD

    # Look up the token in history
    cur.execute(
        "SELECT * FROM qr_tokens WHERE session_id = ? AND token = ? ORDER BY created_at DESC LIMIT 1",
        (session_id, data.token),
    )
    token_row = cur.fetchone()
    if not token_row:
        conn.close()
        raise HTTPException(status_code=403, detail="二维码无效或已过期，请重新扫描")
    if (now - token_row["created_at"]) >= token_validity:
        conn.close()
        raise HTTPException(status_code=403, detail="二维码已过期，请重新扫描")

    # Check for duplicate sign-in using a COMPOSITE key of identity fields.
    # Prefer employee_id/phone (more unique) and also include name, so two genuinely
    # different people who share a name but have different phones can both sign in.
    # Only when neither is collected does it fall back to name-only (or all fields).
    field_data = data.field_data
    identity_candidates = ["employee_id", "phone", "name"]
    key_fields = [
        c for c in identity_candidates
        if c in field_data and str(field_data.get(c, "")).strip() != ""
    ]
    if not key_fields and field_data:
        key_fields = list(field_data.keys())

    if key_fields:
        where = " AND ".join("json_extract(field_data, ?) = ?" for _ in key_fields)
        params = [session_id]
        for kf in key_fields:
            params.append(f"$.{kf}")
            params.append(str(field_data[kf]))
        cur.execute(
            f"SELECT id FROM signins WHERE session_id = ? AND {where}",
            params,
        )
        existing = cur.fetchone()
        if existing:
            conn.close()
            raise HTTPException(status_code=409, detail="您已签到，请勿重复签到")

    # Rule 2: per-field uniqueness for the three identity fields
    # (工号 / 身份证号 / 学号). If ANY of them is filled and already exists in
    # another sign-in record for this session, reject as a duplicate sign-in.
    # This catches cases the composite key above misses (e.g. same employee_id
    # but a typo'd name/phone). The previous composite rule still applies.
    unique_fields = {
        "employee_id": "工号",
        "id_card": "身份证号",
        "student_number": "学号",
    }
    for uf, label in unique_fields.items():
        val = field_data.get(uf)
        if val is None or str(val).strip() == "":
            continue
        cur.execute(
            "SELECT id FROM signins WHERE session_id = ? AND json_extract(field_data, ?) = ?",
            (session_id, f"$.{uf}", str(val)),
        )
        if cur.fetchone():
            conn.close()
            raise HTTPException(status_code=409, detail=f"该{label}已签到，请勿重复签到")

    # Capacity limit: if max_signins is set and already reached, reject new sign-ins
    max_signins = row["max_signins"]
    if max_signins is not None:
        cur.execute("SELECT COUNT(*) as cnt FROM signins WHERE session_id = ?", (session_id,))
        if cur.fetchone()["cnt"] >= max_signins:
            conn.close()
            raise HTTPException(status_code=409, detail=f"签到人数已满（上限 {max_signins} 人）")

    # Save sign-in
    signin_id = str(uuid.uuid4())[:8]
    client_ip = request.client.host if request.client else "unknown"
    cur.execute(
        """INSERT INTO signins (id, session_id, token, field_data, sign_in_time, ip_address)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (signin_id, session_id, data.token, json.dumps(field_data, ensure_ascii=False), now, client_ip),
    )
    conn.commit()
    conn.close()
    return {"status": "success", "sign_in_time": now}


@app.get("/api/sessions/{session_id}/records")
async def get_records(session_id: str, user: dict = Depends(get_current_user)):
    """获取签到记录"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM signins WHERE session_id = ? ORDER BY sign_in_time ASC", (session_id,))
    rows = cur.fetchall()
    # Get session for field config
    cur.execute("SELECT fields_config, name FROM sessions WHERE id = ?", (session_id,))
    session = cur.fetchone()
    conn.close()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    fields_config = json.loads(session["fields_config"])
    records = []
    for row in rows:
        data = json.loads(row["field_data"])
        record = {
            "id": row["id"],
            "sign_in_time": row["sign_in_time"],
            "time_str": datetime.fromtimestamp(row["sign_in_time"]).strftime("%Y-%m-%d %H:%M:%S"),
            "ip_address": row["ip_address"],
        }
        for f in fields_config:
            record[f["name"]] = data.get(f["name"], "")
        records.append(record)
    return {
        "session_name": session["name"],
        "fields_config": fields_config,
        "records": records,
        "total": len(records),
    }


@app.get("/api/sessions/{session_id}/export")
async def export_records(session_id: str, user: dict = Depends(get_current_user)):
    """导出签到记录为 CSV"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM signins WHERE session_id = ? ORDER BY sign_in_time ASC", (session_id,))
    rows = cur.fetchall()
    cur.execute("SELECT fields_config, name FROM sessions WHERE id = ?", (session_id,))
    session = cur.fetchone()
    conn.close()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    fields_config = json.loads(session["fields_config"])

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM for Excel
    writer = csv.writer(output)

    # Header row
    headers = [f["label"] for f in fields_config] + ["签到时间", "IP地址"]
    writer.writerow(headers)

    # Data rows
    for row in rows:
        data = json.loads(row["field_data"])
        row_data = [data.get(f["name"], "") for f in fields_config]
        row_data.append(datetime.fromtimestamp(row["sign_in_time"]).strftime("%Y-%m-%d %H:%M:%S"))
        row_data.append(row["ip_address"])
        writer.writerow(row_data)

    output.seek(0)
    raw_name = f"signin_{session['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    ascii_name = f"signin_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    encoded_name = urllib.parse.quote(raw_name)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"
        }
    )


# ==================== Serve Frontend ====================
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = os.path.join(FRONTEND_DIST, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
