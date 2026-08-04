"""
签到会话路由：增删改查、QR 信息、公开表单、记录列表、CSV 导出。
拆分自原 app.py 的 /api/sessions/* 区块。
"""
import io
import json
import csv
import uuid
import time
import urllib.parse
from datetime import datetime

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..auth_utils import get_current_user, get_current_token, mask_id_card
from ..db import get_db
from ..schemas import SessionCreate, SessionUpdate

router = APIRouter()


@router.post("/api/sessions")
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


@router.get("/api/sessions")
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


@router.get("/api/sessions/{session_id}")
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


@router.put("/api/sessions/{session_id}")
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


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM signins WHERE session_id = ?", (session_id,))
    cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


@router.get("/api/sessions/{session_id}/qr")
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


@router.get("/api/sessions/{session_id}/public")
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


@router.get("/api/sessions/{session_id}/records")
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


@router.get("/api/sessions/{session_id}/export")
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
        row_data = []
        for f in fields_config:
            val = data.get(f["name"], "")
            if f["name"] == "id_card":  # 身份证号脱敏，遵守个人信息保护法
                val = mask_id_card(val)
            row_data.append(val)
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
