import json
import sqlite3
import threading
import uuid
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

def init_log_info_table():
    with get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS log_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pkg TEXT DEFAULT '',
                version TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                type TEXT DEFAULT '',
                info TEXT DEFAULT '',
                time TEXT DEFAULT '',
                user TEXT DEFAULT '',
                unionid TEXT
            )
        """)
        # 为常用查询列创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_log_info_pkg ON log_info(pkg)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_log_info_time ON log_info(time)")
        # 补列：**不能带 DEFAULT ''**，存量行必须留成 NULL 才能和「新客户端报的未登录」区分开
        try:
            cursor.execute("ALTER TABLE log_info ADD COLUMN unionid TEXT")
        except Exception:
            pass  # 列已存在则忽略

def save_log_info(request_item: RequestItem):
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO log_info (pkg, version, phone, type, info, time, user, unionid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (request_item.pkg, request_item.version, request_item.phone,
              request_item.type, request_item.info, request_item.time,
              request_item.user, request_item.unionid))

# 日志归属到人的口径，列表和详情共用一份，避免两处走岔。
#
# 历史包袱：老客户端 user 字段传的是**昵称**，服务端却一直拿它去 JOIN user_info.unionid，
# JOIN 从来没命中过；昵称为空（微信现在大量返回空昵称）时又被判成「未登录」，
# 于是后台显示未登录的其实全是已登录用户。现在身份只认 unionid：
#   unionid 非空  → 已登录，取昵称，昵称为空就退回 unionid
#   unionid = ''  → 新客户端明确报的未登录
#   unionid IS NULL → 老客户端没传这个字段，只能拿昵称顶着显示；
#                     昵称也为空时是真的判不出来，标成「未知」而不是冒充「未登录」
_LOG_USER_NAME_SQL = """
    CASE WHEN l.unionid IS NOT NULL AND l.unionid != ''
              THEN COALESCE(NULLIF(u.nickname, ''), l.unionid)
         WHEN l.unionid = '' THEN '未登录'
         WHEN l.user != '' THEN l.user
         ELSE '未知(旧版本)' END
"""

def upsert_user_wechat(wechat_user_info: dict):
    """微信扫码回调中直接写入/更新用户信息（upsert），避免 App 端崩溃导致数据丢失"""
    unionid = wechat_user_info.get("unionid", "").strip()
    if not unionid:
        return
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    existing = select_user_dict_by_unionid(unionid)
    with get_cursor() as cursor:
        if existing:
            # 已存在用户：只补空，不覆盖用户自定义资料。
            # 头像特殊处理：为空或本来就是微信头像（qlogo.cn 会过期）时才刷新为最新微信头像，
            # OSS 自定义头像保持不动。
            def _keep(field: str):
                old = (existing.get(field) or "").strip()
                return old if old else str(wechat_user_info.get(field, ""))

            old_head = (existing.get("headimgurl") or "").strip()
            if old_head and "qlogo.cn" not in old_head:
                headimgurl = old_head
            else:
                headimgurl = wechat_user_info.get("headimgurl", old_head)

            cursor.execute("""
                UPDATE user_info SET
                    nickname=?, openid=?, sex=?, headimgurl=?, country=?,
                    province=?, city=?, language=?, last_update_time=?
                WHERE unionid=?
            """, (
                _keep("nickname"),
                wechat_user_info.get("openid", existing.get("openid", "")),
                _keep("sex"),
                headimgurl,
                _keep("country"),
                _keep("province"),
                _keep("city"),
                _keep("language"),
                now,
                unionid
            ))
        else:
            cursor.execute("""
                INSERT INTO user_info (unionid, nickname, openid, sex, headimgurl,
                    country, province, city, language, group_id, telephone, pwd, sign,
                    note, create_time, last_update_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                unionid,
                wechat_user_info.get("nickname", ""),
                wechat_user_info.get("openid", ""),
                str(wechat_user_info.get("sex", "")),
                wechat_user_info.get("headimgurl", ""),
                wechat_user_info.get("country", ""),
                wechat_user_info.get("province", ""),
                wechat_user_info.get("city", ""),
                wechat_user_info.get("language", ""),
                "",   # group_id
                "",   # telephone
                "",   # pwd
                "",   # sign
                "android",  # note
                now, now
            ))


def select_user_dict_by_unionid(unionid: str):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM user_info WHERE unionid=?", (unionid,))
        return _row_to_dict(cursor.fetchone())


def get_log_info(pkg: str):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM log_info WHERE pkg=?", (pkg,))
        result = cursor.fetchall()
        data = _rows_to_list(result)
    return json.dumps(data, indent=4)

# 保持 500：后台搜索是前端对已截断的 info 做匹配（admin.html filterLogs），
# 调小会让堆栈里 150 字符之后的异常信息搜不到。响应体大小已由 gzip 解决（343KB→12KB），
# 再截到 150 只省 6KB，不值得拿搜索范围换。
LOG_INFO_TRUNCATE_LENGTH = 500

