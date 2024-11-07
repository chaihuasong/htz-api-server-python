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
    appName: str

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