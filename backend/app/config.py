"""
配置与环境变量（单一来源）：
- SECRET_KEY：生产环境强制、密钥派生、数据库路径、前端构建产物路径
- token 有效期、QR 宽限期、登录限流常量
拆分自原单体 app.py，便于测试与复用，任何模块都从这里取配置。
"""
import os
import json
import secrets
import math

# SECRET_KEY：生产环境（APP_ENV=production）必须显式设置，缺失则拒绝启动，
# 禁止回退到公开可猜的默认密钥；开发环境未设置时生成临时密钥（进程重启后失效，仅本地可接受）。
SECRET_KEY = os.environ.get("SECRET_KEY")
APP_ENV = os.environ.get("APP_ENV", os.environ.get("ENV", "development")).lower()
IS_PRODUCTION = APP_ENV == "production"
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError(
            "安全基线：生产环境必须设置环境变量 SECRET_KEY，禁止回退到默认密钥。"
            "请在部署配置中 export SECRET_KEY=<随机32+位十六进制> 后重启服务。"
        )
    SECRET_KEY = secrets.token_hex(32)
    print("[WARN] SECRET_KEY 未设置，已生成临时开发密钥（进程重启后失效）。"
          "生产部署请通过环境变量提供固定的 SECRET_KEY。")

TOKEN_EXPIRE_HOURS = 24

# 本文件位于 backend/app/config.py，backend 目录为向上两级，项目根(qr-signin/)再上一级
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))    # backend/
_project_root = os.path.dirname(_backend_dir)                                  # qr-signin/

# Render: use persistent disk path if available, otherwise local dir
_RENDER_DATA = os.environ.get("RENDER_DATA_DIR", "")
if _RENDER_DATA:
    DB_PATH = os.path.join(_RENDER_DATA, "signin.db")
else:
    DB_PATH = os.path.join(_backend_dir, "signin.db")

# Frontend dist: 位于项目根的 frontend/dist（默认），找不到时回退到 RENDER_PROJECT_DIR/frontend/dist（Render）
FRONTEND_DIST = os.path.join(_project_root, "frontend", "dist")
if not os.path.isdir(FRONTEND_DIST):
    # Render build may place frontend in a different location
    FRONTEND_DIST = os.path.join(os.environ.get("RENDER_PROJECT_DIR", _project_root), "frontend", "dist")

# Token grace period: users get this many seconds after QR generation to submit
TOKEN_GRACE_PERIOD = 120  # 2 minutes

# 防拍照（动态短时效二维码）模式下的宽限：按字段数量灵活延长，避免字段多的表单
# 来不及填写。有效期 = refresh_interval + 基础宽限 + 每字段额外时间。拍照留存/转发
# 仍会在远短于 130s 的时间内过期，现场活码扫描不受影响。
ANTI_PHOTO_BASE_GRACE = 5        # 基础宽限（无字段/匿名场景）
ANTI_PHOTO_PER_FIELD = 10       # 每个签到字段额外给的填写时间（秒）


def anti_photo_grace_seconds(fields_config):
    """防拍照模式的额外宽限秒数：基础 + 每字段时间。字段越多给的填写时间越长。"""
    try:
        n = len(json.loads(fields_config or "[]"))
    except Exception:
        n = 0
    return ANTI_PHOTO_BASE_GRACE + ANTI_PHOTO_PER_FIELD * n


# ==================== 坐标系与地理围栏工具 ====================
# 浏览器 navigator.geolocation 返回 WGS-84，而国内地图（腾讯/高德/百度）使用 GCJ-02（火星坐标）。
# 两者在国内相差约数百米，若直接比距离会让紧邻围栏边界的正常用户被错误拒绝。
# 因此：会话中心按地图标准(GCJ-02)存储；签到时把用户上报的 WGS-84 转成 GCJ-02 再比距离。
_GCJ02_A = 6378245.0
_GCJ02_EE = 0.00669342162296594323


def _gcj02_transform_lat(x, y):
    ret = (-100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y
           + 0.2 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _gcj02_transform_lng(x, y):
    ret = (300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y
           + 0.1 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat, lng):
    """WGS-84 → GCJ-02（火星坐标）偏移。国内范围外不偏移，直接原样返回。"""
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return lat, lng
    dlat = _gcj02_transform_lat(lng - 105.0, lat - 35.0)
    dlng = _gcj02_transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _GCJ02_EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_GCJ02_A * (1 - _GCJ02_EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (_GCJ02_A / sqrtmagic * math.cos(radlat) * math.pi)
    return lat + dlat, lng + dlng


def haversine_meters(lat1, lng1, lat2, lng2):
    """两点间大圆距离（米）。输入可为 WGS-84 或 GCJ-02，只要两者坐标系一致即可。"""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))

# ==================== Login Rate Limiting 常量 ====================
# 简单内存级登录限流：单实例部署足够；多实例需改为共享存储（如 Redis）。
# 按「用户名」+「来源 IP」双维度计数，防止暴力破解与批量探测。
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW = 5 * 60        # 计数窗口：5 分钟内
LOGIN_LOCKOUT = 5 * 60       # 触发上限后锁定时长：5 分钟
