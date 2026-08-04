"""
公开签到提交路由（无需登录鉴权）。
拆分自原 app.py 的 /api/sessions/{session_id}/signin，单独成文件以突出其
“公开端点”的安全边界：相比同前缀的其它会话接口，本接口不要求登录。
"""
import time
import uuid
import json

from fastapi import APIRouter, Request, HTTPException

from ..config import TOKEN_GRACE_PERIOD
from ..db import get_db
from ..schemas import SignInSubmit

router = APIRouter()


@router.post("/api/sessions/{session_id}/signin")
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
