from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Body
from fastapi.exceptions  import RequestValidationError
from fastapi.responses  import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
import logging
import os
import uuid
import json
import time
import shutil
import urllib.request
import urllib.parse
import threading
from datetime import datetime

from request import RequestItem, AkskRequestItem, AppUsageItem, FeedbackItem, UserTelephoneUpdateItem, PhoneModelMappingItem, UserSyncItem, CompletedItemsReport
from db import *
from typing import List

# ===== 与十年持志（TenYears）系统的用户资料双向同步配置 =====
# 十年持志后端（Spring Boot + MongoDB）入站同步端点，按手机号匹配合并公共资料字段。
# 可按部署环境调整（同机可改为内网地址）。
TENYEARS_SYNC_URL = "http://htzchina.org:8081/syncByTelephone"


def _push_user_to_tenyears(payload: dict):
    """把本地用户的公共资料字段按手机号异步推送到十年持志系统。
    无手机号则跳过；线程内执行，失败仅记录日志，不影响主流程。
    注意：仅在「本系统主动写入」时调用，入站 /userinfo/sync 不调用，避免双向死循环。"""
    telephone = (payload.get("telephone") or "").strip()
    if not telephone:
        return

    def _do():
        try:
            data = urllib.parse.urlencode({
                "telephone": telephone,
                "nickname": payload.get("nickname", "") or "",
                "sex": str(payload.get("sex", "") or ""),
                "headimgurl": payload.get("headimgurl", "") or "",
                "country": payload.get("country", "") or "",
                "province": payload.get("province", "") or "",
                "city": payload.get("city", "") or "",
                "language": payload.get("language", "") or "",
                "sign": payload.get("sign", "") or "",
                "lastUpdateTime": payload.get("last_update_time", "") or "",
            }).encode("utf-8")
            req = urllib.request.Request(
                TENYEARS_SYNC_URL, data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                r.read()
            print(f"push_user_to_tenyears ok telephone={telephone}")
        except Exception as e:
            print(f"push_user_to_tenyears failed telephone={telephone}: {e}")

    threading.Thread(target=_do, daemon=True).start()

# ===== 微信扫码登录配置 =====
# 公众号 APPID，appsecret 存在 aksk 表 appName='htz-gzh' 的 accessKeySecure 字段
WX_GZH_APPID = "wx83aec75c3ca58f0e"
# redirect_uri 须与公众号后台「网页授权域名」一致
WX_REDIRECT_URI = "http://htzchina.org/htz-api-pyservice/api/v1/wx/callback"
# 二维码会话有效期（秒）。
# 同一台手机扫码要走「截图 → 打开微信 → 扫一扫相册 → 授权 → 返回 App」，5 分钟经常不够用。
QR_SESSION_EXPIRE_SECONDS = 600
# 主服务端的 unionid 登录接口，扫码登录的 token 只能由它签发
MAIN_SERVER_LOGIN_UNIONID = "http://39.105.174.143:9100/post/login/unionid"
# 换 token 的重试次数与间隔（秒）：主服务端偶尔抖一下不该让用户白扫一次
MAIN_SERVER_LOGIN_RETRIES = 3
MAIN_SERVER_LOGIN_RETRY_INTERVAL = 1

# 初始化日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

app = FastAPI()

# 服务器出口带宽有限（实测 ~120KB/s），后台列表接口返回的 JSON 重复度极高，
# gzip 后体积能降到约 1/28，是后台刷新慢的主因。也顺带压缩 admin.html。
class SelectiveGZipMiddleware:
    """只对接口和页面做 gzip，跳过 /static。

    /static 下是意见反馈上传的图片和视频，本身已压缩，gzip 收益为零白费 CPU；
    更要紧的是后台 <video> 拖进度条会发 Range 请求，压缩 206 会让 Content-Length
    （压缩后大小）和 Content-Range（原始字节区间）对不上，属于不规范的组合。
    fastapi 0.110 带的 starlette 0.36 还没有按 content-type 排除的参数，所以按路径挡。
    """

    def __init__(self, app):
        self.app = app
        self.gzip_app = GZipMiddleware(app, minimum_size=1000)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not scope["path"].startswith("/static"):
            await self.gzip_app(scope, receive, send)
        else:
            await self.app(scope, receive, send)


app.add_middleware(SelectiveGZipMiddleware)

# ===== 静态文件 =====
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
FEEDBACK_UPLOAD_DIR = os.path.join(STATIC_DIR, "feedback")
os.makedirs(FEEDBACK_UPLOAD_DIR, exist_ok=True)
# 将 static/ 目录暴露为 /static/ 静态资源
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 单个文件大小上限（字节）：图片 10MB，视频 50MB
MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_VIDEO_SIZE = 50 * 1024 * 1024
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".3gp", ".webm", ".mkv"}

