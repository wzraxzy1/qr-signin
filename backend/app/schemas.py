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


class SessionUpdate(BaseModel):
    name: Optional[str] = None
    refresh_interval: Optional[int] = None
    fields_config: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None
    start_at: Optional[float] = None
    expires_at: Optional[float] = None
    max_signins: Optional[int] = None


class SignInSubmit(BaseModel):
    token: str
    field_data: Dict[str, Any]


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
