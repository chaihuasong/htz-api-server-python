from fastapi import FastAPI, HTTPException
from fastapi.exceptions  import RequestValidationError
from fastapi.responses  import JSONResponse
import logging

from request import RequestItem
from request import AkskRequestItem
from db import *

# 初始化日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

app = FastAPI()

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

#uvicorn htz-api-server:app --host=0.0.0.0 --port=8082