# 初始化数据库表
init_log_info_table()
init_app_usage_table()
init_qr_session_table()
init_feedback_table()
init_notification_table()
init_phone_model_mapping_table()
init_user_info_table()
init_completed_item_table()
init_gray_release_table()

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """
    handle the exception of incorrect request parameter

    HTTP 状态码必须跟着 body 里的 code 一起是 4xx。以前这里返回的是默认的 200，
    客户端 postEnsureSuccess() 只看状态码，参数不合法时也当成上报成功，
    转手就把本地的崩溃现场删了 / 把 ANR 水位线推了过去，日志两头都不落。
    """
    logger.error(exc)
    return JSONResponse({"code": "422", "msg": "bad request parameter", "data": None},
                        status_code=422)

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """
    handle the exception of incorrect request path
    """
    logger.error(exc)
    return JSONResponse({"code": "404", "msg": "bad request path", "data": None})

@app.post("/htz-api-pyservice/api/v1/savelog")
def save_loginfo(request_item: RequestItem):
    print(request_item)
    try:
        save_log_info(request_item)
    except Exception as e:
        print(f"保存出错: {e}")
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.get("/htz-api-pyservice/api/v1/getlog")
def get_loginfo(pkg: str):
    print(pkg)
    result = get_log_info(pkg)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.get("/htz-api-pyservice/api/v1/getaksk")
def getaksk(appName: str):
    print(appName)
    result = get_ak_sk(appName)
    print(result)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.post("/htz-api-pyservice/api/v1/userinfo/add")
def save_userinfo(request_item: UserInfoItem):
    print(f"save_userinfo unionid:{request_item}")
    existing_user = select_user_dict_by_unionid(request_item.unionid)
    if existing_user:
        print(f"Updating user with unionid: {request_item.unionid}")
        update_user_by_unionid(request_item)
    else:
        print(f"Inserting new user with unionid: {request_item.unionid}")
        insert_user(request_item)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.post("/htz-api-pyservice/api/v1/userinfo/update")