def get_all_logs():
    with get_cursor() as cursor:
        cursor.execute(f"""
            SELECT l.id, l.pkg, l.version, l.phone, l.type,
                   SUBSTR(l.info, 1, {LOG_INFO_TRUNCATE_LENGTH}) || CASE WHEN LENGTH(l.info) > {LOG_INFO_TRUNCATE_LENGTH} THEN '...' ELSE '' END as info,
                   l.time, l.user, l.unionid,
                   {_LOG_USER_NAME_SQL} as user_name
            FROM log_info l
            LEFT JOIN user_info u ON u.unionid = l.unionid
            ORDER BY l.id DESC
            LIMIT 500
        """)
        return _rows_to_list(cursor.fetchall())

def get_log_detail(log_id: int):
    with get_cursor() as cursor:
        cursor.execute(f"""
            SELECT l.*,
                   {_LOG_USER_NAME_SQL} as user_name
            FROM log_info l
            LEFT JOIN user_info u ON u.unionid = l.unionid
            WHERE l.id=?
        """, (log_id,))
        return _row_to_dict(cursor.fetchone())

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

def init_user_info_table():
    with get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_info (
                unionid TEXT PRIMARY KEY,
                nickname TEXT DEFAULT '',
                openid TEXT DEFAULT '',
                sex TEXT DEFAULT '',
                headimgurl TEXT DEFAULT '',
                country TEXT DEFAULT '',
                province TEXT DEFAULT '',
                city TEXT DEFAULT '',
                language TEXT DEFAULT '',
                group_id TEXT DEFAULT '',
                telephone TEXT DEFAULT '',
                pwd TEXT DEFAULT '',
                sign TEXT DEFAULT '',
                note TEXT DEFAULT '',
                create_time TEXT,
                last_update_time TEXT
            )
        """)

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

def update_user_telephone_by_unionid(unionid: str, telephone: str):
    formatted_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE user_info SET telephone=?, last_update_time=?
            WHERE unionid=?
        """, (telephone, formatted_time, unionid))
        return cursor.rowcount

def select_user_dict_by_telephone(telephone: str):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM user_info WHERE telephone=?", (telephone,))
        return _row_to_dict(cursor.fetchone())

# 与十年持志系统双向同步的「公共资料字段」白名单。
# 注意：unionid / openid / pwd / group_id / note 等为各系统专属字段，绝不跨系统覆盖。
USER_SYNC_FIELDS = ["nickname", "sex", "headimgurl",
                    "country", "province", "city", "language", "sign"]

def apply_user_sync_by_telephone(telephone: str, incoming: dict, incoming_time: str = ""):
    """按手机号匹配本地用户，合并十年持志推送来的公共资料字段。
    规则：非空优先 + 最近更新优先（incoming_time / last_update_time 形如 'YYYY-MM-DD HH:MM:SS'，可字典序比较）。
    - 入站数据为空的字段一律不覆盖本地已有值；
    - 仅更新已用手机号匹配上的记录，不跨系统新建用户；
    - 不触发回推（由调用方保证），避免双向死循环。
    返回 True=已匹配（含无变化），False=未找到该手机号用户。"""
    telephone = (telephone or "").strip()
    if not telephone:
        return False
    incoming_time = (incoming_time or "").strip()
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM user_info WHERE telephone=?", (telephone,))
        local = _row_to_dict(cursor.fetchone())
        if not local:
            return False
        local_time = (local.get("last_update_time") or "").strip()
        merged = {}
        changed = False
        for f in USER_SYNC_FIELDS:
            inc = incoming.get(f)
            inc = "" if inc is None else str(inc).strip()
            loc = local.get(f)
            loc = "" if loc is None else str(loc)
            take = False
            if inc:
                if not loc:
                    take = True
                elif incoming_time and (not local_time or incoming_time >= local_time):
                    take = True
            if take and inc != loc:
                merged[f] = inc
                changed = True
            else:
                merged[f] = loc
        if not changed:
            return True
        new_time = max([t for t in (local_time, incoming_time) if t],
                       default=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        cursor.execute("""
            UPDATE user_info SET nickname=?, sex=?, headimgurl=?, country=?,
                province=?, city=?, language=?, sign=?, last_update_time=?
            WHERE telephone=?
        """, (merged["nickname"], merged["sex"], merged["headimgurl"], merged["country"],
              merged["province"], merged["city"], merged["language"], merged["sign"],
              new_time, telephone))
        return True

def select_user_by_telephone(telephone: str):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM user_info WHERE telephone=?", (telephone,))
        result = cursor.fetchone()
        data = _row_to_dict(result) or {}
    return json.dumps(data, indent=4)

def select_user_by_unionid(unionid: str):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM user_info WHERE unionid=?", (unionid,))
        result = cursor.fetchone()
        data = _row_to_dict(result) or {}
    return json.dumps(data, indent=4)

# ===== 用量统计操作 =====

# ===== 二维码登录会话操作 =====

def init_qr_session_table():
    with get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS qr_session (
                session_id TEXT PRIMARY KEY,
                status TEXT DEFAULT 'pending',
                token TEXT DEFAULT '',
                user_info TEXT DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT
            )
        """)

def create_qr_session(session_id: str):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO qr_session (session_id, status, token, user_info, created_at, updated_at)
            VALUES (?, 'pending', '', '{}', ?, ?)
        """, (session_id, now, now))

