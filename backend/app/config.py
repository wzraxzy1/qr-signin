"""
配置与环境变量（单一来源）：
- SECRET_KEY：生产环境强制、密钥派生、数据库路径、前端构建产物路径
- token 有效期、QR 宽限期、登录限流常量
拆分自原单体 app.py，便于测试与复用，任何模块都从这里取配置。
"""
import os
import secrets

# SECRET_KEY：生产环境（APP_ENV=production）必须显式设置，缺失则拒绝启动，
# 禁止回退到公开可猜的默认密钥；开发环境未设置时生成临时密钥（进程重启后失效，仅本地可接受）。
SECRET_KEY = os.environ.get("SECRET_KEY")
_APP_ENV = os.environ.get("APP_ENV", os.environ.get("ENV", "development")).lower()
if not SECRET_KEY:
    if _APP_ENV == "production":
        raise RuntimeError(
            "安全基线：生产环境必须设置环境变量 SECRET_KEY，禁止回退到默认密钥。"
            "请在部署配置中 export SECRET_KEY=<随机32+位十六进制> 后重启服务。"
        )
    SECRET_KEY = secrets.token_hex(32)
    print("[WARN] SECRET_KEY 未设置，已生成临时开发密钥（进程重启后失效）。"
          "生产部署请通过环境变量提供固定的 SECRET_KEY。")

TOKEN_EXPIRE_HOURS = 24

# Render: use persistent disk path if available, otherwise local dir
_RENDER_DATA = os.environ.get("RENDER_DATA_DIR", "")
if _RENDER_DATA:
    DB_PATH = os.path.join(_RENDER_DATA, "signin.db")
else:
    # 本文件位于 backend/app/config.py，backend 目录为向上两级
    _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(_backend_dir, "signin.db")

# Frontend dist: look relative to backend dir, fallback to /opt/render/ paths for Render
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIST = os.path.join(_project_root, "frontend", "dist")
if not os.path.isdir(FRONTEND_DIST):
    # Render build may place frontend in a different location
    FRONTEND_DIST = os.path.join(os.environ.get("RENDER_PROJECT_DIR", _project_root), "frontend", "dist")

# Token grace period: users get this many seconds after QR generation to submit
TOKEN_GRACE_PERIOD = 120  # 2 minutes

# ==================== Login Rate Limiting 常量 ====================
# 简单内存级登录限流：单实例部署足够；多实例需改为共享存储（如 Redis）。
# 按「用户名」+「来源 IP」双维度计数，防止暴力破解与批量探测。
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW = 5 * 60        # 计数窗口：5 分钟内
LOGIN_LOCKOUT = 5 * 60       # 触发上限后锁定时长：5 分钟
