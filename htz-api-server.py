from fastapi import FastAPI, HTTPException
from fastapi.exceptions  import RequestValidationError
from fastapi.responses  import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import logging
import os

from request import RequestItem, AkskRequestItem, AppUsageItem
from db import *
from typing import List

# 初始化日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

app = FastAPI()

# 初始化数据库表
init_app_usage_table()

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

# ===== 网页管理后台 =====
@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    html_path = os.path.join(os.path.dirname(__file__), "static", "admin.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

#uvicorn htz-api-server:app --host=0.0.0.0 --port=8082