def update_userinfo(request_item: UserInfoItem):
    print(f"update_userinfo unionid:{request_item}")
    update_user_by_unionid(request_item)
    # 写时出站：把公共资料字段同步到十年持志系统（按手机号）
    _push_user_to_tenyears({
        "telephone": request_item.telephone,
        "nickname": request_item.nickname,
        "sex": request_item.sex,
        "headimgurl": request_item.headimgurl,
        "country": request_item.country,
        "province": request_item.province,
        "city": request_item.city,
        "language": request_item.language,
        "sign": request_item.sign,
        "last_update_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.post("/htz-api-pyservice/api/v1/userinfo/telephone/update")
def update_user_telephone(request_item: UserTelephoneUpdateItem):
    unionid = request_item.unionid.strip()
    telephone = request_item.telephone.strip()
    if not unionid:
        return JSONResponse({"code": "400", "msg": "unionid is required", "data": None})
    if not telephone:
        return JSONResponse({"code": "400", "msg": "telephone is required", "data": None})

    existing_user = select_user_dict_by_telephone(telephone)
    if existing_user and existing_user.get("unionid") != unionid:
        return JSONResponse({"code": "409", "msg": "telephone already exists", "data": None})

    updated_count = update_user_telephone_by_unionid(unionid, telephone)
    if updated_count == 0:
        return JSONResponse({"code": "404", "msg": "user not found", "data": None})
    # 绑定/更新手机号后，按手机号把该用户公共资料推送到十年持志系统
    synced_user = select_user_dict_by_telephone(telephone)
    if synced_user:
        _push_user_to_tenyears(synced_user)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.post("/htz-api-pyservice/api/v1/userinfo/sync")
def userinfo_sync(item: UserSyncItem):
    """入站：接收十年持志系统按手机号推送的公共资料，合并到本地（非空+最近更新优先）。
    本端点不再回推，避免双向死循环。"""
    ok = apply_user_sync_by_telephone(item.telephone, item.dict(), item.last_update_time)
    if not ok:
        return JSONResponse({"code": "404", "msg": "user not found", "data": None})
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": None})

@app.get("/htz-api-pyservice/api/v1/userinfo/getbyphone")
def get_userinfo_by_phone(telephone: str):
    result = select_user_by_telephone(telephone)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.get("/htz-api-pyservice/api/v1/userinfo/get")
def get_userinfo(unionid: str):
    print(f"get_userinfo unionid:{unionid}")
    result = select_user_by_unionid(unionid)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.post("/htz-api-pyservice/api/v1/userinfo/delete")
def delete_userinfo(unionid: str):
    print(f"delete_userinfo unionid:{unionid}")
    delete_user_by_unionid(unionid)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

# ===== AK/SK 管理 API =====
@app.get("/htz-api-pyservice/api/v1/aksk/list")
def list_aksk():
    result = get_all_aksk()
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.post("/htz-api-pyservice/api/v1/aksk/add")
def add_aksk(request_item: AkskRequestItem):
    print(f"add_aksk: {request_item}")
    insert_aksk(request_item)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.post("/htz-api-pyservice/api/v1/aksk/update")
def update_aksk_api(request_item: AkskRequestItem):
    print(f"update_aksk: {request_item}")
    update_aksk(request_item)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.post("/htz-api-pyservice/api/v1/aksk/delete")
def delete_aksk_api(id: int):
    print(f"delete_aksk id: {id}")
    delete_aksk(id)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

# ===== 用户和日志列表 API =====
@app.get("/htz-api-pyservice/api/v1/userinfo/list")
def list_userinfo():
    result = get_all_users()
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.get("/htz-api-pyservice/api/v1/log/list")
def list_logs():
    result = get_all_logs()
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.get("/htz-api-pyservice/api/v1/log/detail")
def log_detail(id: int):
    result = get_log_detail(id)
    if result is None:
        return JSONResponse({"code": "404", "msg": "log not found", "data": None})
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

# ===== 用量统计 API =====
@app.post("/htz-api-pyservice/api/v1/usage/report")
def report_usage(item: AppUsageItem):
    print(f"report_usage: {item}")
    try:
        save_app_usage(item)
    except Exception as e:
        print(f"report_usage error: {e}")
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.post("/htz-api-pyservice/api/v1/usage/report/batch")
def report_usage_batch(items: List[AppUsageItem]):
    print(f"report_usage_batch: {len(items)} items")
    try:
        save_app_usage_batch(items)
    except Exception as e:
        print(f"report_usage_batch error: {e}")
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.get("/htz-api-pyservice/api/v1/usage/list")
def list_usage():
    result = get_all_app_usage()
    result = enrich_list_with_marketing_model(result, "phone_model")
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.get("/htz-api-pyservice/api/v1/usage/summary")
def usage_summary():
    result = get_app_usage_summary()
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.get("/htz-api-pyservice/api/v1/usage/phone-model-stats")
def usage_phone_model_stats():
    result = get_phone_model_stats()
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

# ===== 学习统计 API（换设备/清数据后找回）=====
@app.get("/htz-api-pyservice/api/v1/study/duration")
def study_duration(user_id: str):
    """按 unionid 返回每天的实际播放时长，已跨设备汇总"""
    result = get_user_daily_play_duration(user_id)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.post("/htz-api-pyservice/api/v1/study/completed/report")
def study_completed_report(item: CompletedItemsReport):
    print(f"study_completed_report: user={item.user_id} count={len(item.item_ids)}")
    try:
        save_completed_items(item.user_id, item.item_ids)
    except Exception as e:
        print(f"study_completed_report error: {e}")
        return JSONResponse({"code": "500", "msg": str(e), "data": "null"})
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.get("/htz-api-pyservice/api/v1/study/completed")
def study_completed(user_id: str):
    result = get_completed_items(user_id)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

# ===== 意见反馈 API =====
@app.post("/htz-api-pyservice/api/v1/feedback/add")
def feedback_add(item: FeedbackItem):
    print(f"feedback_add: {item}")
    try:
        save_feedback(item)
    except Exception as e:
        print(f"feedback_add error: {e}")
        return JSONResponse({"code": "500", "msg": str(e), "data": None})
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.get("/htz-api-pyservice/api/v1/feedback/list")
def feedback_list():
    result = get_all_feedback()
    result = enrich_list_with_marketing_model(result, "phone_model")
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.post("/htz-api-pyservice/api/v1/feedback/update")
def feedback_update(item: FeedbackItem):
    print(f"feedback_update: {item}")
    update_feedback(item)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.post("/htz-api-pyservice/api/v1/feedback/delete")
def feedback_delete(id: int):
    print(f"feedback_delete id: {id}")
    delete_feedback(id)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

# ===== 系统通知 API =====
@app.get("/htz-api-pyservice/api/v1/notification/list")
def notification_list():
    result = get_all_notifications()
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.post("/htz-api-pyservice/api/v1/notification/add")
def notification_add(item: NotificationItem):
    print(f"notification_add: {item}")
    notification_id = save_notification(item)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": {"id": notification_id}})

@app.post("/htz-api-pyservice/api/v1/notification/update")
def notification_update(item: NotificationItem):
    print(f"notification_update: {item}")
    notification_id = save_notification(item)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": {"id": notification_id}})

@app.post("/htz-api-pyservice/api/v1/notification/delete")
def notification_delete(id: str):
    print(f"notification_delete id: {id}")
    delete_notification(id)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.post("/htz-api-pyservice/api/v1/get/notifications")
def get_notifications(request_item: NotificationQueryItem, token: str = Header(default="")):
    result = get_user_notifications(token, request_item.page_index, request_item.page_size)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.post("/htz-api-pyservice/api/v1/put/user/notifications")
def put_user_notifications(notification_ids: List[str] = Body(default=[]), token: str = Header(default="")):
    count = mark_user_notifications_read(token, notification_ids)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": {"count": count}})

@app.post("/htz-api-pyservice/api/v1/feedback/upload")
async def feedback_upload(file: UploadFile = File(...), type: str = Form("image")):
    """上传反馈附件（图片/视频），返回可访问 URL"""
    try:
        ext = os.path.splitext(file.filename or "")[1].lower()
        if type == "video":
            allowed = ALLOWED_VIDEO_EXTS
            max_size = MAX_VIDEO_SIZE
        else:
            allowed = ALLOWED_IMAGE_EXTS
            max_size = MAX_IMAGE_SIZE
        if ext not in allowed:
            return JSONResponse({"code": "400", "msg": f"unsupported file ext: {ext}", "data": None})

        new_name = f"{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
        dst_path = os.path.join(FEEDBACK_UPLOAD_DIR, new_name)
        size = 0
        with open(dst_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_size:
                    out.close()
                    os.remove(dst_path)
                    return JSONResponse({"code": "413", "msg": "file too large", "data": None})
                out.write(chunk)
        url = f"/static/feedback/{new_name}"
        print(f"feedback_upload saved {dst_path} ({size} bytes) -> {url}")
        return JSONResponse({"code": "0", "msg": "SUCCESS", "data": {"url": url, "size": size}})
    except Exception as e:
        print(f"feedback_upload error: {e}")
        return JSONResponse({"code": "500", "msg": str(e), "data": None})

# ===== 微信扫码登录 =====

def _get_gzh_aksk():
    """从 aksk 表读取公众号 appid 和 appsecret"""
    aksk_json = get_ak_sk("htz-fwh")
    aksk = json.loads(aksk_json)
    return aksk.get("accessKey", ""), aksk.get("accessKeySecure", "")


@app.post("/htz-api-pyservice/api/v1/qr/login/create")
def qr_login_create():
    """创建二维码登录会话（公众号 oauth2/authorize，扫码一次直接弹授权）"""
    appid, _ = _get_gzh_aksk()
    if not appid:
        return JSONResponse({"code": "500", "msg": "gzh appid not configured", "data": None})

    session_id = uuid.uuid4().hex
    create_qr_session(session_id)

    from urllib.parse import quote
    redirect_uri_encoded = quote(WX_REDIRECT_URI, safe="")
    qr_url = (
        f"https://open.weixin.qq.com/connect/oauth2/authorize"
        f"?appid={appid}"
        f"&redirect_uri={redirect_uri_encoded}"
        f"&response_type=code"
        f"&scope=snsapi_userinfo"
        f"&state={session_id}"
        f"#wechat_redirect"
    )
    print(f"qr_login_create session_id={session_id} appid={appid} redirect_uri={WX_REDIRECT_URI}")
    print(f"qr_login_create full_url={qr_url}")
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": {
        "session_id": session_id,
        "qr_url": qr_url
    }})