def get_qr_session(session_id: str):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM qr_session WHERE session_id=?", (session_id,))
        return _row_to_dict(cursor.fetchone())

def confirm_qr_session(session_id: str, token: str, user_info: str):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE qr_session SET status='confirmed', token=?, user_info=?, updated_at=?
            WHERE session_id=?
        """, (token, user_info, now, session_id))

def expire_qr_session(session_id: str):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE qr_session SET status='expired', updated_at=? WHERE session_id=?
        """, (now, session_id))

def consume_qr_session(session_id: str):
    """客户端确认已把登录态存到本地后调用，防止同一个 session 被反复取用。
    只有 confirmed 的会话能被消费；轮询本身不消费，否则响应一丢用户就登不上了。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE qr_session SET status='consumed', updated_at=?
            WHERE session_id=? AND status='confirmed'
        """, (now, session_id))

# ===== 意见反馈 =====

def init_feedback_table():
    with get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT DEFAULT '',
                nickname TEXT DEFAULT '',
                contact TEXT DEFAULT '',
                content TEXT NOT NULL,
                category TEXT DEFAULT '',
                pkg TEXT DEFAULT '',
                version TEXT DEFAULT '',
                phone_model TEXT DEFAULT '',
                os_version TEXT DEFAULT '',
                device_id TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                reply TEXT DEFAULT '',
                image_urls TEXT DEFAULT '',
                video_url TEXT DEFAULT '',
                created_at TEXT,
                updated_at TEXT
            )
        """)
        # 兼容旧表，补充新列
        for col, definition in [("image_urls", "TEXT DEFAULT ''"), ("video_url", "TEXT DEFAULT ''"), ("engineering_model", "TEXT DEFAULT ''")]:
            try:
                cursor.execute(f"ALTER TABLE feedback ADD COLUMN {col} {definition}")
            except Exception:
                pass


def save_feedback(item: FeedbackItem):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO feedback (user_id, nickname, contact, content, category,
                pkg, version, phone_model, engineering_model, os_version, device_id, status, reply,
                image_urls, video_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (item.user_id, item.nickname, item.contact, item.content, item.category,
              item.pkg, item.version, item.phone_model, item.engineering_model, item.os_version, item.device_id,
              item.status or "pending", item.reply, item.image_urls, item.video_url, now, now))


def get_all_feedback():
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT f.*, u.nickname AS user_nickname
            FROM feedback f
            LEFT JOIN user_info u ON f.user_id = u.unionid
            ORDER BY f.id DESC
            LIMIT 1000
        """)
        return _rows_to_list(cursor.fetchall())


def update_feedback(item: FeedbackItem):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE feedback SET status=?, reply=?, updated_at=?
            WHERE id=?
        """, (item.status, item.reply, now, item.id))


def delete_feedback(id: int):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM feedback WHERE id=?", (id,))


# ===== 系统通知 =====

def _now_millis():
    return str(int(datetime.now().timestamp() * 1000))


def init_notification_table():
    with get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_notification (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                msg TEXT NOT NULL,
                status TEXT DEFAULT 'published',
                created_at TEXT,
                updated_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_notification_read (
                user_id TEXT NOT NULL,
                notification_id TEXT NOT NULL,
                read_at TEXT,
                PRIMARY KEY (user_id, notification_id)
            )
        """)


def save_notification(item: NotificationItem):
    now = _now_millis()
    notification_id = item.id or uuid.uuid4().hex
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO system_notification (id, title, msg, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                msg = excluded.msg,
                status = excluded.status,
                updated_at = excluded.updated_at
        """, (notification_id, item.title, item.msg, item.status or "published", now, now))
    return notification_id


def get_all_notifications():
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT id, title, msg, status, created_at, updated_at
            FROM system_notification
            ORDER BY CAST(created_at AS INTEGER) DESC
            LIMIT 1000
        """)
        return _rows_to_list(cursor.fetchall())


def delete_notification(id: str):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM user_notification_read WHERE notification_id=?", (id,))
        cursor.execute("DELETE FROM system_notification WHERE id=?", (id,))


