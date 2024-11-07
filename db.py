import json
import sqlite3

from request import *
from datetime import datetime

DB_NAME = 'htz.db'

def save_log_info(request_item: RequestItem):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO log_info (pkg, phone, type, info, time, user)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (request_item.pkg,  request_item.phone,  request_item.type,  request_item.info,  request_item.time,  request_item.user))
    conn.commit()
    cursor.close()
    conn.close()

def get_log_info(pkg: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    sql=f"SELECT * FROM log_info WHERE pkg='{pkg}'"
    print(sql)
    cursor.execute(sql)
    result = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    if result is None:
        data = {}
    else:
        data = [dict(zip(columns, row)) for row in result]
    cursor.close()
    conn.close()
    return json.dumps(data, indent=4)

def get_ak_sk(appName: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    sql=f"SELECT * FROM aksk WHERE appName='{appName}'"
    print(sql)
    cursor.execute(sql)
    result = cursor.fetchone()
    columns = [description[0] for description in cursor.description]
    #data = [dict(zip(columns, row)) for row in result]
    if result is None:
        data = {}
    else:
        data = dict(zip(columns, result))
    cursor.close()
    conn.close()
    return json.dumps(data, indent=4)

def insert_user(user: UserInfoItem):
    current_time = datetime.now()
    formatted_time = current_time.strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO user_info (unionid, nickname, openid, sex, headimgurl, country, province, city, language, group_id, telephone, pwd, sign, note, create_time, last_update_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user.unionid, user.nickname, user.openid, user.sex, user.headimgurl, user.country, user.province, user.city, user.language, user.group_id, user.telephone, user.pwd, user.sign, user.note, formatted_time, formatted_time))
    conn.commit()
    conn.close()

def delete_user_by_unionid(unionid):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    sql=f"DELETE FROM user_info WHERE unionid ='{unionid}'"
    print(sql)
    cursor.execute(sql)
    conn.commit()
    conn.close()

def update_user_by_unionid(user: UserInfoItem):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    current_time = datetime.now()
    formatted_time = current_time.strftime('%Y-%m-%d %H:%M:%S')
    sql=f"UPDATE user_info SET nickname='{user.nickname}', openid='{user.openid}', sex='{user.sex}', headimgurl='{user.headimgurl}', country='{user.country}', province='{user.province}', city='{user.city}', language='{user.language}', group_id='{user.group_id}', telephone='{user.telephone}', pwd='{user.pwd}', sign='{user.sign}', note='{user.note}', last_update_time='{formatted_time}' WHERE unionid='{user.unionid}'"
    print(sql)
    cursor.execute(sql) 
    conn.commit()
    conn.close()

def select_user_by_unionid(unionid):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    sql=f"SELECT * FROM user_info WHERE unionid ='{unionid}'"
    print(sql)
    cursor.execute(sql)
    result = cursor.fetchone()
    columns = [description[0] for description in cursor.description]
    if result is None:
        data = {}
    else:
        data = dict(zip(columns, result))
    conn.close()
    return json.dumps(data, indent=4)