@app.get("/htz-api-pyservice/api/v1/qr/login/poll")
def qr_login_poll(session_id: str):
    """APP 轮询二维码登录状态"""
    session = get_qr_session(session_id)
    if session is None:
        return JSONResponse({"code": "404", "msg": "session not found", "data": None})

    # 检查是否过期（pending 状态超时）
    if session["status"] == "pending":
        created_at = datetime.strptime(session["created_at"], '%Y-%m-%d %H:%M:%S')
        elapsed = (datetime.now() - created_at).total_seconds()
        if elapsed > QR_SESSION_EXPIRE_SECONDS:
            expire_qr_session(session_id)
            return JSONResponse({"code": "0", "msg": "SUCCESS", "data": {"status": "expired"}})

    if session["status"] == "confirmed":
        user_info = json.loads(session["user_info"]) if session["user_info"] else {}
        return JSONResponse({"code": "0", "msg": "SUCCESS", "data": {
            "status": "confirmed",
            "token": session["token"],
            "user_info": user_info
        }})

    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": {"status": session["status"]}})


@app.post("/htz-api-pyservice/api/v1/qr/login/consume")
def qr_login_consume(session_id: str = Body(..., embed=True)):
    """APP 已把登录态写到本地后回调，标记会话用完。
    轮询阶段不做这件事：poll 的响应可能在路上丢掉，那时会话必须还能再取一次。"""
    consume_qr_session(session_id)
    print(f"qr_login_consume session_id={session_id}")
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": {"status": "consumed"}})


