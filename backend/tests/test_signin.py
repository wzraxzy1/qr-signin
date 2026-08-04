"""submit_signin 核心逻辑单测：成功 / 复合键去重 / 强唯一字段去重 / 人数上限 / 时间窗口 / token 过期。"""
import threading
import time

import app as app_module
from fastapi.testclient import TestClient

ADMIN = ("admin", "admin123")


def _login(client):
    r = client.post("/api/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _create_session(client, token, **overrides):
    payload = {
        "name": "test",
        "refresh_interval": 10,
        "fields_config": [
            {"name": "name", "label": "姓名", "type": "text", "required": True},
            {"name": "phone", "label": "手机号", "type": "tel", "required": True},
            {"name": "employee_id", "label": "工号", "type": "text", "required": False},
        ],
        "start_at": None,
        "expires_at": None,
        "max_signins": None,
    }
    payload.update(overrides)
    r = client.post("/api/sessions", json=payload,
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _seed_token(session_id, token_value="TKN", age=0):
    conn = app_module.get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO qr_tokens (id, session_id, token, created_at) VALUES (?,?,?,?)",
        (f"qt_{token_value}", session_id, token_value, time.time() - age),
    )
    conn.commit()
    conn.close()
    return token_value


def _submit(client, session_id, token, field_data):
    return client.post(
        f"/api/sessions/{session_id}/signin",
        json={"token": token, "field_data": field_data},
    )


def test_signin_success(client):
    token = _login(client)
    sid = _create_session(client, token)
    t = _seed_token(sid)
    r = _submit(client, sid, t, {"name": "张三", "phone": "13800000000"})
    assert r.status_code == 200, r.text


def test_dedup_composite_key(client):
    token = _login(client)
    sid = _create_session(client, token)
    t = _seed_token(sid)
    fd = {"name": "张三", "phone": "13800000000"}
    assert _submit(client, sid, t, fd).status_code == 200
    # 同一复合键、换新 token(重新扫码)再次提交 -> 仍 409（跨 token 身份去重）
    t2 = _seed_token(sid, token_value="TKN2")
    r2 = _submit(client, sid, t2, fd)
    assert r2.status_code == 409


def test_unique_field_employee_id(client):
    token = _login(client)
    sid = _create_session(client, token)
    t = _seed_token(sid)
    assert _submit(client, sid, t, {"name": "张三", "phone": "1", "employee_id": "E1"}).status_code == 200
    # 姓名/手机都不同，但工号相同 -> 换新 token 后仍判重复
    t2 = _seed_token(sid, token_value="TKN2")
    r2 = _submit(client, sid, t2, {"name": "李四", "phone": "2", "employee_id": "E1"})
    assert r2.status_code == 409
    assert "工号" in r2.json()["detail"]


def test_anonymous_token_single_use(client):
    """匿名签到(表单无任何字段)：同一 token 成功后不可再次使用，防"返回上一页不扫码再签"。"""
    token = _login(client)
    sid = _create_session(client, token, fields_config=[])
    t = _seed_token(sid)
    # 无字段表单：field_data 传空对象
    assert _submit(client, sid, t, {}).status_code == 200
    # 同一 token 再次提交(相当于返回上一页重签) -> 409
    r2 = _submit(client, sid, t, {})
    assert r2.status_code == 409
    assert "已签到" in r2.json()["detail"]
    # 新 token(重新扫码) 允许签到
    t2 = _seed_token(sid, token_value="TKN2")
    assert _submit(client, sid, t2, {}).status_code == 200


def test_token_single_use_universal_fields(client):
    """回归（用户报"返回上一页不扫码再次签到"）：带字段表单同 token 二次提交，
    即使改了字段值也必须 409——之前只查身份去重，改任意字段即可绕过。"""
    token = _login(client)
    sid = _create_session(client, token)
    t = _seed_token(sid)
    assert _submit(client, sid, t, {"name": "张三", "phone": "1"}).status_code == 200
    # 返回上一页后改了手机号再提交（身份字段不同，身份去重拦不住）
    r2 = _submit(client, sid, t, {"name": "张三", "phone": "2"})
    assert r2.status_code == 409
    assert "该二维码已签到" in r2.json()["detail"]
    # 再补一刀：填全新身份也拦（同 token 一律单次使用）
    r3 = _submit(client, sid, t, {"name": "李四", "phone": "3"})
    assert r3.status_code == 409


def test_token_single_use_anonymous_to_fields(client):
    """回归：匿名签到成功后，同一 token 改带字段再次提交 -> 409（匿名↔带字段互转绕过）。"""
    token = _login(client)
    sid = _create_session(client, token, fields_config=[])
    t = _seed_token(sid)
    assert _submit(client, sid, t, {}).status_code == 200
    r2 = _submit(client, sid, t, {"name": "张三", "phone": "1"})
    assert r2.status_code == 409
    assert "该二维码已签到" in r2.json()["detail"]


def test_capacity_limit(client):
    token = _login(client)
    sid = _create_session(client, token, max_signins=1)
    t = _seed_token(sid)
    assert _submit(client, sid, t, {"name": "张三", "phone": "1"}).status_code == 200
    # 满员后用新 token(重新扫码)提交 -> 409「已满」
    t2 = _seed_token(sid, token_value="TKN2")
    r2 = _submit(client, sid, t2, {"name": "李四", "phone": "2"})
    assert r2.status_code == 409
    assert "已满" in r2.json()["detail"]


def test_capacity_limit_no_toctou_under_concurrency(client):
    """并发竞态回归：max_signins=1 时，两个并发请求必须恰好 1 个成功、1 个 409。

    若临界区未用 BEGIN IMMEDIATE 原子化（TOCTOU），两个请求会同时通过
    COUNT < max 检查后再各自 INSERT，导致超额（2 个成功）——本用例即失败。
    修复后 BEGIN IMMEDIATE 抢占写锁，第二个请求必然阻塞到第一个 COMMIT，
    再看到 COUNT>=max 被拒，结果确定。
    """
    token = _login(client)
    sid = _create_session(client, token, max_signins=1)
    # 两个线程各用各的 token（否则统一“同 token 单次使用”规则会先拦截，
    # 测不到人数上限的并发竞态）
    _seed_token(sid, token_value="TKN1")
    _seed_token(sid, token_value="TKN2")

    # 两个独立 TestClient（各自持有独立 ASGI portal，避免单 client 跨线程不安全），
    # 共享同一个 app 与同一份临时 DB 文件。
    c1 = TestClient(app_module.app)
    c2 = TestClient(app_module.app)

    barrier = threading.Barrier(2, timeout=5)
    results = []
    errors = []

    def worker(client_inst, token_value, name):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            return
        try:
            r = client_inst.post(
                f"/api/sessions/{sid}/signin",
                json={"token": token_value, "field_data": {"name": name, "phone": "1"}},
            )
            results.append(r.status_code)
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    t1 = threading.Thread(target=worker, args=(c1, "TKN1", "张三"))
    t2 = threading.Thread(target=worker, args=(c2, "TKN2", "李四"))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not errors, errors
    assert sorted(results) == [200, 409], f"并发结果应为 1 成功 1 拒绝，实际: {results}"
    # 落库必须恰好 1 条，绝不超额
    conn = app_module.get_db()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM signins WHERE session_id = ?", (sid,)
    ).fetchone()[0]
    conn.close()
    assert cnt == 1, f"并发后签到记录数应为 1，实际 {cnt}（TOCTOU 竞态未修复）"


