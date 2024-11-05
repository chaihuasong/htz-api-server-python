from fastapi import FastAPI, HTTPException
from fastapi.exceptions  import RequestValidationError
from fastapi.responses  import JSONResponse
import logging
from pydantic import BaseModel
import sqlite3

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

class RequestItem(BaseModel):
    pkg: str
    phone: str
    type: str
    info: str
    time: str
    user: str

def save_log_info(request_item: RequestItem):
    # 创建数据库连接
    conn = sqlite3.connect('htz.db')
    cursor = conn.cursor()

    # 插入数据到数据库
    cursor.execute("""
        INSERT INTO log_info (pkg, phone, type, info, time, user)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (request_item.pkg,  request_item.phone,  request_item.type,  request_item.info,  request_item.time,  request_item.user))

    # 提交事务
    conn.commit()

    # 关闭游标和连接
    cursor.close()

@app.post("/htz-api-pyservice/api/v1/savelog")
def save_loginfo(request_item: RequestItem):
    print(request_item)
    save_log_info(request_item)
    return JSONResponse({"code": "0", "msg": "SUCCESS", "data": "null"})