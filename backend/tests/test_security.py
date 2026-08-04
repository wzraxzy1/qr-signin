"""安全基元单测：密码哈希、token 签发/校验/失效。"""
import app as app_module


def test_hash_password_roundtrip():
    h = app_module.hash_password("secret123")
    assert h != "secret123"
    assert app_module.verify_password("secret123", h)
    assert not app_module.verify_password("wrong", h)


def test_hash_password_salt_is_random():
    a = app_module.hash_password("x")
    b = app_module.hash_password("x")
    assert a != b  # 每次都应带随机 salt


def test_token_roundtrip_and_expiry():
    tok = app_module.create_token("u1", "admin", 0, expires_hours=1)
    p = app_module.verify_token(tok)
    assert p["uid"] == "u1"
    assert p["role"] == "admin"
    # 已过期的 token 必须被拒
    tok2 = app_module.create_token("u1", "admin", 0, expires_hours=-1)
    assert app_module.verify_token(tok2) is None


def test_token_signature_tamper_rejected():
    tok = app_module.create_token("u1", "admin")
    payload, sig = tok.rsplit(".", 1)
    bad = payload + "." + ("0" * len(sig))
    assert app_module.verify_token(bad) is None


def test_token_carries_password_version():
    tok = app_module.create_token("u1", "admin", password_version=3)
    p = app_module.verify_token(tok)
    assert p["pv"] == 3
