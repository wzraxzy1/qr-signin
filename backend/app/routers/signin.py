"""
公开签到提交路由（无需登录鉴权）。
拆分自原 app.py 的 /api/sessions/{session_id}/signin，单独成文件以突出其
"公开端点"的安全边界：相比同前缀的其它会话接口，本接口不要求登录。

并发安全（PRD 缺陷清单 P1：人数上限 TOCTOU 竞态）：
    临界区（去重 + 人数上限 + INSERT）必须在同一个「写事务」内原子完成。
    若用 SQLite 默认 deferred 事务，SELECT COUNT(*) 是读操作不拿写锁，
    直到 INSERT 才隐式开写事务——两个并发请求会同时通过 COUNT < max 检查，
    再各自 INSERT，导致签到人数超额。这里改用 BEGIN IMMEDIATE 在「检查」前
    就抢占写锁，将 Check→Use 的时间窗折叠为零。
"""
import os
import re
import time
import uuid
import json

from fastapi import APIRouter, Request, HTTPException

from ..config import TOKEN_GRACE_PERIOD
from ..db import get_db
from ..schemas import SignInSubmit

router = APIRouter()

# 仅允许微信内置浏览器提交签到（企业微信 wxwork 不在放行范围）。
# 注意：UA 可被伪造，此处只是"提高绕过成本"的震慑级防护，
# 与生产意义上"防作弊"一致（并非密码学级）。
_WECHAT_UA_RE = re.compile(r"micromessenger", re.IGNORECASE)


def _require_wechat(request: Request):
    """仅 production 环境强制要求微信内置浏览器 UA；开发/测试环境放行便于调试。

    绕过方式：非微信 UA 直接打 API 会被这里拦下（403），无法仅靠改前端绕过。
    """
    if os.getenv("APP_ENV", "production") != "production":
        return
    ua = request.headers.get("user-agent", "") or ""
    if not _WECHAT_UA_RE.search(ua):
        raise HTTPException(
            status_code=403,
            detail="请在微信中打开本页面后再签到（本签到仅支持微信内置浏览器）",
        )


class _RejectSignin(Exception):
    """临界区内用于统一回滚并转为 4xx 的轻量控制流。"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def try_persist_signin(conn, session_row, token, field_data, now, client_ip, device_id=""):
    """在调用方已开启的写事务内完成 去重 + 人数上限 + INSERT。

    不负责 BEGIN/COMMIT——事务边界由 submit_signin 统一控制，以保证原子性。
    成功返回 None；应拒绝时抛出 _RejectSignin(status_code, detail)。
    抽成独立函数是为了让并发 TOCTOU 回归测试能直接驱动真实代码路径。
    """
    cur = conn.cursor()

    # ============ 防作弊：同一设备同一会话只能成功签到一次 ============
    # 独立于身份去重：即便换 token（重扫新码）或换身份，只要 device_id 相同即拦截，
    # 堵住"同一台手机替多人签到"的漏洞。device_id 为空（旧前端/非浏览器）时跳过，
    # 退回原有的 token/身份去重，向后兼容。
    if device_id:
        cur.execute(
            "SELECT id FROM signins WHERE session_id = ? AND device_id = ?",
            (session_row["id"], device_id),
        )
        if cur.fetchone():
            raise _RejectSignin(
                409, "该设备已签到，请勿重复签到（如需为他人签到，请换一台设备）"
            )

    # ============ 反重复签到（多人共码语义）============
    # 产品规则：同一张二维码允许「多个不同的人」签到（大屏一码多人扫），
    # 只拦截「同一个人重复签到」。区分依据是会话是否配置了表单字段：
    #   - 匿名会话（fields_config 为空）→ 无法识别身份 → 同一 token 只能成功一次；
    #   - 多人会话（配置了字段）→ 按身份去重，同一身份（含跨 token 重扫）重复签才拦。
    try:
        fields_config = json.loads(session_row["fields_config"] or "[]")
    except (ValueError, TypeError):
        fields_config = []
    has_form_fields = bool(fields_config)

    def _token_already_used():
        """同一 token 在同一 session 是否已成功签到过。"""
        cur.execute(
            "SELECT id FROM signins WHERE session_id = ? AND token = ?",
            (session_row["id"], token),
        )
        return cur.fetchone() is not None

    if not has_form_fields:
        # 匿名会话：一码一签，提交什么内容都一样（恶意伪造字段也拦）。
        if _token_already_used():
            raise _RejectSignin(
                409, "该二维码已签到，请勿重复签到（如需重签请重新扫描）"
            )
        return _insert_signin(conn, session_row, token, field_data, now, client_ip, device_id)

    # ---- 多人会话：身份去重 ----
    # 身份候选字段非空值 -> 复合键去重
    identity_candidates = ["employee_id", "phone", "name"]
    key_fields = [
        c for c in identity_candidates
        if c in field_data and str(field_data.get(c, "")).strip() != ""
    ]
    if not key_fields:
        # 没有任何标准身份字段被填写：退而用「其它非空字段」做复合去重
        # （如只配置了"部门"下拉的会话，不同部门视为不同人）。
        non_empty = {
            k: v for k, v in field_data.items()
            if str(v).strip() != ""
        }
        if not non_empty:
            # 什么都没填（全空/空对象）-> 无法识别身份 -> 视同匿名，一码一签
            if _token_already_used():
                raise _RejectSignin(
                    409, "该二维码已签到，请勿重复签到（如需重签请重新扫描）"
                )
            return _insert_signin(conn, session_row, token, field_data, now, client_ip, device_id)
        key_fields = list(non_empty.keys())

    if key_fields:
        where = " AND ".join("json_extract(field_data, ?) = ?" for _ in key_fields)
        params = [session_row["id"]]
        for kf in key_fields:
            params.append(f"$.{kf}")
            params.append(str(field_data[kf]))
        cur.execute(
            f"SELECT id FROM signins WHERE session_id = ? AND {where}",
            params,
        )
        if cur.fetchone():
            raise _RejectSignin(409, "您已签到，请勿重复签到")

    # 单字段唯一性（工号 / 身份证号 / 学号）。
    # 若任一字段已存在于本会话其它签到记录则判重复，兜住复合键漏判的情况
    # （如同工号但姓名/手机填错）。
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
            (session_row["id"], f"$.{uf}", str(val)),
        )
        if cur.fetchone():
            raise _RejectSignin(409, f"该{label}已签到，请勿重复签到")

    return _insert_signin(conn, session_row, token, field_data, now, client_ip, device_id)


def _insert_signin(conn, session_row, token, field_data, now, client_ip, device_id=""):
    """人数上限检查 + INSERT（事务由调用方统一 COMMIT/ROLLBACK）。

    人数上限与 INSERT 同处一个写事务，原子执行，杜绝并发超额（TOCTOU 修复点）。
    返回 signin_id。
    """
    cur = conn.cursor()
    max_signins = session_row["max_signins"]
    if max_signins is not None:
        cur.execute(
            "SELECT COUNT(*) as cnt FROM signins WHERE session_id = ?",
            (session_row["id"],),
        )
        if cur.fetchone()["cnt"] >= max_signins:
            raise _RejectSignin(409, f"签到人数已满（上限 {max_signins} 人）")

    signin_id = str(uuid.uuid4())[:8]
    cur.execute(
        """INSERT INTO signins (id, session_id, token, field_data, sign_in_time, ip_address, device_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (signin_id, session_row["id"], token, json.dumps(field_data, ensure_ascii=False), now, client_ip, device_id or None),
    )
    return signin_id