def get_user_notifications(user_id: str, page_index: int = 0, page_size: int = 500):
    page_index = max(page_index or 0, 0)
    page_size = min(max(page_size or 500, 1), 500)
    offset = page_index * page_size
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT n.id, n.title, n.msg, n.created_at,
                   CASE WHEN r.notification_id IS NULL THEN 0 ELSE 1 END AS is_read
            FROM system_notification n
            LEFT JOIN user_notification_read r
                ON r.notification_id = n.id AND r.user_id = ?
            WHERE n.status = 'published'
            ORDER BY CAST(n.created_at AS INTEGER) DESC
            LIMIT ? OFFSET ?
        """, (user_id or "", page_size, offset))
        rows = _rows_to_list(cursor.fetchall())
    for row in rows:
        row["is_read"] = bool(row.get("is_read"))
    return rows


def mark_user_notifications_read(user_id: str, notification_ids: list):
    if not user_id or not notification_ids:
        return 0
    now = _now_millis()
    unique_ids = list(dict.fromkeys([str(item) for item in notification_ids if item]))
    with get_cursor() as cursor:
        cursor.executemany("""
            INSERT INTO user_notification_read (user_id, notification_id, read_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, notification_id) DO UPDATE SET read_at=excluded.read_at
        """, [(user_id, notification_id, now) for notification_id in unique_ids])
    return len(unique_ids)


# ===== 用量统计初始化 =====

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
                phone_model TEXT DEFAULT '',
                os_version TEXT DEFAULT '',
                created_at TEXT,
                UNIQUE(device_id, user_id, date)
            )
        """)
        # 兼容旧表，补充新列
        for col, definition in [("phone_model", "TEXT DEFAULT ''"), ("os_version", "TEXT DEFAULT ''"), ("network_type", "TEXT DEFAULT ''"), ("source", "TEXT DEFAULT ''"), ("engineering_model", "TEXT DEFAULT ''"), ("play_duration_ms", "INTEGER DEFAULT 0")]:
            try:
                cursor.execute(f"ALTER TABLE app_usage ADD COLUMN {col} {definition}")
            except Exception:
                pass  # 列已存在则忽略
        _migrate_app_usage_unique_key(cursor)
        # 唯一索引以 device_id 打头，按 user_id 查（学习时长找回、后台用户详情）用不上。
        # 必须放在迁移之后建：迁移会重建表，先建的索引会跟着旧表一起没掉
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_usage_user ON app_usage(user_id)")

def _migrate_app_usage_unique_key(cursor):
    """
    唯一键从 (device_id, date) 改成 (device_id, user_id, date)。

    学习时长要按用户回灌到客户端，一台设备上换过账号的话，旧的唯一键会让两个账号
    当天的数据互相覆盖。SQLite 改不了约束，只能建新表搬数据。
    """
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='app_usage'")
    row = cursor.fetchone()
    if row is None:
        return
    table_sql = (row[0] or "").replace(" ", "")
    if "UNIQUE(device_id,date)" not in table_sql:
        return  # 已经是新结构

    cursor.execute("PRAGMA table_info(app_usage)")
    columns = [r[1] for r in cursor.fetchall() if r[1] != "id"]
    column_list = ", ".join(columns)
    cursor.execute("DROP TABLE IF EXISTS app_usage_old")
    cursor.execute("ALTER TABLE app_usage RENAME TO app_usage_old")
    cursor.execute("""
        CREATE TABLE app_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            user_id TEXT DEFAULT '',
            date TEXT NOT NULL,
            open_count INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            play_duration_ms INTEGER DEFAULT 0,
            version TEXT DEFAULT '',
            pkg TEXT DEFAULT '',
            phone_model TEXT DEFAULT '',
            engineering_model TEXT DEFAULT '',
            os_version TEXT DEFAULT '',
            network_type TEXT DEFAULT '',
            source TEXT DEFAULT '',
            created_at TEXT,
            UNIQUE(device_id, user_id, date)
        )
    """)
    cursor.execute(f"INSERT INTO app_usage ({column_list}) SELECT {column_list} FROM app_usage_old")
    cursor.execute("DROP TABLE app_usage_old")
    print("app_usage unique key migrated to (device_id, user_id, date)")

def save_app_usage(item: AppUsageItem):
    formatted_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO app_usage (device_id, user_id, date, open_count, duration_ms, play_duration_ms, version, pkg, phone_model, engineering_model, os_version, network_type, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, user_id, date) DO UPDATE SET
                open_count = MAX(app_usage.open_count, excluded.open_count),
                duration_ms = MAX(app_usage.duration_ms, excluded.duration_ms),
                -- 客户端上报的是本设备当日累计值，取 MAX 保证重复上报幂等；
                -- 用户清过数据后本地归零，也不会把服务端已有的时长抹掉
                play_duration_ms = MAX(app_usage.play_duration_ms, excluded.play_duration_ms),
                version = CASE WHEN excluded.version != '' THEN excluded.version ELSE app_usage.version END,
                pkg = CASE WHEN excluded.pkg != '' THEN excluded.pkg ELSE app_usage.pkg END,
                phone_model = CASE WHEN excluded.phone_model != '' THEN excluded.phone_model ELSE app_usage.phone_model END,
                engineering_model = CASE WHEN excluded.engineering_model != '' THEN excluded.engineering_model ELSE app_usage.engineering_model END,
                os_version = CASE WHEN excluded.os_version != '' THEN excluded.os_version ELSE app_usage.os_version END,
                network_type = CASE WHEN excluded.network_type != '' THEN excluded.network_type ELSE app_usage.network_type END,
                source = CASE WHEN excluded.source != '' THEN excluded.source ELSE app_usage.source END,
                created_at = excluded.created_at
        """, (item.device_id, item.user_id, item.date, item.open_count,
              item.duration_ms, item.play_duration_ms, item.version, item.pkg, item.phone_model, item.engineering_model, item.os_version, item.network_type, item.source, formatted_time))

def save_app_usage_batch(items: list):
    for item in items:
        save_app_usage(item)

def get_all_app_usage():
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT a.*,
                   CASE WHEN a.user_id = '' THEN '未登录'
                        WHEN u.nickname IS NULL OR u.nickname = '' THEN '-'
                        ELSE u.nickname END as nickname
            FROM app_usage a
            LEFT JOIN user_info u ON a.user_id = u.unionid
            ORDER BY a.date DESC, a.id DESC
            LIMIT 1000
        """)
        return _rows_to_list(cursor.fetchall())

