import json
import sqlite3
import threading
from contextlib import contextmanager
from request import *
from datetime import datetime

DB_NAME = 'htz.db'

# 线程本地存储，每个线程复用自己的连接
_local = threading.local()

def _get_connection():
    """获取当前线程的数据库连接（连接复用）"""
    if not hasattr(_local, 'conn') or _local.conn is None:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # 使用 Row 对象，可以按列名访问
        conn.execute("PRAGMA journal_mode=WAL")  # WAL 模式提升并发性能
        conn.execute("PRAGMA synchronous=NORMAL")  # 平衡性能和安全
        conn.execute("PRAGMA cache_size=-64000")  # 64MB 缓存
        _local.conn = conn
    return _local.conn

@contextmanager
def get_cursor():
    """上下文管理器：获取游标，自动处理提交和异常"""
    conn = _get_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()

def _row_to_dict(row):
    """将 sqlite3.Row 转换为字典"""
    if row is None:
        return None
    return dict(row)

def _rows_to_list(rows):
    """将 sqlite3.Row 列表转换为字典列表"""
    return [dict(row) for row in rows] if rows else []

# ===== 日志操作 =====

def save_log_info(request_item: RequestItem):
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO log_info (pkg, version, phone, type, info, time, user)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (request_item.pkg, request_item.version, request_item.phone,
              request_item.type, request_item.info, request_item.time, request_item.user))

def get_log_info(pkg: str):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM log_info WHERE pkg=?", (pkg,))
        result = cursor.fetchall()
        data = _rows_to_list(result)
    return json.dumps(data, indent=4)

def get_all_logs():
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM log_info ORDER BY id DESC LIMIT 500")
        return _rows_to_list(cursor.fetchall())

# ===== AK/SK 操作 =====

def get_ak_sk(appName: str):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM aksk WHERE appName=?", (appName,))
        result = cursor.fetchone()
        data = _row_to_dict(result) or {}
    return json.dumps(data, indent=4)

def get_all_aksk():
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM aksk")
        return _rows_to_list(cursor.fetchall())

def insert_aksk(aksk: AkskRequestItem):
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO aksk (appName, platform, accessKey, accessKeySecure, note)
            VALUES (?, ?, ?, ?, ?)
        """, (aksk.appName, aksk.platform, aksk.accessKey, aksk.accessKeySecure, aksk.note))

def update_aksk(aksk: AkskRequestItem):
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE aksk SET appName=?, platform=?, accessKey=?, accessKeySecure=?, note=?
            WHERE id=?
        """, (aksk.appName, aksk.platform, aksk.accessKey, aksk.accessKeySecure, aksk.note, aksk.id))

def delete_aksk(id: int):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM aksk WHERE id=?", (id,))

# ===== 用户操作 =====

def get_all_users():
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM user_info")
        return _rows_to_list(cursor.fetchall())

def insert_user(user: UserInfoItem):
    formatted_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute('''
            INSERT INTO user_info (unionid, nickname, openid, sex, headimgurl, country,
                province, city, language, group_id, telephone, pwd, sign, note,
                create_time, last_update_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user.unionid, user.nickname, user.openid, user.sex, user.headimgurl,
              user.country, user.province, user.city, user.language, user.group_id,
              user.telephone, user.pwd, user.sign, user.note, formatted_time, formatted_time))

def delete_user_by_unionid(unionid: str):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM user_info WHERE unionid=?", (unionid,))

def update_user_by_unionid(user: UserInfoItem):
    formatted_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE user_info SET nickname=?, openid=?, sex=?, headimgurl=?, country=?,
                province=?, city=?, language=?, group_id=?, telephone=?, pwd=?, sign=?,
                note=?, last_update_time=?
            WHERE unionid=?
        """, (user.nickname, user.openid, user.sex, user.headimgurl, user.country,
              user.province, user.city, user.language, user.group_id, user.telephone,
              user.pwd, user.sign, user.note, formatted_time, user.unionid))

def select_user_by_unionid(unionid: str):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM user_info WHERE unionid=?", (unionid,))
        result = cursor.fetchone()
        data = _row_to_dict(result) or {}
    return json.dumps(data, indent=4)

# ===== 用量统计操作 =====

def init_app_usage_table():
    with get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                user_id TEXT DEFAULT '',
                date TEXT NOT NULL,
                open_count INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                version TEXT DEFAULT '',
                pkg TEXT DEFAULT '',
                created_at TEXT,
                UNIQUE(device_id, date)
            )
        """)

def save_app_usage(item: AppUsageItem):
    formatted_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO app_usage (device_id, user_id, date, open_count, duration_ms, version, pkg, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, date) DO UPDATE SET
                open_count = excluded.open_count,
                duration_ms = excluded.duration_ms,
                user_id = CASE WHEN excluded.user_id != '' THEN excluded.user_id ELSE app_usage.user_id END,
                version = CASE WHEN excluded.version != '' THEN excluded.version ELSE app_usage.version END,
                pkg = CASE WHEN excluded.pkg != '' THEN excluded.pkg ELSE app_usage.pkg END,
                created_at = excluded.created_at
        """, (item.device_id, item.user_id, item.date, item.open_count,
              item.duration_ms, item.version, item.pkg, formatted_time))

def save_app_usage_batch(items: list):
    for item in items:
        save_app_usage(item)

def get_all_app_usage():
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT a.*, u.nickname
            FROM app_usage a
            LEFT JOIN user_info u ON a.user_id = u.unionid
            ORDER BY a.date DESC, a.id DESC
            LIMIT 1000
        """)
        return _rows_to_list(cursor.fetchall())

def get_app_usage_summary():
    with get_cursor() as cursor:
        # 总设备数
        cursor.execute("SELECT COUNT(DISTINCT device_id) FROM app_usage")
        total_devices = cursor.fetchone()[0]

        # 总打开次数
        cursor.execute("SELECT COALESCE(SUM(open_count), 0) FROM app_usage")
        total_opens = cursor.fetchone()[0]

        # 总使用时长
        cursor.execute("SELECT COALESCE(SUM(duration_ms), 0) FROM app_usage")
        total_duration = cursor.fetchone()[0]

        # 总使用天数（有记录的日期数）
        cursor.execute("SELECT COUNT(DISTINCT date) FROM app_usage")
        total_days = cursor.fetchone()[0]

        # 今日统计
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("SELECT COUNT(DISTINCT device_id), COALESCE(SUM(open_count), 0), COALESCE(SUM(duration_ms), 0) FROM app_usage WHERE date=?", (today,))
        today_row = cursor.fetchone()
        today_devices = today_row[0]
        today_opens = today_row[1]
        today_duration = today_row[2]

        # 最近30天每日统计
        cursor.execute("""
            SELECT date, COUNT(DISTINCT device_id) as devices, SUM(open_count) as opens, SUM(duration_ms) as duration
            FROM app_usage
            WHERE date >= date('now', '-30 days')
            GROUP BY date
            ORDER BY date ASC
        """)
        daily_stats = _rows_to_list(cursor.fetchall())

        return {
            "total_devices": total_devices,
            "total_opens": total_opens,
            "total_duration_ms": total_duration,
            "total_days": total_days,
            "today_devices": today_devices,
            "today_opens": today_opens,
            "today_duration_ms": today_duration,
            "daily_stats": daily_stats
        }
