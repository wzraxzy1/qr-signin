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

from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from ..auth_utils import get_current_user, get_current_token, mask_id_card
from ..db import get_db
from ..schemas import SessionCreate, SessionUpdate

router = APIRouter()


def _parse_roster_bytes(content: bytes, filename: str):
    """解析名单文件（CSV 或 XLSX），返回 (headers, rows)。

    headers: 首行去空白后的字符串列表
    rows:    后续每行的单元格列表（字符串；空单元格为 ""）
    """
    lower = (filename or "").lower()
    if lower.endswith(".xlsx"):
        try:
            import openpyxl
        except ImportError:
            raise HTTPException(status_code=500, detail="服务器未安装 openpyxl，无法解析 xlsx")
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        if ws is None:
            return [], []
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        if not grid:
            return [], []
        headers = [str(h).strip() if h is not None else "" for h in grid[0]]
        rows = []
        for raw in grid[1:]:
            cells = [str(c).strip() if c is not None else "" for c in raw]
            # 补齐到与表头等长，避免列错位
            if len(cells) < len(headers):
                cells = cells + [""] * (len(headers) - len(cells))
            rows.append(cells)
        return headers, rows
    else:
        # 默认按 CSV 处理（兼容 .csv / .txt）
        text = content.decode("utf-8-sig", errors="replace")
        reader = list(csv.reader(io.StringIO(text)))
        if not reader:
            return [], []
        headers = [h.strip() for h in reader[0]]
        rows = [["" if c is None else str(c).strip() for c in r] for r in reader[1:]]
        return headers, rows


def _owned_session(cur, session_id: str, user: dict):
    """Return the session row if the user may access it, else None.

    super_admin 可访问任意会话；普通 admin 仅能访问自己创建的（created_by = uid）。
    不存在或无权限一律返回 None（调用方按 404 处理，避免泄露是否存在）。"""
    cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    if not row:
        return None
    if user.get("role") != "super_admin" and row["created_by"] != user["uid"]:
        return None
    return row


@router.post("/api/sessions")
async def create_session(session: SessionCreate, user: dict = Depends(get_current_user)):
    session_id = str(uuid.uuid4())[:8]
    now = time.time()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO sessions (id, name, refresh_interval, fields_config, status, created_at, start_at, expires_at, max_signins, created_by)
           VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
        (
            session_id,
            session.name,
            session.refresh_interval,
            json.dumps(session.fields_config, ensure_ascii=False),
            now,
            session.start_at,
            session.expires_at,
            session.max_signins,
            user["uid"],
        ),
    )
    conn.commit()
    conn.close()
    return {"id": session_id, "name": session.name, "refresh_interval": session.refresh_interval}


@router.get("/api/sessions")
async def list_sessions(user: dict = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    # LEFT JOIN 出创建者用户名；普通 admin 仅看自己创建的，super_admin 看全部。
    if user.get("role") == "super_admin":
        cur.execute(
            "SELECT s.*, u.username AS creator_username FROM sessions s "
            "LEFT JOIN users u ON s.created_by = u.id ORDER BY s.created_at DESC"
        )
    else:
        cur.execute(
            "SELECT s.*, u.username AS creator_username FROM sessions s "
            "LEFT JOIN users u ON s.created_by = u.id WHERE s.created_by = ? ORDER BY s.created_at DESC",
            (user["uid"],),
        )
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
            "created_by": row["created_by"],
            "created_by_username": row["creator_username"],
        })
    conn.close()
    return {"sessions": sessions}


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    row = _owned_session(cur, session_id, user)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    # Get sign-in count
    cur.execute("SELECT COUNT(*) as cnt FROM signins WHERE session_id = ?", (session_id,))
    count = cur.fetchone()["cnt"]
    cur.execute("SELECT username FROM users WHERE id = ?", (row["created_by"],))
    creator = cur.fetchone()
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
        "created_by": row["created_by"],
        "created_by_username": creator["username"] if creator else None,
        "sign_in_count": count,
    }


