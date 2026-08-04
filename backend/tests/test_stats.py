"""get_session_stats 单测：返回签到概况，需登录；未带 token 应 401。"""
import app as app_module
from fastapi.testclient import TestClient

ADMIN = ("admin", "admin123")


def _login(client):
    r = client.post("/api/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _create_session(client, token):
    r = client.post(
        "/api/sessions",
        json={"name": "stats-test", "refresh_interval": 10, "fields_config": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_stats_returns_counts(client):
    token = _login(client)
    sid = _create_session(client, token)
    r = client.get(f"/api/sessions/{sid}/stats", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == sid
    assert body["sign_in_count"] == 0
    assert "first_sign_in" in body and "last_sign_in" in body


def test_stats_requires_auth(client):
    token = _login(client)
    sid = _create_session(client, token)
    r = client.get(f"/api/sessions/{sid}/stats")
    assert r.status_code == 401
