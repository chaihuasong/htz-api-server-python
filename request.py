from pydantic import BaseModel

class RequestItem(BaseModel):
    pkg: str
    version: str
    phone: str
    type: str
    info: str
    time: str
    user: str

class AkskRequestItem(BaseModel):
    id: int = None
    appName: str
    platform: str
    accessKey: str
    accessKeySecure: str
    note: str = ""

class AppUsageItem(BaseModel):
    device_id: str
    user_id: str = ""
    date: str
    open_count: int = 0
    duration_ms: int = 0
    version: str = ""
    pkg: str = ""
    phone_model: str = ""
    os_version: str = ""
    network_type: str = ""
    source: str = ""

class FeedbackItem(BaseModel):
    id: int = None
    user_id: str = ""
    nickname: str = ""
    contact: str = ""
    content: str
    category: str = ""
    pkg: str = ""
    version: str = ""
    phone_model: str = ""
    os_version: str = ""
    device_id: str = ""
    status: str = "pending"
    reply: str = ""
    # JSON 字符串数组，例如 ["/static/feedback/xxx.jpg", ...]
    image_urls: str = ""
    # 单个视频 URL，例如 "/static/feedback/xxx.mp4"
    video_url: str = ""

class NotificationItem(BaseModel):
    id: str = None
    title: str
    msg: str
    status: str = "published"

class NotificationQueryItem(BaseModel):
    page_index: int = 0
    page_size: int = 500

class UserInfoItem(BaseModel):
    unionid: str
    nickname: str
    openid: str
    sex: str
    headimgurl: str
    country: str
    province: str
    city: str
    language: str
    group_id: str
    telephone: str
    pwd: str
    sign: str
    note: str