"""
Pydantic 请求/响应模型（数据契约）。
拆分自原 app.py 的 Models 区块，集中管理前后端交互结构。
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class SessionCreate(BaseModel):
    name: str
    refresh_interval: int = 10
    fields_config: List[Dict[str, Any]] = []
    start_at: Optional[float] = None
    expires_at: Optional[float] = None
    max_signins: Optional[int] = None
    anti_photo: bool = False


class SessionUpdate(BaseModel):
    name: Optional[str] = None
    refresh_interval: Optional[int] = None
    fields_config: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None
    start_at: Optional[float] = None
    expires_at: Optional[float] = None
    max_signins: Optional[int] = None
    anti_photo: Optional[bool] = None


class SignInSubmit(BaseModel):
    token: str
    field_data: Dict[str, Any]
    # 设备指纹（防作弊：同一台设备在同一会话内只能成功签到一次）。
    # 由前端生成并持久化在 localStorage，不随 token 变化；旧前端/非浏览器客户端
    # 可不传（默认空），此时跳过设备维度去重，向后兼容现有行为。
    device_id: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "admin"


class UserUpdate(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[int] = None


class ChangePassword(BaseModel):
    old_password: str
    new_password: str
