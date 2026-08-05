"""会话归属隔离单测：
- 普通 admin 只能看到/操作自己创建的会话；
- 超级管理员能看到全部会话，且每条带 created_by / created_by_username（创建者）；
- 普通 admin 访问他人会话（GET/PUT/DELETE/records/export/qr）一律 404；
- 超级管理员可访问任意会话。
"""
import app as app_module


SUPER = ("admin", "admin123")
H = lambda tok: {"Authorization": f"Bearer {tok}"}


def _login(client, username, password="pass123"):
    return client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]


def _create_admin(client, super_token, username, password="pass123"):
    r = client.post(
        "/api/users",
        headers=H(super_token),
        json={"username": username, "password": password, "role": "admin"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _make_session(client, token, name="测试会话"):
    r = client.post(
        "/api/sessions",
        headers=H(token),
        json={"name": name, "fields_config": []},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_admin_sees_only_own_sessions(client):
    super_tok = _login(client, *SUPER)
    _create_admin(client, super_tok, "admin_a")
    _create_admin(client, super_tok, "admin_b")
    a_tok = _login(client, "admin_a")
    b_tok = _login(client, "admin_b")

    a_sid = _make_session(client, a_tok, "A的会话")

    ra = client.get("/api/sessions", headers=H(a_tok))
    assert ra.status_code == 200
    a_ids = [s["id"] for s in ra.json()["sessions"]]
    assert a_sid in a_ids

    rb = client.get("/api/sessions", headers=H(b_tok))
    assert rb.status_code == 200
    b_ids = [s["id"] for s in rb.json()["sessions"]]
    assert a_sid not in b_ids


def test_super_admin_sees_all_with_creator(client):
    super_tok = _login(client, *SUPER)
    a_id = _create_admin(client, super_tok, "admin_a")
    b_id = _create_admin(client, super_tok, "admin_b")
    a_tok = _login(client, "admin_a")
    b_tok = _login(client, "admin_b")

    sa = _make_session(client, a_tok, "A会话")
    sb = _make_session(client, b_tok, "B会话")

    r = client.get("/api/sessions", headers=H(super_tok))
    assert r.status_code == 200
    sess = {s["id"]: s for s in r.json()["sessions"]}
    assert sa in sess and sb in sess
    assert sess[sa]["created_by_username"] == "admin_a"
    assert sess[sa]["created_by"] == a_id
    assert sess[sb]["created_by_username"] == "admin_b"
    assert sess[sb]["created_by"] == b_id


def test_admin_cannot_access_others_session(client):
    super_tok = _login(client, *SUPER)
    _create_admin(client, super_tok, "admin_a")
    _create_admin(client, super_tok, "admin_b")
    a_tok = _login(client, "admin_a")
    b_tok = _login(client, "admin_b")

    sa = _make_session(client, a_tok, "A会话")

    assert client.get(f"/api/sessions/{sa}", headers=H(b_tok)).status_code == 404
    assert client.put(f"/api/sessions/{sa}", headers=H(b_tok), json={"status": "closed"}).status_code == 404
    assert client.delete(f"/api/sessions/{sa}", headers=H(b_tok)).status_code == 404
    assert client.get(f"/api/sessions/{sa}/records", headers=H(b_tok)).status_code == 404
    assert client.get(f"/api/sessions/{sa}/export", headers=H(b_tok)).status_code == 404
    assert client.get(f"/api/sessions/{sa}/qr", headers=H(b_tok)).status_code == 404
    # admin_a 的会话本身不受影响（仍归 admin_a）
    assert client.get(f"/api/sessions/{sa}", headers=H(a_tok)).status_code == 200


def test_super_admin_can_access_any_session(client):
    super_tok = _login(client, *SUPER)
    _create_admin(client, super_tok, "admin_a")
    a_tok = _login(client, "admin_a")

    sa = _make_session(client, a_tok, "A会话")

    r = client.get(f"/api/sessions/{sa}", headers=H(super_tok))
    assert r.status_code == 200
    assert r.json()["created_by_username"] == "admin_a"
    # 超级管理员可删除任意会话
    assert client.delete(f"/api/sessions/{sa}", headers=H(super_tok)).status_code == 200
