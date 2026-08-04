"""
FastAPI 应用入口（门面 / facade）。
职责仅限于“装配”，不包含业务细节：
- 创建 app 实例、配置 CORS
- include_router 装配各业务路由器
- 挂载前端静态资源与 SPA 回退
- 启动时建表（init_db）
- 重新导出测试与脚本所需的若干函数，保证 `import app` 的对外契约不变

业务逻辑已拆分到同包内的 config / crypto / db / auth_utils / schemas / routers。
部署仍使用 `uvicorn app:app`（app 即本模块导出的 FastAPI 实例）。
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import FRONTEND_DIST, IS_PRODUCTION
from .db import get_db, init_db
from .crypto import hash_password, verify_password, create_token, verify_token
from .auth_utils import (
    get_current_user,
    require_super_admin,
    mask_id_card,
    _login_fail,
)
from . import routers


def _resolve_cors_origins():
    """解析允许的跨域来源。
    - 显式设置 CORS_ORIGINS（逗号分隔）时优先采用；
    - 生产环境未设置则默认 []（同源 SPA 由本后端挂载，本就无需 CORS）；
    - 非生产环境未设置则放行常见本地前端来源，方便本地联调。
    注意：allow_credentials=True 不能与通配符 "*" 共用（违反浏览器同源策略），
    因此这里始终返回明确的来源列表，禁止回退到 "*"。
    """
    raw = os.environ.get("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    if IS_PRODUCTION:
        return []
    return ["http://localhost:5173", "http://127.0.0.1:5173"]


app = FastAPI(title="QR Sign-in System")

# CORS（禁止 allow_origins=["*"] 与 allow_credentials=True 共用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 装配业务路由（顺序无关；API 路由均先于下方 SPA 通配路由注册，不会被覆盖）
app.include_router(routers.auth.router)
app.include_router(routers.users.router)
app.include_router(routers.sessions.router)
app.include_router(routers.signin.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ==================== Serve Frontend ====================
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_spa_root():
        """SPA 根路径返回 index.html。注意：@app.get("/{full_path:path}") 的 path 转换器要求至少一个字符，"
        "不匹配空路径 '/'; 因此根路径必须单独注册一个路由。"""
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        file_path = os.path.join(FRONTEND_DIST, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


# 表结构在导入时创建（与原单体 app.py 行为一致：首启建表 / 迁移列 / 播种超管）
init_db()
