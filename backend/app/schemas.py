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
    # 定位限制（地理围栏）：开启后仅允许位于指定中心点 radius_m 米内的签到者签到。
    # center_lat/center_lng 按 GCJ-02（腾讯地图标准）存储；location_fallback 定义
    # 用户无定位/拒绝授权时的策略：'reject' 拒签 / 'allow_flag' 放行并标记位置异常。
    location_enabled: bool = False
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    radius_m: Optional[int] = None
    location_fallback: str = "reject"


class SessionUpdate(BaseModel):
    name: Optional[str] = None
    refresh_interval: Optional[int] = None
    fields_config: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None
    start_at: Optional[float] = None
    expires_at: Optional[float] = None
    max_signins: Optional[int] = None
    anti_photo: Optional[bool] = None
    location_enabled: Optional[bool] = None
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    radius_m: Optional[int] = None
    location_fallback: Optional[str] = None


class SignInSubmit(BaseModel):
    token: str
    field_data: Dict[str, Any]
    # 设备指纹（防作弊：同一台设备在同一会话内只能成功签到一次）。
    # 由前端生成并持久化在 localStorage，不随 token 变化；旧前端/非浏览器客户端
    # 可不传（默认空），此时跳过设备维度去重，向后兼容现有行为。
    device_id: str = ""
    # 用户上报的 GPS 坐标（WGS-84，来自 navigator.geolocation）。开启定位限制时
    # 由前端采集并随提交发送；拒绝授权或无 GPS 时为 None，后端按 location_fallback 处理。
    lat: Optional[float] = None
    lng: Optional[float] = None


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