@router.post("/api/sessions/{session_id}/signin")
async def submit_signin(session_id: str, data: SignInSubmit, request: Request):
    """提交签到"""
    # 仅允许微信内置浏览器提交（企业微信不在放行范围）；非生产环境放行便于调试
    _require_wechat(request)
    conn = get_db()
    # 手动控制事务：默认 isolation_level="" 会在首条 DML 隐式 BEGIN（deferred），
    # 与下方显式 BEGIN IMMEDIATE 冲突。设为 None 后由我们完全掌控事务边界。
    conn.isolation_level = None
    cur = conn.cursor()

    # ============ 前置只读校验（不涉及 signins 写竞争，无需锁）============
    cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session not found")
    if row["status"] != "active":
        conn.close()
        raise HTTPException(status_code=400, detail="签到已关闭")

    now = time.time()
    if row["start_at"] and now < row["start_at"]:
        conn.close()
        raise HTTPException(status_code=403, detail="签到尚未开始")
    if row["expires_at"] and now > row["expires_at"]:
        conn.close()
        raise HTTPException(status_code=403, detail="签到已结束")

    # Token 有效性校验（只读）
    interval = row["refresh_interval"]
    token_validity = interval + TOKEN_GRACE_PERIOD
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

    # ============ 临界区：去重 + 人数上限 + 写入（必须原子提交）============
    # 用 BEGIN IMMEDIATE 在「检查」之前就抢占写锁，彻底消除 TOCTOU 竞态：
    # 两个并发请求不会同时通过 COUNT < max 检查后再各自 INSERT 导致超额 / 重复签到。
    conn.execute("BEGIN IMMEDIATE")
    try:
        client_ip = request.client.host if request.client else "unknown"
        try_persist_signin(conn, row, data.token, data.field_data, now, client_ip, data.device_id)
        conn.execute("COMMIT")
        conn.close()
        return {"status": "success", "sign_in_time": now}
    except _RejectSignin as rj:
        # 拒绝类（重复 / 已满）：回滚事务，转为对应 4xx
        conn.execute("ROLLBACK")
        conn.close()
        raise HTTPException(status_code=rj.status_code, detail=rj.detail)
    except Exception:
        # 任何意外异常都回滚，避免留下半开事务把后续请求全卡在 busy_timeout 上
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        conn.close()
        raise
