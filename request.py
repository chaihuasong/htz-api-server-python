import json
import os
import re
from typing import List, Optional

from pydantic import BaseModel

# 反馈里最多附带的应用日志个数，对应客户端默认勾选的最近 3 天。
MAX_FEEDBACK_LOG_FILES = 3
_LOG_URL_PREFIX = "/static/feedback/"
_LOG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.log$")


class FeedbackLogUrlError(ValueError):
    """log_urls 不符合约定。调用方应原样把这条消息返回给客户端，不能当成保存成功。"""


def normalize_feedback_log_urls(value):
    """把 log_urls 收成 JSON 数组字符串。

    合法输入：缺省 / 空串 / null、JSON 数组字符串、JSON 数组，或单个
    /static/feedback/*.log 地址。存进数据库的始终是 JSON 数组字符串；没有日志时是空串。
    这里只检查地址形状，不碰磁盘。
    """
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise FeedbackLogUrlError("log_urls 不是合法的 JSON 数组") from exc
        elif text.startswith(_LOG_URL_PREFIX):
            parsed = [text]
        else:
            raise FeedbackLogUrlError("log_urls 必须是日志地址的 JSON 数组")
    elif isinstance(value, list):
        parsed = value
    else:
        raise FeedbackLogUrlError("log_urls 必须是日志地址的 JSON 数组")
    if not isinstance(parsed, list):
        raise FeedbackLogUrlError("log_urls 必须是日志地址的 JSON 数组")
    if len(parsed) > MAX_FEEDBACK_LOG_FILES:
        raise FeedbackLogUrlError(f"log_urls 最多 {MAX_FEEDBACK_LOG_FILES} 个")
    urls = []
    for item in parsed:
        if not isinstance(item, str):
            raise FeedbackLogUrlError("log_urls 里的每一项都必须是字符串地址")
        urls.append(feedback_log_basename(item))
    if not urls:
        return ""
    return json.dumps([_LOG_URL_PREFIX + name for name in urls], ensure_ascii=False)


def feedback_log_basename(url):
    """从 /static/feedback/<文件名>.log 取出文件名。拒绝路径穿越和其它扩展名。"""
    if not isinstance(url, str) or not url.startswith(_LOG_URL_PREFIX):
        raise FeedbackLogUrlError("log_urls 只能使用 /static/feedback/ 下的 .log 地址")
    name = url[len(_LOG_URL_PREFIX):]
    if name != os.path.basename(name) or ".." in name or not _LOG_NAME_RE.fullmatch(name):
        raise FeedbackLogUrlError("log_urls 含有非法的日志文件名")
    return name

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
    # 应用日志地址。旧客户端不传。可以是 JSON 数组字符串、JSON 数组，或单个 .log 地址。
    # 入库前会收成 JSON 数组字符串；没有日志时是空串。
    log_urls: Optional[object] = ""

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

class UserNote2UpdateItem(BaseModel):
    unionid: str
    note2: str = ""

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