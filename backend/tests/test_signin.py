"""submit_signin 核心逻辑单测：成功 / 复合键去重 / 强唯一字段去重 / 人数上限 / 时间窗口 / token 过期。"""
import json
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


def _submit(client, session_id, token, field_data, device_id=""):
    return client.post(
        f"/api/sessions/{session_id}/signin",
        json={"token": token, "field_data": field_data, "device_id": device_id},
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


def test_multi_user_same_qr_code_allowed(client):
    """多人共码核心回归（用户问"多个用户扫同一个二维码会不会冲突"）：
    带字段会话，同一张二维码(token)允许多个不同身份签到；同一身份重复签(409)。"""
    token = _login(client)
    sid = _create_session(client, token)
    t = _seed_token(sid)
    # 第 1 人
    assert _submit(client, sid, t, {"name": "张三", "phone": "1"}).status_code == 200
    # 第 2 人（同一 token、不同身份）-> 必须成功，不能互相挤掉
    assert _submit(client, sid, t, {"name": "李四", "phone": "2"}).status_code == 200
    # 第 3 人
    assert _submit(client, sid, t, {"name": "王五", "phone": "3"}).status_code == 200
    # 同一人(完全同身份)重复签 -> 409（同 token / 跨 token 重扫均拦）
    assert _submit(client, sid, t, {"name": "张三", "phone": "1"}).status_code == 409
    t2 = _seed_token(sid, token_value="TKN2")
    assert _submit(client, sid, t2, {"name": "张三", "phone": "1"}).status_code == 409
    # 语义边界：改个别字段(如改手机号) -> 复合键不同且无强唯一字段 -> 视为"不同人"放行。
    # 后端无法区分"同一人改号"与"同名不同人"，属多人共码的固有边界，
    # 同一设备重复进入由前端 localStorage 守卫兜底；若要严格拦，会话需配置
    # 强唯一字段(工号/身份证号/学号)，见 test_unique_field_employee_id。
    assert _submit(client, sid, t, {"name": "张三", "phone": "9"}).status_code == 200
    # 落库 4 人（张三/李四/王五 + 张三改号）
    conn = app_module.get_db()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM signins WHERE session_id = ?", (sid,)
    ).fetchone()[0]
    conn.close()
    assert cnt == 4


def test_anonymous_session_rejects_fabricated_fields(client):
    """匿名会话(无字段)即使伪造带字段提交，同一 token 二次仍 409（一码一签）。"""
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


def test_device_single_use_per_session(client):
    """防作弊核心回归：同一 device_id 在同一会话内只能成功签到一次，
    即便换 token（重扫新码）或换身份也拦截。"""
    token = _login(client)
    sid = _create_session(client, token)
    t = _seed_token(sid)
    # 设备 D1 首次签到（身份 A）
    assert _submit(client, sid, t, {"name": "张三", "phone": "1"}, device_id="D1").status_code == 200
    # 同设备 D1、换新 token、换身份 B -> 必须 409「该设备已签到」
    t2 = _seed_token(sid, token_value="TKN2")
    r2 = _submit(client, sid, t2, {"name": "李四", "phone": "2"}, device_id="D1")
    assert r2.status_code == 409
    assert "该设备已签到" in r2.json()["detail"]


def test_different_device_allowed(client):
    """防作弊边界：不同 device_id 视为不同设备，应放行（不要误伤多台手机）。"""
    token = _login(client)
    sid = _create_session(client, token)
    t = _seed_token(sid)
    assert _submit(client, sid, t, {"name": "张三", "phone": "1"}, device_id="D1").status_code == 200
    # 设备 D2（另一台手机）签到 -> 应成功
    assert _submit(client, sid, t, {"name": "李四", "phone": "2"}, device_id="D2").status_code == 200
    conn = app_module.get_db()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM signins WHERE session_id = ?", (sid,)
    ).fetchone()[0]
    conn.close()
    assert cnt == 2


def test_anonymous_session_device_single_use(client):
    """匿名会话 + 设备指纹：同一设备即便换 token 重扫也被拦（旧逻辑下换 token 可再签）。"""
    token = _login(client)
    sid = _create_session(client, token, fields_config=[])
    t = _seed_token(sid)
    assert _submit(client, sid, t, {}, device_id="D1").status_code == 200
    # 同设备、换 token -> 409「该设备已签到」
    t2 = _seed_token(sid, token_value="TKN2")
    r2 = _submit(client, sid, t2, {}, device_id="D1")
    assert r2.status_code == 409
    assert "该设备已签到" in r2.json()["detail"]
    # 不同设备、换 token -> 放行
    assert _submit(client, sid, t2, {}, device_id="D2").status_code == 200


