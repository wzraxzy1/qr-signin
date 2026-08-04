"""
SQLite 连接与表初始化。
- get_db：每次请求开连接，开启 WAL + busy_timeout 防并发 "database is locked"。
- init_db：首次运行建表、迁移新增列、清理过期 QR token、播种默认超管。
拆分自原 app.py 的 Database 区块。
"""
import sqlite3
import os
import uuid
import time
import json
import secrets

from .config import DB_PATH, IS_PRODUCTION
from .crypto import hash_password


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
    # Create default super admin on first run.
    # 安全基线：禁止回退到可猜测的默认密码（如旧版的 "admin123"）。
    # - 生产环境：必须显式设置 DEFAULT_ADMIN_PASSWORD，否则拒绝启动。
    # - 开发环境：未设置则生成一次性随机密码并打印到启动日志（仅显示一次），请尽快在管理面板修改。
    cur.execute("SELECT COUNT(*) as cnt FROM users")
    if cur.fetchone()["cnt"] == 0:
        default_user = os.environ.get("DEFAULT_ADMIN_USER", "admin")
        default_pass = os.environ.get("DEFAULT_ADMIN_PASSWORD")
        if not default_pass:
            if IS_PRODUCTION:
                raise RuntimeError(
                    "安全基线：生产环境必须设置环境变量 DEFAULT_ADMIN_PASSWORD，"
                    "禁止回退到可猜测的默认密码。请在部署配置中 "
                    "export DEFAULT_ADMIN_PASSWORD=<强随机密码> 后重启服务。"
                )
            default_pass = secrets.token_urlsafe(16)
            print(
                f"[WARN] 未设置 DEFAULT_ADMIN_PASSWORD，已生成随机初始密码（仅显示一次）：{default_pass}\n"
                f"       请尽快在管理面板修改。生产环境请通过环境变量显式提供固定密码。"
            )
        cur.execute(
            "INSERT INTO users (id, username, password_hash, role, is_active, created_at) VALUES (?, ?, ?, 'super_admin', 1, ?)",
            (str(uuid.uuid4())[:12], default_user, hash_password(default_pass), time.time()),
        )
    # Clean up tokens older than 5 minutes on startup
    cur.execute("DELETE FROM qr_tokens WHERE created_at < ?", (time.time() - 300,))
    conn.commit()
    conn.close()
