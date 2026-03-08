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