@router.put("/api/sessions/{session_id}")
async def update_session(session_id: str, update: SessionUpdate, user: dict = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()
    row = _owned_session(cur, session_id, user)
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
    row = _owned_session(cur, session_id, user)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    cur.execute("DELETE FROM signins WHERE session_id = ?", (session_id,))
    cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


@router.get("/api/sessions/{session_id}/qr")
async def get_qr_info(session_id: str, request: Request, user: dict = Depends(get_current_user)):
    """获取当前 QR 码信息"""
    conn = get_db()
    cur = conn.cursor()
    row = _owned_session(cur, session_id, user)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    conn.close()
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
    row = _owned_session(cur, session_id, user)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    cur.execute("SELECT * FROM signins WHERE session_id = ? ORDER BY sign_in_time ASC", (session_id,))
    rows = cur.fetchall()
    session = {"fields_config": row["fields_config"], "name": row["name"]}
    conn.close()

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
    row = _owned_session(cur, session_id, user)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    cur.execute("SELECT * FROM signins WHERE session_id = ? ORDER BY sign_in_time ASC", (session_id,))
    rows = cur.fetchall()
    session = {"fields_config": row["fields_config"], "name": row["name"]}
    conn.close()

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
@router.post("/api/sessions/{session_id}/roster")
async def import_roster(
    session_id: str,
    file: UploadFile = File(...),
    match_field: str = Form(...),
    user: dict = Depends(get_current_user),
):
    """导入名单（CSV / XLSX）。

    - match_field：管理员手动指定的匹配列，必须是本会话某个字段的 name
      （如 "employee_id"/"id_card"/"student_number"/"phone"/"name"）。
    - 名单表头（首行）按 label 或 name 映射到会话字段；匹配不上的列也保留（key 用原表头）。
    - 替换式写入：同一会话重复导入会清空旧名单。
    """
    conn = get_db()
    cur = conn.cursor()
    row = _owned_session(cur, session_id, user)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")

    fields_config = json.loads(row["fields_config"])
    field_names = {f["name"] for f in fields_config}

    content = await file.read()
    headers, rows = _parse_roster_bytes(content, file.filename)
    if not headers:
        conn.close()
        raise HTTPException(status_code=400, detail="名单文件为空或无法解析（需包含表头行）")

    # 表头 -> 会话字段 name（能映射才用 name，否则保留原表头字符串）
    label_to_name = {f["label"]: f["name"] for f in fields_config if f.get("label")}
    header_map = {}
    for h in headers:
        if h in field_names:
            header_map[h] = h
        elif h in label_to_name:
            header_map[h] = label_to_name[h]
        else:
            header_map[h] = h  # 保留原表头（如备注列）

    # 校验匹配列在名单中能找到对应表头
    match_header = None
    for h, name in header_map.items():
        if name == match_field:
            match_header = h
            break
    if match_header is None:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"匹配列「{match_field}」在名单中找不到对应表头，请检查名单表头或重新选择匹配列",
        )
    if match_field not in field_names:
        conn.close()
        raise HTTPException(status_code=400, detail=f"匹配列「{match_field}」不是本会话的字段")

    # 替换式写入
    cur.execute("DELETE FROM roster WHERE session_id = ?", (session_id,))
    seq = 0
    for r in rows:
        field_data = {}
        for idx, h in enumerate(headers):
            key = header_map[h]
            cell = r[idx] if idx < len(r) else ""
            field_data[key] = cell
        cur.execute(
            "INSERT INTO roster (session_id, seq, field_data, sign_token) VALUES (?, ?, ?, ?)",
            (session_id, seq, json.dumps(field_data, ensure_ascii=False), uuid.uuid4().hex[:16]),
        )
        seq += 1
    cur.execute(
        "UPDATE sessions SET roster_match_field = ? WHERE id = ?",
        (match_field, session_id),
    )
    conn.commit()
    conn.close()
    return {
        "status": "imported",
        "count": seq,
        "match_field": match_field,
        "match_header": match_header,
    }


@router.get("/api/sessions/{session_id}/roster")
async def get_roster(session_id: str, user: dict = Depends(get_current_user)):
    """获取已导入的名单概览（条数 + 匹配列）。"""
    conn = get_db()
    cur = conn.cursor()
    row = _owned_session(cur, session_id, user)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    cur.execute("SELECT COUNT(*) AS cnt FROM roster WHERE session_id = ?", (session_id,))
    cnt = cur.fetchone()["cnt"]
    conn.close()
    return {
        "count": cnt,
        "match_field": row["roster_match_field"],
        "imported": cnt > 0,
    }