def test_time_window_not_started(client):
    token = _login(client)
    sid = _create_session(client, token, start_at=time.time() + 3600)
    t = _seed_token(sid)
    r = _submit(client, sid, t, {"name": "张三", "phone": "1"})
    assert r.status_code == 403
    assert "尚未开始" in r.json()["detail"]


def test_time_window_ended(client):
    token = _login(client)
    sid = _create_session(client, token, expires_at=time.time() - 3600)
    t = _seed_token(sid)
    r = _submit(client, sid, t, {"name": "张三", "phone": "1"})
    assert r.status_code == 403
    assert "已结束" in r.json()["detail"]


def test_token_expired(client):
    token = _login(client)
    sid = _create_session(client, token)
    # interval(10)+grace(120)=130s，age=200 超过有效期
    t = _seed_token(sid, token_value="OLD", age=200)
    r = _submit(client, sid, t, {"name": "张三", "phone": "1"})
    assert r.status_code == 403
    assert "过期" in r.json()["detail"]


def test_export_masks_id_card(client):
    token = _login(client)
    # 会话字段配置需含 id_card，导出才会包含该列（与 UI 默认字段一致）
    fields = [
        {"name": "name", "label": "姓名", "type": "text", "required": True},
        {"name": "phone", "label": "手机号", "type": "tel", "required": True},
        {"name": "id_card", "label": "身份证号", "type": "text", "required": False},
    ]
    sid = _create_session(client, token, fields_config=fields)
    t = _seed_token(sid)
    fd = {"name": "张三", "phone": "13800000000", "id_card": "330102199003078888"}
    assert _submit(client, sid, t, fd).status_code == 200
    r = client.get(f"/api/sessions/{sid}/export",
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.text
    assert "330102199003078888" not in body   # 明文身份证号不得出现在导出中
    assert "3301**********8888" in body        # 应出现脱敏后的形式
