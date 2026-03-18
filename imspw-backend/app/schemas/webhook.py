from pydantic import BaseModel
from typing import Optional, Dict, Any

class UserInfo(BaseModel):
    username: Optional[str] = None
    phone: Optional[str] = None
    uuid: Optional[str] = None

class ChatInfo(BaseModel):
    uuid: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None

class WebhookPayload(BaseModel):
    type: str
    device_id: str
    package: Optional[str] = None
    platform: str
    user_info: Optional[UserInfo] = None
    chat: Optional[ChatInfo] = None
    content: str  # Base64 encoded
    time: Any  # Allow int or date string
    is_group: bool = False
    media_type: Optional[str] = None  # "image", "video", etc.
    media_url: Optional[str] = None  # URL or path to media
    caption: Optional[str] = None  # Media caption (Base64 encoded)

class WebhookResponse(BaseModel):
    status: str = "ok"
    message: Optional[str] = None
    image: Optional[str] = None  # URL to image for auto-reply
    image_caption: Optional[str] = None  # Optional caption for image reply
