"""
路由器包：按业务域拆分路由。每个子模块定义自己的 APIRouter，
由 backend/app/__init__.py 统一 include_router 装配。
"""
from . import auth, users, sessions, signin

__all__ = ["auth", "users", "sessions", "signin"]
