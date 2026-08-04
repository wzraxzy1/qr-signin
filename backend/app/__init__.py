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

from .config import FRONTEND_DIST
from .db import get_db, init_db
from .crypto import hash_password, verify_password, create_token, verify_token
from .auth_utils import (
    get_current_user,
    require_super_admin,
    mask_id_card,
    _login_fail,
)
from . import routers

app = FastAPI(title="QR Sign-in System")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = os.path.join(FRONTEND_DIST, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


# 表结构在导入时创建（与原单体 app.py 行为一致：首启建表 / 迁移列 / 播种超管）
init_db()
