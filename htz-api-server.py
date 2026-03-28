from fastapi import FastAPI, HTTPException
from fastapi.exceptions  import RequestValidationError
from fastapi.responses  import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import logging
import os
import uuid
import json
import time
import urllib.request
import urllib.parse

from request import RequestItem, AkskRequestItem, AppUsageItem
from db import *
from typing import List

# ===== 微信扫码登录配置 =====
# 公众号 APPID，appsecret 存在 aksk 表 appName='htz-gzh' 的 accessKeySecure 字段
WX_GZH_APPID = "wx83aec75c3ca58f0e"
# redirect_uri 须与公众号后台「网页授权域名」一致
WX_REDIRECT_URI = "http://htzchina.org/htz-api-pyservice/api/v1/wx/callback"
# 二维码会话有效期（秒）
QR_SESSION_EXPIRE_SECONDS = 300

# 初始化日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

app = FastAPI()

# 初始化数据库表
init_app_usage_table()
init_qr_session_table()

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """
    handle the exception of incorrect request parameter
    """
    logger.error(exc)
    return JSONResponse({"code": "422", "msg": "bad request parameter", "data": None})

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
    existing_user = select_user_by_unionid(request_item.unionid)
    if existing_user is not None:
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
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})

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
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

@app.get("/htz-api-pyservice/api/v1/usage/summary")
def usage_summary():
    result = get_app_usage_summary()
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": result})

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


@app.get("/htz-api-pyservice/api/v1/wx/callback", response_class=HTMLResponse)
def wx_callback(code: str = "", state: str = ""):
    """微信网站应用 OAuth 回调：用 code 直接换取用户信息，更新 session"""
    print(f"wx_callback code={code} state={state}")
    if not code or not state:
        return "<html><head><meta charset='utf-8'></head><body><p>参数错误</p></body></html>"

    try:
        # 1. 用公众号 appid + appsecret 换取 access_token + openid
        appid, appsecret = _get_gzh_aksk()
        if not appsecret:
            print("wx_callback: appsecret not configured")
            return "<html><head><meta charset='utf-8'></head><body><p>服务配置错误</p></body></html>"

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

        # 4. 调主服务器 post/login/unionid，用完整 WeixinLoginResp 创建/更新用户并获取 token
        token = ""
        try:
            req_data = json.dumps(user_info, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                "http://39.105.174.143:9100/post/login/unionid",
                data=req_data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                login_resp = json.loads(r.read())
            print(f"wx_callback main_server resp code={login_resp.get('code')}")
            if login_resp.get("code") == 200:
                token = login_resp.get("data", {}).get("token", "")
                print(f"wx_callback got token from main server unionid={user_info.get('unionid')}")
        except Exception as e:
            print(f"wx_callback main_server login/unionid failed: {e}")

        if not token:
            token = uuid.uuid4().hex
            print(f"wx_callback fallback uuid token")

        # 5. 更新会话状态
        confirm_qr_session(state, token, json.dumps(user_info, ensure_ascii=False))
        print(f"wx_callback confirmed session={state}")
        return """
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{display:flex;justify-content:center;align-items:center;height:100vh;
margin:0;font-family:sans-serif;background:#f5f5f5;}
.box{text-align:center;padding:40px;background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.1);}
.icon{font-size:48px;}.msg{margin-top:16px;font-size:18px;color:#333;}
.tip{margin-top:8px;font-size:14px;color:#999;}</style></head>
<body><div class="box"><div class="icon">✅</div>
<div class="msg">授权成功</div>
<div class="tip">请返回 APP 继续操作</div></div></body></html>
"""
    except Exception as e:
        print(f"wx_callback error: {e}")
        expire_qr_session(state)
        return "<html><head><meta charset='utf-8'></head><body><p>授权失败，请重试</p></body></html>"


# ===== 网页管理后台 =====
@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    html_path = os.path.join(os.path.dirname(__file__), "static", "admin.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

#uvicorn htz-api-server:app --host=0.0.0.0 --port=8082