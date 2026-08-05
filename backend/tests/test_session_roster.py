"""名单导入与签到后校对单测：
- 导入 CSV 名单（指定匹配列 employee_id），reconcile 正确拆分 已到/未到/名单外；
- 导入 XLSX 同样正确；
- 重复导入为替换式（旧名单被清空）；
- 匹配列在名单表头中找不到 -> 400；
- 未导入名单就校对 -> 400；
- 普通 admin 不能访问他人会话的名单/校对接口（404）。
"""
import io

import openpyxl

import app as app_module


SUPER = ("admin", "admin123")
H = lambda tok: {"Authorization": f"Bearer {tok}"}

FIELDS = [
    {"name": "name", "label": "姓名", "type": "text", "required": True},
    {"name": "phone", "label": "手机号", "type": "tel", "required": True},
    {"name": "employee_id", "label": "工号", "type": "text", "required": False},
]


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
        json={"name": name, "fields_config": FIELDS},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _insert_signin(session_id, employee_id, name, phone, t):
    """直接写签到记录，绕过 token 校验，便于控制字段与签到时间。"""
    from app.crypto import hash_password  # noqa: F401 仅确保依赖可用
    import json as _json
    conn = app_module.get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO signins (id, session_id, token, field_data, sign_in_time, ip_address) VALUES (?,?,?,?,?,?)",
        (
            f"s_{employee_id}_{t}",
            session_id,
            "tok",
            _json.dumps({"name": name, "phone": phone, "employee_id": employee_id}, ensure_ascii=False),
            t,
            "1.2.3.4",
        ),
    )
    conn.commit()
    conn.close()


def _csv_bytes(headers, rows):
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8-sig")


def _xlsx_bytes(headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _upload_roster(client, token, session_id, content, filename, match_field):
    files = {"file": (filename, content, "application/octet-stream")}
    data = {"match_field": match_field}
    return client.post(f"/api/sessions/{session_id}/roster", files=files, data=data, headers=H(token))


def test_import_csv_and_reconcile(client):
    tok = _login(client, *SUPER)
    sid = _make_session(client, tok)

    headers = ["姓名", "手机号", "工号"]
    rows = [
        ["张三", "13800000001", "E001"],
        ["李四", "13800000002", "E002"],
        ["王五", "13800000003", "E003"],  # 仅名单内有，未签到 -> 未到
    ]
    r = _upload_roster(client, tok, sid, _csv_bytes(headers, rows), "roster.csv", "employee_id")
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 3

    # 签到：E001、E002 已到；E004 不在名单 -> 名单外
    _insert_signin(sid, "E001", "张三", "13800000001", 1000.0)
    _insert_signin(sid, "E002", "李四", "13800000002", 1001.0)
    _insert_signin(sid, "E004", "赵六", "13800000004", 1002.0)

    rc = client.get(f"/api/sessions/{sid}/reconcile", headers=H(tok))
    assert rc.status_code == 200, rc.text
    data = rc.json()
    assert data["counts"]["present"] == 2
    assert data["counts"]["absent"] == 1
    assert data["counts"]["extra"] == 1
    present_ids = {row["employee_id"] for row in data["present"]}
    assert present_ids == {"E001", "E002"}
    absent_ids = {row["employee_id"] for row in data["absent"]}
    assert absent_ids == {"E003"}
    extra_ids = {row["employee_id"] for row in data["extra"]}
    assert extra_ids == {"E004"}


def test_import_xlsx_and_reconcile(client):
    tok = _login(client, *SUPER)
    sid = _make_session(client, tok)

    headers = ["姓名", "手机号", "工号"]
    rows = [["张三", "13800000001", "E001"], ["李四", "13800000002", "E002"]]
    r = _upload_roster(client, tok, sid, _xlsx_bytes(headers, rows), "roster.xlsx", "employee_id")
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2

    _insert_signin(sid, "E001", "张三", "13800000001", 1000.0)
    data = client.get(f"/api/sessions/{sid}/reconcile", headers=H(tok)).json()
    assert data["counts"]["present"] == 1
    assert data["counts"]["absent"] == 1
    assert data["counts"]["extra"] == 0


def test_reimport_replaces(client):
    tok = _login(client, *SUPER)
    sid = _make_session(client, tok)

    _upload_roster(client, tok, sid, _csv_bytes(["工号"], [["E001"], ["E002"]]), "a.csv", "employee_id")
    _upload_roster(client, tok, sid, _csv_bytes(["工号"], [["E009"]]), "b.csv", "employee_id")

    info = client.get(f"/api/sessions/{sid}/roster", headers=H(tok)).json()
    assert info["count"] == 1  # 第二次导入清空了第一次


def test_match_field_not_in_headers(client):
    tok = _login(client, *SUPER)
    sid = _make_session(client, tok)
    # 名单表头没有「工号」列，却指定匹配列 employee_id
    r = _upload_roster(client, tok, sid, _csv_bytes(["姓名", "手机号"], [["张三", "138"]]), "r.csv", "employee_id")
    assert r.status_code == 400
    assert "找不到对应表头" in r.json()["detail"]


def test_reconcile_without_roster(client):
    tok = _login(client, *SUPER)
    sid = _make_session(client, tok)
    r = client.get(f"/api/sessions/{sid}/reconcile", headers=H(tok))
    assert r.status_code == 400
    assert "尚未导入名单" in r.json()["detail"]


def test_ownership_roster_404(client):
    super_tok = _login(client, *SUPER)
    _create_admin(client, super_tok, "admin_a")
    _create_admin(client, super_tok, "admin_b")
    a_tok = _login(client, "admin_a")
    b_tok = _login(client, "admin_b")
    sid = _make_session(client, a_tok, "A会话")

    # admin_b 既不能导入也不能读取/校对 admin_a 的名单
    assert _upload_roster(client, b_tok, sid, _csv_bytes(["工号"], [["E001"]]), "r.csv", "employee_id").status_code == 404
    assert client.get(f"/api/sessions/{sid}/roster", headers=H(b_tok)).status_code == 404
    assert client.get(f"/api/sessions/{sid}/reconcile", headers=H(b_tok)).status_code == 404
    # admin_a 自己可以
    assert client.get(f"/api/sessions/{sid}/roster", headers=H(a_tok)).status_code == 200