# ===== 用量详情（后台弹窗）=====

def _latest_by_device(column: str, alias: str = "a"):
    """这台设备最近一次上报的非空值。
    不能用 MAX()：那是字典序，1.9.0 会压过 1.10.0，Android 9 会压过 Android 10，
    偏偏升级过的设备才是最想看清楚的。"""
    return (f"(SELECT x.{column} FROM app_usage x "
            f"WHERE x.device_id = {alias}.device_id AND x.{column} != '' "
            f"ORDER BY x.date DESC, x.id DESC LIMIT 1) AS {column}")


_USAGE_SUM_COLUMNS = """
    COALESCE(SUM(open_count), 0) AS opens,
    COALESCE(SUM(duration_ms), 0) AS duration_ms,
    COALESCE(SUM(play_duration_ms), 0) AS play_duration_ms,
    COUNT(DISTINCT date) AS days,
    MIN(date) AS first_date,
    MAX(date) AS last_date
"""


def get_usage_user_detail(user_id: str):
    """
    后台用量统计里点用户名要看的东西：这个 unionid 的资料 + 跨设备汇总 + 按天、按设备明细。

    同一个人可能在多台设备上登录，列表页每行只是「设备 × 用户 × 日期」的一条，
    看不出这个人一共学了多久，所以这里按 unionid 把各台设备重新汇总一遍。
    """
    if not user_id:
        return None
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT unionid, nickname, sex, headimgurl, country, province, city,
                   telephone, note, create_time, last_update_time
            FROM user_info WHERE unionid = ?
        """, (user_id,))
        row = cursor.fetchone()
        profile = _row_to_dict(row) if row else None

        cursor.execute(f"""
            SELECT COUNT(DISTINCT device_id) AS devices, {_USAGE_SUM_COLUMNS}
            FROM app_usage WHERE user_id = ?
        """, (user_id,))
        summary = _row_to_dict(cursor.fetchone())
        if not summary.get("days"):
            return None if profile is None else {"profile": profile, "summary": summary, "daily": [], "devices": []}

        cursor.execute("""
            SELECT date,
                   COUNT(DISTINCT device_id) AS devices,
                   COALESCE(SUM(open_count), 0) AS open_count,
                   COALESCE(SUM(duration_ms), 0) AS duration_ms,
                   COALESCE(SUM(play_duration_ms), 0) AS play_duration_ms
            FROM app_usage WHERE user_id = ?
            GROUP BY date ORDER BY date DESC
        """, (user_id,))
        daily = _rows_to_list(cursor.fetchall())

        cursor.execute(f"""
            SELECT a.device_id,
                   {_latest_by_device("phone_model")},
                   {_latest_by_device("engineering_model")},
                   {_latest_by_device("os_version")},
                   {_latest_by_device("network_type")},
                   {_latest_by_device("source")},
                   {_latest_by_device("version")},
                   {_USAGE_SUM_COLUMNS}
            FROM app_usage a WHERE a.user_id = ?
            GROUP BY a.device_id ORDER BY last_date DESC, opens DESC
        """, (user_id,))
        devices = _rows_to_list(cursor.fetchall())

    return {
        "profile": profile,
        "summary": summary,
        "daily": daily,
        "devices": enrich_list_with_marketing_model(devices, "phone_model"),
    }


def get_usage_device_detail(device_id: str):
    """
    某台设备的用量详情：机型等固定信息 + 汇总 + 按天明细 + 这台设备上登录过的账号。
    """
    if not device_id:
        return None
    with get_cursor() as cursor:
        cursor.execute(f"""
            SELECT {_latest_by_device("phone_model")},
                   {_latest_by_device("engineering_model")},
                   {_latest_by_device("os_version")},
                   {_latest_by_device("network_type")},
                   {_latest_by_device("source")},
                   {_latest_by_device("version")},
                   {_latest_by_device("pkg")},
                   COUNT(DISTINCT CASE WHEN a.user_id != '' THEN a.user_id END) AS users,
                   {_USAGE_SUM_COLUMNS}
            FROM app_usage a WHERE a.device_id = ?
        """, (device_id,))
        summary = _row_to_dict(cursor.fetchone())
        if not summary.get("days"):
            return None
        summary["device_id"] = device_id
        summary = enrich_list_with_marketing_model([summary], "phone_model")[0]

        cursor.execute("""
            SELECT date,
                   COALESCE(SUM(open_count), 0) AS open_count,
                   COALESCE(SUM(duration_ms), 0) AS duration_ms,
                   COALESCE(SUM(play_duration_ms), 0) AS play_duration_ms
            FROM app_usage WHERE device_id = ?
            GROUP BY date ORDER BY date DESC
        """, (device_id,))
        daily = _rows_to_list(cursor.fetchall())

        cursor.execute(f"""
            SELECT a.user_id,
                   COALESCE(NULLIF(u.nickname, ''), '') AS nickname,
                   {_USAGE_SUM_COLUMNS}
            FROM app_usage a
            LEFT JOIN user_info u ON a.user_id = u.unionid
            WHERE a.device_id = ?
            GROUP BY a.user_id
            -- 未登录那段固定排在最后，前面的行数才对得上「登录过的账号」个数
            ORDER BY (a.user_id = '') ASC, last_date DESC, opens DESC
        """, (device_id,))
        users = _rows_to_list(cursor.fetchall())

    return {"summary": summary, "daily": daily, "users": users}


# ===== 学习统计（跨设备找回）=====

def get_user_daily_play_duration(user_id: str):
    """
    某个用户每天的实际播放时长，按 unionid 聚合各台设备。

    客户端换设备或清了数据之后靠这份数据把首页的学习时长找回来。
    """
    if not user_id:
        return []
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT date, COALESCE(SUM(play_duration_ms), 0) AS play_duration_ms
            FROM app_usage
            WHERE user_id = ?
            GROUP BY date
            ORDER BY date DESC
        """, (user_id,))
        return [{"date": row[0], "play_duration_ms": row[1]} for row in cursor.fetchall()]

