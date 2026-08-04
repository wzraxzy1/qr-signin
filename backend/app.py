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
import urllib.parse
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

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


# ==================== Database ====================
def get_db():
    conn = sqlite3.connect(DB_PATH)
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
    expires_at: Optional[float] = None


class SessionUpdate(BaseModel):
    name: Optional[str] = None
    refresh_interval: Optional[int] = None
    fields_config: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None
    expires_at: Optional[float] = None


class SignInSubmit(BaseModel):
    token: str
    field_data: Dict[str, Any]


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
@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/sessions")
async def create_session(session: SessionCreate):
    session_id = str(uuid.uuid4())[:8]
    now = time.time()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO sessions (id, name, refresh_interval, fields_config, status, created_at, expires_at)
           VALUES (?, ?, ?, ?, 'active', ?, ?)""",
        (
            session_id,
            session.name,
            session.refresh_interval,
            json.dumps(session.fields_config, ensure_ascii=False),
            now,
            session.expires_at,
        ),
    )
    conn.commit()
    conn.close()
    return {"id": session_id, "name": session.name, "refresh_interval": session.refresh_interval}


@app.get("/api/sessions")
async def list_sessions():
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
            "expires_at": row["expires_at"],
        })
    conn.close()
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
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
        "expires_at": row["expires_at"],
        "sign_in_count": count,
    }


@app.put("/api/sessions/{session_id}")
async def update_session(session_id: str, update: SessionUpdate):
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
    if update.expires_at is not None:
        updates.append("expires_at = ?")
        params.append(update.expires_at)

    if updates:
        params.append(session_id)
        cur.execute(f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    conn.close()
    return {"status": "updated"}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM signins WHERE session_id = ?", (session_id,))
    cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


@app.get("/api/sessions/{session_id}/qr")
async def get_qr_info(session_id: str, request: Request):
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

    # Validate token - check against token history with grace period
    now = time.time()
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

    # Check for duplicate sign-in (by first field value, usually name/phone)
    fields_config = json.loads(row["fields_config"])
    field_data = data.field_data

    # Try to find a unique identifier (first required field)
    identifier_field = None
    for f in fields_config:
        if f.get("name") == "name" or f.get("name") == "phone" or f.get("name") == "employee_id":
            identifier_field = f["name"]
            break
    if not identifier_field and fields_config:
        identifier_field = fields_config[0]["name"]

    if identifier_field and identifier_field in field_data:
        cur.execute(
            "SELECT id FROM signins WHERE session_id = ? AND json_extract(field_data, ?) = ?",
            (session_id, f"$.{identifier_field}", field_data[identifier_field]),
        )
        existing = cur.fetchone()
        if existing:
            conn.close()
            raise HTTPException(status_code=409, detail="您已签到，请勿重复签到")

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
async def get_records(session_id: str):
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
async def export_records(session_id: str):
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
