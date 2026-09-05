from typing import List, Optional

from pydantic import BaseModel

class RequestItem(BaseModel):
    """崩溃 / ANR 日志上报。

    字段全部给默认值：缺一个就把整条日志丢掉不值当，日志本来就是出问题时才发的。
    """
    pkg: str = ""
    version: str = ""
    phone: str = ""
    type: str = ""
    info: str = ""
    time: str = ""
    # 老客户端（<= 2.0.x）这里传的是**昵称**，新客户端传的也是昵称、身份看 unionid。
    # 后台展示逻辑见 db.py 的 _LOG_USER_NAME_SQL。
    user: str = ""
    # 用户身份。**None 和 "" 含义不同，不要给它改成 str = ""**：
    #   None = 老客户端根本没传这个字段，无从判断登录状态
    #   ""   = 新客户端传了，且当时确实未登录
    # 混在一起的话，未登录和「已登录但昵称为空」在后台又会分不出来。
    unionid: Optional[str] = None

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
    # 前台停留时长
    duration_ms: int = 0
    # 实际播放音频的时长，首页「学习时长」用的就是这份
    play_duration_ms: int = 0
    version: str = ""
    pkg: str = ""
    phone_model: str = ""
    engineering_model: str = ""
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
    engineering_model: str = ""
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

# 客户端上报「听完过的条目」，换设备后靠它还原首页的完成课程数
class CompletedItemsReport(BaseModel):
    user_id: str
    item_ids: List[str] = []

class UserTelephoneUpdateItem(BaseModel):
    unionid: str
    telephone: str

class PhoneModelMappingItem(BaseModel):
    id: int = None
    engineering_model: str
    marketing_model: str
    manufacturer: str = ""
    remark: str = ""

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

# 十年持志系统按手机号推送过来的公共资料同步数据（仅含可跨系统同步的字段）
class UserSyncItem(BaseModel):
    telephone: str = ""
    nickname: str = ""
    sex: str = ""
    headimgurl: str = ""
    country: str = ""
    province: str = ""
    city: str = ""
    language: str = ""
    sign: str = ""
    last_update_time: str = ""