def init_completed_item_table():
    with get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_completed_item (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                sutra_item_id TEXT NOT NULL,
                created_at TEXT,
                UNIQUE(user_id, sutra_item_id)
            )
        """)

def save_completed_items(user_id: str, item_ids: list):
    """记下用户听完过的条目。只增不删，重复上报忽略。"""
    if not user_id or not item_ids:
        return 0
    formatted_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.executemany("""
            INSERT OR IGNORE INTO user_completed_item (user_id, sutra_item_id, created_at)
            VALUES (?, ?, ?)
        """, [(user_id, item_id, formatted_time) for item_id in item_ids if item_id])
        return cursor.rowcount

def get_completed_items(user_id: str):
    if not user_id:
        return []
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT sutra_item_id FROM user_completed_item WHERE user_id = ?
        """, (user_id,))
        return [row[0] for row in cursor.fetchall()]

# ===== 手机型号映射操作 =====

def init_phone_model_mapping_table():
    with get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS phone_model_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                engineering_model TEXT NOT NULL UNIQUE,
                marketing_model TEXT NOT NULL,
                manufacturer TEXT DEFAULT '',
                remark TEXT DEFAULT '',
                created_at TEXT
            )
        """)

def get_all_phone_model_mappings():
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT * FROM phone_model_mapping
            ORDER BY id DESC
        """)
        return _rows_to_list(cursor.fetchall())

def get_phone_model_mapping(engineering_model: str):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM phone_model_mapping WHERE engineering_model=?", (engineering_model,))
        return _row_to_dict(cursor.fetchone())

def add_phone_model_mapping(item) -> dict:
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO phone_model_mapping (engineering_model, marketing_model, manufacturer, remark, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (item.engineering_model.strip(), item.marketing_model.strip(), item.manufacturer, item.remark, now))
        return {"id": cursor.lastrowid}

