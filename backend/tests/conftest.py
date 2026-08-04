"""pytest 公共夹具：用临时目录的 SQLite 跑测试，绝不触碰生产 signin.db。"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# 必须在 import app 之前把 DB 指到临时目录（app.py 在导入时计算 DB_PATH）
_TMPDIR = tempfile.mkdtemp(prefix="qrsignin_test_")
os.environ["RENDER_DATA_DIR"] = _TMPDIR
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "admin123")
os.environ.setdefault("APP_ENV", "test")  # 避免触发 SECRET_KEY 生产强制校验

import app as app_module  # noqa: E402


@pytest.fixture(scope="session")
def app():
    app_module.init_db()
    return app_module.app


@pytest.fixture(scope="function", autouse=True)
def _reset_tables(app):
    """每个测试前清空所有业务表并重新播种管理员，保证用例互相隔离。"""
    conn = app_module.get_db()
    cur = conn.cursor()
    for t in ("signins", "qr_tokens", "sessions", "users"):
        cur.execute(f"DELETE FROM {t}")
    conn.commit()
    conn.close()
    app_module.init_db()
    yield


@pytest.fixture
def client(app):
    return TestClient(app)