@router.get("/api/sessions/{session_id}/roster/qrcodes")
async def get_roster_qrcodes(session_id: str, request: Request, user: dict = Depends(get_current_user)):
    """管理员：返回本会话名单中每人的专属签到码（一人一码）。

    每条返回 seq / 显示名 / sign_token（用于拼签到 URL）/ 是否已签。
    """
    conn = get_db()
    cur = conn.cursor()
    row = _owned_session(cur, session_id, user)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    match_field = row["roster_match_field"]
    cur.execute(
        "SELECT seq, field_data, sign_token FROM roster WHERE session_id = ? ORDER BY seq ASC",
        (session_id,),
    )
    roster_rows = cur.fetchall()
    # 计算已签集合（按 match_field 值去空白相等匹配，与 reconcile 一致）
    signed_set = set()
    if match_field:
        cur.execute("SELECT field_data FROM signins WHERE session_id = ?", (session_id,))
        for r in cur.fetchall():
            fd = json.loads(r["field_data"])
            v = str(fd.get(match_field, "")).strip()
            if v:
                signed_set.add(v)
    conn.close()
    base_url = str(request.base_url).rstrip("/")
    items = []
    for r in roster_rows:
        fd = json.loads(r["field_data"])
        display = (str(fd.get(match_field, "")).strip() if match_field
                   else str(fd.get("name", "")).strip() or f"第{r['seq'] + 1}位")
        is_signed = bool(match_field) and (str(fd.get(match_field, "")).strip() in signed_set)
        items.append({
            "seq": r["seq"],
            "display": display,
            "sign_token": r["sign_token"],
            "signed": is_signed,
            "url": f"{base_url}/#/signin?session={session_id}&token={r['sign_token']}",
        })
    return {"count": len(items), "match_field": match_field, "items": items}