def _wx_callback_page(icon: str, msg: str, tip: str):
    """扫码授权后微信里显示的结果页"""
    return f"""
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{display:flex;justify-content:center;align-items:center;height:100vh;
margin:0;font-family:sans-serif;background:#f5f5f5;}}
.box{{text-align:center;padding:40px;background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.1);}}
.icon{{font-size:48px;}}.msg{{margin-top:16px;font-size:18px;color:#333;}}
.tip{{margin-top:8px;font-size:14px;color:#999;}}</style></head>
<body><div class="box"><div class="icon">{icon}</div>
<div class="msg">{msg}</div>
<div class="tip">{tip}</div></div></body></html>
"""


def _fetch_main_server_token(user_info: dict):
    """拿 unionid 去主服务端换 token，换不到返回空字符串。

    这个 token 主服务端每次请求都要拿去查库（查不到直接 401），所以**不能本地伪造**：
    伪造出来的 token 会让 App 显示「已登录」，但专辑、收藏、购买、灰度全部 401，
    客户端又没有自愈逻辑，用户只能一直卡在这个残废登录态里。
    """
    req_data = json.dumps(user_info, ensure_ascii=False).encode("utf-8")
    for attempt in range(1, MAIN_SERVER_LOGIN_RETRIES + 1):
        try:
            req = urllib.request.Request(
                MAIN_SERVER_LOGIN_UNIONID,
                data=req_data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                login_resp = json.loads(r.read())
            print(f"wx_callback main_server resp code={login_resp.get('code')} attempt={attempt}")
            if login_resp.get("code") == 200:
                token = login_resp.get("data", {}).get("token", "")
                if token:
                    print(f"wx_callback got token from main server unionid={user_info.get('unionid')}")
                    return token
        except Exception as e:
            print(f"wx_callback main_server login/unionid failed (attempt {attempt}): {e}")
        if attempt < MAIN_SERVER_LOGIN_RETRIES:
            time.sleep(MAIN_SERVER_LOGIN_RETRY_INTERVAL)
    return ""


@app.get("/htz-api-pyservice/api/v1/wx/callback", response_class=HTMLResponse)
def wx_callback(code: str = "", state: str = ""):
    """微信网站应用 OAuth 回调：用 code 直接换取用户信息，更新 session"""
    print(f"wx_callback code={code} state={state}")
    if not code or not state:
        return _wx_callback_page("❌", "参数错误", "请回到 APP 刷新二维码后重试")

    try:
        # 1. 用公众号 appid + appsecret 换取 access_token + openid
        appid, appsecret = _get_gzh_aksk()
        if not appsecret:
            print("wx_callback: appsecret not configured")
            return _wx_callback_page("❌", "服务配置错误", "请稍后再试")

        token_qs = urllib.parse.urlencode({
            "appid": appid, "secret": appsecret,
            "code": code, "grant_type": "authorization_code"
        })
        with urllib.request.urlopen(
            f"https://api.weixin.qq.com/sns/oauth2/access_token?{token_qs}", timeout=10
        ) as r:
            token_data = json.loads(r.read().decode())
        print(f"wx_callback token_data={token_data}")
        if "errcode" in token_data:
            raise Exception(f"WeChat token error: {token_data}")

        access_token = token_data["access_token"]
        openid = token_data["openid"]

        # 2. 获取完整用户信息（昵称、头像、unionid 等）
        userinfo_qs = urllib.parse.urlencode(
            {"access_token": access_token, "openid": openid, "lang": "zh_CN"}
        )
        with urllib.request.urlopen(
            f"https://api.weixin.qq.com/sns/userinfo?{userinfo_qs}", timeout=10
        ) as r:
            user_info = json.loads(r.read().decode("utf-8"))
        print(f"wx_callback user_info unionid={user_info.get('unionid')}")
        if "errcode" in user_info:
            raise Exception(f"WeChat userinfo error: {user_info}")

        # 3. 补全字段
        user_info.setdefault("country", "")
        user_info.setdefault("language", "")
        user_info.setdefault("privilege", [])

        # 3.5. 直接写入/更新 user_info 表（upsert），避免 App 端崩溃导致用户数据丢失
        try:
            upsert_user_wechat(user_info)
            print(f"wx_callback upsert_user_wechat done unionid={user_info.get('unionid')}")
        except Exception as e:
            print(f"wx_callback upsert_user_wechat error: {e}")

        # 4. 调主服务器 post/login/unionid，用完整 WeixinLoginResp 创建/更新用户并获取 token
        token = _fetch_main_server_token(user_info)
        if not token:
            # 换不到 token 就不能确认这次登录：宁可让用户重扫一次，也不能放一个
            # 主服务端不认的 token 进 App（见 _fetch_main_server_token 的说明）。
            print(f"wx_callback no token from main server, expire session={state}")
            expire_qr_session(state)
            return _wx_callback_page("❌", "登录失败", "请回到 APP 刷新二维码后重试")

        # 5. 更新会话状态
        confirm_qr_session(state, token, json.dumps(user_info, ensure_ascii=False))
        print(f"wx_callback confirmed session={state}")
        return _wx_callback_page("✅", "授权成功", "请返回 APP 继续操作")
    except Exception as e:
        print(f"wx_callback error: {e}")
        expire_qr_session(state)
        return _wx_callback_page("❌", "授权失败", "请回到 APP 刷新二维码后重试")


# ===== 网页管理后台 =====
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin@1234"
ADMIN_TOKEN = "htz_admin_token_2024"

# ===== 手机型号映射管理 =====

@app.get("/htz-api-pyservice/api/v1/phone-model-mapping/list")
def phone_model_mapping_list():
    result = get_all_phone_model_mappings()
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.post("/htz-api-pyservice/api/v1/phone-model-mapping/add")
def phone_model_mapping_add(item: PhoneModelMappingItem):
    print(f"phone_model_mapping_add: {item}")
    try:
        result = add_phone_model_mapping(item)
        return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})
    except Exception as e:
        return JSONResponse({"code": "500", "msg": str(e), "data": None})