def test_empty_device_id_skips_device_check(client):
    """兼容：未传 device_id（旧前端/非浏览器）时跳过设备去重，退回原有 token/身份去重。"""
    token = _login(client)
    sid = _create_session(client, token, fields_config=[])
    t = _seed_token(sid)
    assert _submit(client, sid, t, {}).status_code == 200
    # 未传 device_id、换 token -> 走匿名一码一签逻辑，新 token 允许
    t2 = _seed_token(sid, token_value="TKN2")
    assert _submit(client, sid, t2, {}).status_code == 200


def test_wechat_only_rejects_non_wechat_in_production(client):
    """仅微信打开：production 环境下，非微信 UA 提交被 403 拦下；微信 UA 放行。

    通过临时把 APP_ENV 切到 production 驱动真实校验分支；
    开发/测试环境（默认 APP_ENV=test）不触发，避免日常测试被误伤。
    """
    import os
    token = _login(client)
    sid = _create_session(client, token)
    t = _seed_token(sid)
    old = os.environ.get("APP_ENV")
    os.environ["APP_ENV"] = "production"
    try:
        # 非微信 UA（TestClient 默认 UA 不含 MicroMessenger）-> 403
        r = _submit(client, sid, t, {"name": "张三", "phone": "1"})
        assert r.status_code == 403, r.text
        assert "微信" in r.json()["detail"]
        # 微信 UA -> 放行（不同身份，避免被身份去重拦）
        r2 = client.post(
            f"/api/sessions/{sid}/signin",
            json={"token": t, "field_data": {"name": "李四", "phone": "2"}},
            headers={"user-agent": "Mozilla/5.0 MicroMessenger/8.0.40"},
        )
        assert r2.status_code == 200, r2.text
    finally:
        if old is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = old


def _import_roster_csv(client, token, sid, csv_text, match_field):
    return client.post(
        f"/api/sessions/{sid}/roster",
        files={"file": ("roster.csv", csv_text.encode("utf-8-sig"), "text/csv")},
        data={"match_field": match_field},
        headers={"Authorization": f"Bearer {token}"},
    )


def _stored_signins(client, sid):
    conn = app_module.get_db()
    cur = conn.cursor()
    cur.execute("SELECT field_data, roster_token FROM signins WHERE session_id = ?", (sid,))
    rows = cur.fetchall()
    conn.close()
    return rows


def test_roster_per_person_qr_binds_identity_and_single_use(client):
    """一人一码：名单专属码绑定身份（忽略提交字段）、且只能成功一次（杜绝照片分享冒签）。"""
    token = _login(client)
    sid = _create_session(client, token)
    csv = "name,phone,employee_id\n张三,13800000001,1001\n李四,13800000002,1002\n"
    r = _import_roster_csv(client, token, sid, csv, "employee_id")
    assert r.status_code == 200, r.text

    # 取出每人专属码
    q = client.get(f"/api/sessions/{sid}/roster/qrcodes",
                   headers={"Authorization": f"Bearer {token}"}).json()
    assert q["count"] == 2
    tokens = {it["display"]: it["sign_token"] for it in q["items"]}
    t_zhang, t_li = tokens["1001"], tokens["1002"]

    # 张三用自己专属码签到（提交空字段，身份应由后端按名单绑定）
    r1 = _submit(client, sid, t_zhang, {}, device_id="D1")
    assert r1.status_code == 200, r1.text
    rows = _stored_signins(client, sid)
    assert len(rows) == 1
    assert json.loads(rows[0]["field_data"])["employee_id"] == "1001"  # 身份被绑定
    assert rows[0]["roster_token"] == t_zhang

    # 复用张三专属码（换设备 D2）→ 该码已使用，409
    r2 = _submit(client, sid, t_zhang, {}, device_id="D2")
    assert r2.status_code == 409
    assert "该签到码已使用" in r2.json()["detail"]

    # 李四用自己专属码（不同设备 D3）→ 放行
    r3 = _submit(client, sid, t_li, {}, device_id="D3")
    assert r3.status_code == 200, r3.text

    # 公开 token-info：张三专属码 is_roster=true；随机 token → false
    info = client.get(f"/api/sessions/{sid}/roster/token-info?token={t_zhang}").json()
    assert info["is_roster"] is True
    assert info["display"] == "1001"
    info2 = client.get(f"/api/sessions/{sid}/roster/token-info?token=random_nope").json()
    assert info2["is_roster"] is False


def test_shared_qr_still_works_for_roster_session(client):
    """名单会话仍可走共享二维码（qr_tokens）路径，旧逻辑不被破坏。"""
    token = _login(client)
    sid = _create_session(client, token)
    csv = "name,employee_id\n张三,1001\n"
    assert _import_roster_csv(client, token, sid, csv, "employee_id").status_code == 200
    t = _seed_token(sid)  # 共享码
    r = _submit(client, sid, t, {"name": "王五", "employee_id": "1001"}, device_id="DX")
    assert r.status_code == 200, r.text
