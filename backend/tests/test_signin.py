"""submit_signin 核心逻辑单测：成功 / 复合键去重 / 强唯一字段去重 / 人数上限 / 时间窗口 / token 过期。"""
import time

import app as app_module

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
    # 同一复合键再次提交 -> 409
    r2 = _submit(client, sid, t, fd)
    assert r2.status_code == 409


def test_unique_field_employee_id(client):
    token = _login(client)
    sid = _create_session(client, token)
    t = _seed_token(sid)
    assert _submit(client, sid, t, {"name": "张三", "phone": "1", "employee_id": "E1"}).status_code == 200
    # 姓名/手机都不同，但工号相同 -> 仍判重复
    r2 = _submit(client, sid, t, {"name": "李四", "phone": "2", "employee_id": "E1"})
    assert r2.status_code == 409
    assert "工号" in r2.json()["detail"]


def test_capacity_limit(client):
    token = _login(client)
    sid = _create_session(client, token, max_signins=1)
    t = _seed_token(sid)
    assert _submit(client, sid, t, {"name": "张三", "phone": "1"}).status_code == 200
    r2 = _submit(client, sid, t, {"name": "李四", "phone": "2"})
    assert r2.status_code == 409
    assert "已满" in r2.json()["detail"]


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
