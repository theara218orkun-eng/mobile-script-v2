from pydantic import BaseModel
from typing import Optional, Dict, Any

class UserInfo(BaseModel):
    username: Optional[str] = None
    phone: Optional[str] = None
    uuid: Optional[str] = None

class ChatInfo(BaseModel):
    uuid: Optional[str] = None
    name: Optional[str] = None

class WebhookPayload(BaseModel):
    type: str
    device_id: str
    package: str
    platform: str
    user_info: Optional[UserInfo] = None
    chat: Optional[ChatInfo] = None
    content: str  # Base64 encoded
    time: int
    is_group: bool = False

class WebhookResponse(BaseModel):
    status: str = "ok"
    message: Optional[str] = None