@router.get("/api/sessions/{session_id}/roster/token-info")
async def roster_token_info(session_id: str, token: str = ""):
    """公开接口：签到页判断当前 token 是否为名单专属码（一人一码）。

    是则返回绑定身份（显示名 + match_field），签到页据此锁定身份、展示确认页；
    否则返回 is_roster=false，走原表单流程。无需登录（签到页本身即公开）。
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    srow = cur.fetchone()
    if not srow:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    cur.execute(
        "SELECT field_data, sign_token FROM roster WHERE session_id = ? AND sign_token = ? LIMIT 1",
        (session_id, token),
    )
    rrow = cur.fetchone()
    if not rrow:
        conn.close()
        return {"is_roster": False}
    match_field = srow["roster_match_field"]
    fd = json.loads(rrow["field_data"])
    display = (str(fd.get(match_field, "")).strip() if match_field
               else str(fd.get("name", "")).strip() or "")
    conn.close()
    return {"is_roster": True, "display": display, "match_field": match_field}


@router.get("/api/sessions/{session_id}/reconcile")
async def reconcile(session_id: str, user: dict = Depends(get_current_user)):
    """签到后校对：对比名单与签到记录，产出 已到 / 未到 / 名单外 三类。

    - 已到：名单内且已签到（按 roster_match_field 匹配）
    - 未到：名单内但未签到
    - 名单外：签到了但不在名单（含未填写匹配字段的签到）
    """
    conn = get_db()
    cur = conn.cursor()
    row = _owned_session(cur, session_id, user)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    match_field = row["roster_match_field"]
    if not match_field:
        conn.close()
        raise HTTPException(status_code=400, detail="尚未导入名单或未指定匹配列，无法校对")

    fields_config = json.loads(row["fields_config"])
    match_label = next((f["label"] for f in fields_config if f["name"] == match_field), match_field)

    # 名单
    cur.execute("SELECT field_data FROM roster WHERE session_id = ? ORDER BY seq ASC", (session_id,))
    roster_rows = [json.loads(r["field_data"]) for r in cur.fetchall()]
    roster_keys = {}  # norm match value -> roster field_data
    for rd in roster_rows:
        v = str(rd.get(match_field, "")).strip()
        if v:
            roster_keys.setdefault(v, rd)

    # 签到
    cur.execute("SELECT field_data, sign_in_time FROM signins WHERE session_id = ? ORDER BY sign_in_time ASC", (session_id,))
    signin_rows = cur.fetchall()
    signin_by_key = {}  # norm match value -> signin record
    for sr in signin_rows:
        sd = json.loads(sr["field_data"])
        v = str(sd.get(match_field, "")).strip()
        signin_by_key.setdefault(v, (sd, sr["sign_in_time"]))

    # 已到 / 未到
    present, absent = [], []
    for rd in roster_rows:
        v = str(rd.get(match_field, "")).strip()
        if v and v in signin_by_key:
            sd, t = signin_by_key[v]
            rec = dict(rd)
            rec["_sign_in_time"] = t
            rec["_time_str"] = datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
            present.append(rec)
        else:
            absent.append(dict(rd))

    # 名单外：所有签到中匹配值不在名单集合内的（含空值）
    extra = []
    for sr in signin_rows:
        sd = json.loads(sr["field_data"])
        v = str(sd.get(match_field, "")).strip()
        if v not in roster_keys:
            rec = dict(sd)
            rec["_sign_in_time"] = sr["sign_in_time"]
            rec["_time_str"] = datetime.fromtimestamp(sr["sign_in_time"]).strftime("%Y-%m-%d %H:%M:%S")
            extra.append(rec)

    conn.close()
    return {
        "match_field": match_field,
        "match_field_label": match_label,
        "roster_total": len(roster_rows),
        "signin_total": len(signin_rows),
        "present": present,
        "absent": absent,
        "extra": extra,
        "counts": {
            "present": len(present),
            "absent": len(absent),
            "extra": len(extra),
        },
    }


@router.get("/api/sessions/{session_id}/reconcile/export")
async def export_reconcile(session_id: str, user: dict = Depends(get_current_user)):
    """导出校对结果为 CSV（带「校对状态」列：已到 / 未到 / 名单外）。"""
    conn = get_db()
    cur = conn.cursor()
    row = _owned_session(cur, session_id, user)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    match_field = row["roster_match_field"]
    if not match_field:
        conn.close()
        raise HTTPException(status_code=400, detail="尚未导入名单或未指定匹配列，无法导出")

    fields_config = json.loads(row["fields_config"])
    match_label = next((f["label"] for f in fields_config if f["name"] == match_field), match_field)
    labels = [f["label"] for f in fields_config if f["name"] != match_field]
    label_of = {f["name"]: f["label"] for f in fields_config}

    # 复用 reconcile 的计算逻辑
    cur.execute("SELECT field_data FROM roster WHERE session_id = ? ORDER BY seq ASC", (session_id,))
    roster_rows = [json.loads(r["field_data"]) for r in cur.fetchall()]
    roster_keys = {}
    for rd in roster_rows:
        v = str(rd.get(match_field, "")).strip()
        if v:
            roster_keys.setdefault(v, rd)
    cur.execute("SELECT field_data, sign_in_time FROM signins WHERE session_id = ? ORDER BY sign_in_time ASC", (session_id,))
    signin_rows = cur.fetchall()
    signin_by_key = {}
    for sr in signin_rows:
        sd = json.loads(sr["field_data"])
        v = str(sd.get(match_field, "")).strip()
        signin_by_key.setdefault(v, (sd, sr["sign_in_time"]))

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["校对状态", match_label] + labels + ["签到时间"])

    def _emit(status, data, sign_in_time=None):
        row_vals = [status, str(data.get(match_field, "")).strip()]
        for f in fields_config:
            if f["name"] == match_field:
                continue
            val = data.get(f["name"], "")
            if f["name"] == "id_card":
                val = mask_id_card(val)
            row_vals.append(val)
        row_vals.append(
            datetime.fromtimestamp(sign_in_time).strftime("%Y-%m-%d %H:%M:%S") if sign_in_time else ""
        )
        writer.writerow(row_vals)

    for rd in roster_rows:
        v = str(rd.get(match_field, "")).strip()
        if v and v in signin_by_key:
            sd, t = signin_by_key[v]
            _emit("已到", sd, t)
        else:
            _emit("未到", rd)
    for sr in signin_rows:
        sd = json.loads(sr["field_data"])
        v = str(sd.get(match_field, "")).strip()
        if v not in roster_keys:
            _emit("名单外", sd, sr["sign_in_time"])

    conn.close()
    output.seek(0)
    raw_name = f"reconcile_{row['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    ascii_name = f"reconcile_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    encoded_name = urllib.parse.quote(raw_name)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"
        }
    )


@router.get("/api/sessions/{session_id}/stats")
async def get_session_stats(session_id: str, user: dict = Depends(get_current_user)):
    """查看单个会话的签到概况（需登录）"""
    conn = get_db()
    cur = conn.cursor()
    # 1) 会话是否存在且当前用户有权访问
    row = _owned_session(cur, session_id, user)
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    # 2) 聚合签到数据
    cur.execute(
        "SELECT COUNT(*) AS cnt, MIN(sign_in_time) AS first_t, MAX(sign_in_time) AS last_t "
        "FROM signins WHERE session_id = ?",
        (session_id,),
    )
    row = cur.fetchone()
    conn.close()
    return {
        "session_id": session_id,
        "sign_in_count": row["cnt"],
        "first_sign_in": row["first_t"],
        "last_sign_in": row["last_t"],
    }