def update_phone_model_mapping(item):
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE phone_model_mapping SET
                engineering_model=?, marketing_model=?, manufacturer=?, remark=?
            WHERE id=?
        """, (item.engineering_model.strip(), item.marketing_model.strip(), item.manufacturer, item.remark, item.id))

def delete_phone_model_mapping(id: int):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM phone_model_mapping WHERE id=?", (id,))

# ===== 灰度发布操作 =====

# 灰度期间允许升级、并且有权确认全量的手机号白名单。
GRAY_RELEASE_PHONES = [
    "13585863020",
    "13661513013",
    "13632946727",
    "13294102614",
]

# 全量放开需要的确认票数。原本要求白名单里的每个人都确认，只要有一位管理员没空点，
# 版本就一直卡在灰度里（线上曾连着三个版本没放开、全量用户停在几个版本之前），
# 所以改成够票即可，剩下的人不必再点。
GRAY_RELEASE_REQUIRED_CONFIRMS = 3

def get_required_confirm_count() -> int:
    """实际需要的票数。白名单人数少于阈值时按人数算，否则永远凑不齐。"""
    return min(GRAY_RELEASE_REQUIRED_CONFIRMS, len(GRAY_RELEASE_PHONES))

def init_gray_release_table():
    """gray_release 只记录「已确认全量」的版本，没有记录即表示该版本仍在灰度中。"""
    with get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gray_release (
                version_code INTEGER PRIMARY KEY,
                version_name TEXT DEFAULT '',
                promoted_by TEXT DEFAULT '',
                promoted_phone TEXT DEFAULT '',
                promoted_at TEXT
            )
        """)
        # 每位管理员对某个版本的确认各记一行，凑齐 GRAY_RELEASE_REQUIRED_CONFIRMS 票才写 gray_release
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gray_release_confirm (
                version_code INTEGER NOT NULL,
                telephone TEXT NOT NULL,
                version_name TEXT DEFAULT '',
                unionid TEXT DEFAULT '',
                confirmed_at TEXT,
                PRIMARY KEY (version_code, telephone)
            )
        """)
    sync_confirmed_releases()

def get_user_telephone(unionid: str) -> str:
    if not unionid:
        return ""
    with get_cursor() as cursor:
        cursor.execute("SELECT telephone FROM user_info WHERE unionid=?", (unionid,))
        row = cursor.fetchone()
    return (row["telephone"] or "").strip() if row else ""

def is_gray_phone(telephone: str) -> bool:
    return bool(telephone) and telephone.strip() in GRAY_RELEASE_PHONES

def is_version_released(version_code: int) -> bool:
    with get_cursor() as cursor:
        cursor.execute("SELECT version_code FROM gray_release WHERE version_code=?", (version_code,))
        return cursor.fetchone() is not None

def get_max_released_version() -> int:
    with get_cursor() as cursor:
        cursor.execute("SELECT MAX(version_code) AS max_version FROM gray_release")
        row = cursor.fetchone()
    return int(row["max_version"]) if row and row["max_version"] is not None else 0

def record_release_confirm(version_code: int, version_name: str, unionid: str, telephone: str):
    """登记一位管理员对某个版本的确认，重复确认幂等。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO gray_release_confirm (version_code, telephone, version_name, unionid, confirmed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(version_code, telephone) DO UPDATE SET
                version_name = excluded.version_name,
                unionid = excluded.unionid,
                confirmed_at = excluded.confirmed_at
        """, (version_code, (telephone or "").strip(), version_name or "", unionid or "", now))

def get_release_confirm_phones(version_code: int) -> list:
    """某版本已确认、且当前仍在白名单里的手机号。白名单调整后，已离任管理员的确认不再算数。"""
    with get_cursor() as cursor:
        cursor.execute("SELECT telephone FROM gray_release_confirm WHERE version_code=?",
                       (version_code,))
        rows = cursor.fetchall()
    confirmed = {(row["telephone"] or "").strip() for row in rows}
    return [phone for phone in GRAY_RELEASE_PHONES if phone in confirmed]

def is_release_fully_confirmed(version_code: int) -> bool:
    """够票即视为通过验收，不必等白名单里剩下的人。"""
    return len(get_release_confirm_phones(version_code)) >= get_required_confirm_count()

def sync_confirmed_releases():
    """把已经够票、却还没写进 gray_release 的版本补记为已全量。

    票数要求是在 promote 的那一刻判定的，阈值从「全员」放宽到 3 票之后，
    历史上卡在 3/4 的版本不会自己放开，靠这里在服务启动时补齐，
    免得还要请管理员回去重新点一次确认。
    """
    required = get_required_confirm_count()
    if required <= 0 or not GRAY_RELEASE_PHONES:
        return
    placeholders = ",".join("?" * len(GRAY_RELEASE_PHONES))
    with get_cursor() as cursor:
        cursor.execute(f"""
            SELECT version_code, COUNT(DISTINCT TRIM(telephone)) AS votes
            FROM gray_release_confirm
            WHERE TRIM(telephone) IN ({placeholders})
              AND version_code NOT IN (SELECT version_code FROM gray_release)
            GROUP BY version_code
            HAVING votes >= ?
        """, (*GRAY_RELEASE_PHONES, required))
        pending = [int(row["version_code"]) for row in cursor.fetchall()]
    for version_code in pending:
        # 版本名和确认人取最后一次确认的那条，便于回溯是谁把票凑齐的
        with get_cursor() as cursor:
            cursor.execute("""
                SELECT version_name, unionid, telephone FROM gray_release_confirm
                WHERE version_code=? ORDER BY confirmed_at DESC LIMIT 1
            """, (version_code,))
            last = cursor.fetchone()
        promote_release(version_code,
                        last["version_name"] if last else "",
                        last["unionid"] if last else "",
                        last["telephone"] if last else "")
        print(f"sync_confirmed_releases: version_code={version_code} promoted (confirms >= {required})")

def promote_release(version_code: int, version_name: str, unionid: str, telephone: str):
    """把某个版本标记为已全量放开，重复确认视为幂等。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO gray_release (version_code, version_name, promoted_by, promoted_phone, promoted_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(version_code) DO UPDATE SET
                version_name = excluded.version_name,
                promoted_by = excluded.promoted_by,
                promoted_phone = excluded.promoted_phone,
                promoted_at = excluded.promoted_at
        """, (version_code, version_name or "", unionid or "", telephone or "", now))

def get_all_released_versions():
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM gray_release ORDER BY version_code DESC LIMIT 200")
        return _rows_to_list(cursor.fetchall())

def revoke_release(version_code: int):
    """回退：把版本重新打回灰度状态，之前的确认票一并作废，需要重新凑够票。"""
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM gray_release WHERE version_code=?", (version_code,))
        cursor.execute("DELETE FROM gray_release_confirm WHERE version_code=?", (version_code,))

def enrich_phone_model(phone_model: str, engineering_model: str = "", mappings: dict = None) -> str:
    """根据 phone_model 或 engineering_model 查找对应的营销型号，没找到返回 None"""
    if not phone_model and not engineering_model:
        return None
    if mappings is None:
        all_mappings = get_all_phone_model_mappings()
        mappings = {m["engineering_model"]: m["marketing_model"] for m in all_mappings}
    # 优先匹配 phone_model
    result = mappings.get(phone_model, None)
    if result:
        return result
    # 再匹配 engineering_model
    if engineering_model:
        result = mappings.get(engineering_model, None)
    return result

def get_phone_model_stats():
    """按手机型号统计用量（含营销型号映射），按打开次数降序"""
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT
                COALESCE(NULLIF(phone_model, ''), '未知') as phone_model,
                COALESCE(NULLIF(engineering_model, ''), '') as engineering_model,
                COUNT(DISTINCT device_id) as devices,
                COALESCE(SUM(open_count), 0) as opens,
                COALESCE(SUM(duration_ms), 0) as duration_ms,
                COALESCE(SUM(play_duration_ms), 0) as play_duration_ms
            FROM app_usage
            GROUP BY phone_model, engineering_model
            ORDER BY opens DESC
        """)
        rows = _rows_to_list(cursor.fetchall())
    return enrich_list_with_marketing_model(rows, "phone_model")

def enrich_list_with_marketing_model(items: list, phone_model_key: str = "phone_model", engineering_model_key: str = "engineering_model"):
    """为列表中的每个 item 添加 marketing_model 字段"""
    all_mappings = get_all_phone_model_mappings()
    mappings = {m["engineering_model"]: m["marketing_model"] for m in all_mappings}
    for item in items:
        raw_model = item.get(phone_model_key, "")
        raw_eng_model = item.get(engineering_model_key, "")
        marketing = enrich_phone_model(raw_model, raw_eng_model, mappings)
        item["marketing_model"] = marketing or ""
    return items

def get_app_usage_summary():
    with get_cursor() as cursor:
        # 总设备数
        cursor.execute("SELECT COUNT(DISTINCT device_id) FROM app_usage")
        total_devices = cursor.fetchone()[0]

        # 总打开次数
        cursor.execute("SELECT COALESCE(SUM(open_count), 0) FROM app_usage")
        total_opens = cursor.fetchone()[0]

        # 总使用时长（前台停留）与总播放时长（含后台/锁屏收听）
        cursor.execute("SELECT COALESCE(SUM(duration_ms), 0), COALESCE(SUM(play_duration_ms), 0) FROM app_usage")
        total_row = cursor.fetchone()
        total_duration = total_row[0]
        total_play_duration = total_row[1]

        # 总使用天数（有记录的日期数）
        cursor.execute("SELECT COUNT(DISTINCT date) FROM app_usage")
        total_days = cursor.fetchone()[0]

        # 今日统计
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("SELECT COUNT(DISTINCT device_id), COALESCE(SUM(open_count), 0), COALESCE(SUM(duration_ms), 0), COALESCE(SUM(play_duration_ms), 0) FROM app_usage WHERE date=?", (today,))
        today_row = cursor.fetchone()
        today_devices = today_row[0]
        today_opens = today_row[1]
        today_duration = today_row[2]
        today_play_duration = today_row[3]

        # 最近30天每日统计
        cursor.execute("""
            SELECT date, COUNT(DISTINCT device_id) as devices, SUM(open_count) as opens,
                   SUM(duration_ms) as duration, SUM(play_duration_ms) as play_duration
            FROM app_usage
            WHERE date >= date('now', '-30 days')
            GROUP BY date
            ORDER BY date ASC
        """)
        daily_stats = _rows_to_list(cursor.fetchall())

        # 按来源统计（累计）
        cursor.execute("""
            SELECT COALESCE(NULLIF(source, ''), '未知') as source,
                   COUNT(DISTINCT device_id) as devices,
                   COALESCE(SUM(open_count), 0) as opens,
                   COALESCE(SUM(duration_ms), 0) as duration_ms,
                   COALESCE(SUM(play_duration_ms), 0) as play_duration_ms
            FROM app_usage
            GROUP BY source
            ORDER BY opens DESC
        """)
        source_stats = _rows_to_list(cursor.fetchall())

        # 按来源统计（今日）
        cursor.execute("""
            SELECT COALESCE(NULLIF(source, ''), '未知') as source,
                   COUNT(DISTINCT device_id) as devices,
                   COALESCE(SUM(open_count), 0) as opens,
                   COALESCE(SUM(duration_ms), 0) as duration_ms,
                   COALESCE(SUM(play_duration_ms), 0) as play_duration_ms
            FROM app_usage
            WHERE date=?
            GROUP BY source
            ORDER BY opens DESC
        """, (today,))
        today_source_stats = _rows_to_list(cursor.fetchall())

        return {
            "total_devices": total_devices,
            "total_opens": total_opens,
            "total_duration_ms": total_duration,
            "total_play_duration_ms": total_play_duration,
            "total_days": total_days,
            "today_devices": today_devices,
            "today_opens": today_opens,
            "today_duration_ms": today_duration,
            "today_play_duration_ms": today_play_duration,
            "daily_stats": daily_stats,
            "source_stats": source_stats,
            "today_source_stats": today_source_stats
        }