@app.post("/htz-api-pyservice/api/v1/phone-model-mapping/update")
def phone_model_mapping_update(item: PhoneModelMappingItem):
    print(f"phone_model_mapping_update: {item}")
    update_phone_model_mapping(item)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.post("/htz-api-pyservice/api/v1/phone-model-mapping/delete")
def phone_model_mapping_delete(id: int):
    print(f"phone_model_mapping_delete id: {id}")
    delete_phone_model_mapping(id)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

# ===== 灰度发布 =====
# 新版本发布后默认处于灰度状态，只有白名单手机号的用户能收到升级提示；
# 白名单里的**每一位**管理员都在 App 内点过「确认发布」之后，该版本才对所有人放开，
# 只要还有人没确认就一直留在灰度中。
#
# 白名单认的是手机号，手机号要拿 unionid 去 user_info 里查。客户端 header 里的 token 是
# 主服务端签发的 UUID、不是 unionid，所以必须用单独的 unionid 头，token 只作为老客户端的兜底。

@app.get("/htz-api-pyservice/api/v1/release/status")
def release_status(version_code: int, token: str = Header(default=""),
                   unionid: str = Header(default="")):
    """客户端查询某个版本是否已全量放开，同时下发白名单供客户端判断入口可见性。"""
    telephone = get_user_telephone(unionid or token)
    confirmed_phones = get_release_confirm_phones(version_code)
    result = {
        "version_code": version_code,
        "released": is_version_released(version_code),
        "max_released_version": get_max_released_version(),
        "gray_phones": GRAY_RELEASE_PHONES,
        "is_gray_user": is_gray_phone(telephone),
        # 确认进度：凑齐 required_count 票才会真正全量放开
        "confirmed_count": len(confirmed_phones),
        "required_count": len(GRAY_RELEASE_PHONES),
        "confirmed_by_me": bool(telephone) and telephone.strip() in confirmed_phones,
    }
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.post("/htz-api-pyservice/api/v1/release/promote")
def release_promote(version_code: int = Body(...), version_name: str = Body(default=""),
                    token: str = Header(default=""), unionid: str = Header(default="")):
    """确认发布：登记一票确认，白名单里所有人都确认过之后才真正放开给全量用户。仅白名单手机号可操作。"""
    user_key = unionid or token
    telephone = get_user_telephone(user_key)
    if not is_gray_phone(telephone):
        print(f"release_promote denied: user_key={user_key} telephone={telephone}")
        return JSONResponse({"code": "403", "msg": "无权限确认发布", "data": None})

    record_release_confirm(version_code, version_name, user_key, telephone)
    confirmed_count = len(get_release_confirm_phones(version_code))
    required_count = len(GRAY_RELEASE_PHONES)
    released = is_release_fully_confirmed(version_code)
    if released:
        promote_release(version_code, version_name, user_key, telephone)
    print(f"release_promote ok: version_code={version_code} by {telephone} "
          f"confirmed={confirmed_count}/{required_count} released={released}")
    return JSONResponse({"code": "0", "msg": "SUCCESS",
                         "data": {"version_code": version_code,
                                  "released": released,
                                  "confirmed_count": confirmed_count,
                                  "required_count": required_count}})

@app.get("/htz-api-pyservice/api/v1/release/list")
def release_list():
    """管理端查看已全量放开的版本记录。"""
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": get_all_released_versions()})

@app.post("/htz-api-pyservice/api/v1/release/revoke")
def release_revoke(version_code: int = Body(..., embed=True)):
    """管理端回退：把版本重新打回灰度状态。"""
    revoke_release(version_code)
    print(f"release_revoke: version_code={version_code}")
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

@app.post("/htz-api-pyservice/api/v1/admin/login")
def admin_login(username: str = Body(...), password: str = Body(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        return JSONResponse({"code": "0", "msg": "SUCCESS", "data": {"token": ADMIN_TOKEN}})
    return JSONResponse({"code": "401", "msg": "用户名或密码错误", "data": None})

@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    html_path = os.path.join(os.path.dirname(__file__), "static", "admin.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

#uvicorn htz-api-server:app --host=0.0.0.0 --port=8082