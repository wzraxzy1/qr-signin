"""登录限流单测：连续错误触发 429；锁定期间正确密码也被拒；成功后计数清零。"""
import app as app_module

ADMIN = ("admin", "admin123")


def _login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_wrong_password_triggers_rate_limit(client):
    app_module._login_fail.clear()
    for _ in range(5):
        r = _login(client, ADMIN[0], "wrongpass")
        assert r.status_code == 401, r.text
    r6 = _login(client, ADMIN[0], "wrongpass")
    assert r6.status_code == 429
    assert "频繁" in r6.json()["detail"]


def test_lock_blocks_valid_password(client):
    app_module._login_fail.clear()
    for _ in range(5):
        _login(client, ADMIN[0], "wrongpass")
    # 锁定后即便正确密码也返回 429（而非 200）
    r = _login(client, ADMIN[0], ADMIN[1])
    assert r.status_code == 429


def test_success_clears_failures(client):
    app_module._login_fail.clear()
    for _ in range(4):
        _login(client, ADMIN[0], "wrongpass")
    # 第 5 次用正确密码应成功并清零计数
    r = _login(client, ADMIN[0], ADMIN[1])
    assert r.status_code == 200, r.text
    # 清零后一次错误不应立即触发限流（重新从 1 开始）
    r2 = _login(client, ADMIN[0], "wrongpass")
    assert r2.status_code == 401
