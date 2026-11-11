"""意见反馈日志上传的契约测试。

使用临时数据库和临时附件目录，不读取生产库，也不访问生产服务。
multipart 字段沿用本服务现有的 file + type；成功响应沿用 data.url / data.size。
"""
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from request import FeedbackLogUrlError, normalize_feedback_log_urls  # noqa: E402

MAX_LOG_SIZE = 6 * 1024 * 1024
UPLOAD = "/htz-api-pyservice/api/v1/feedback/upload"
ADD = "/htz-api-pyservice/api/v1/feedback/add"
LIST = "/htz-api-pyservice/api/v1/feedback/list"


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("feedback-api")
    upload = tmp / "feedback"
    upload.mkdir()
    old_cwd = os.getcwd()
    os.environ["HTZ_ADMIN_TOKEN"] = "isolate-token"
    os.environ["HTZ_ADMIN_PASSWORD"] = "isolate-pass"
    os.environ["HTZ_FEEDBACK_UPLOAD_DIR"] = str(upload)
    os.chdir(tmp)
    spec = importlib.util.spec_from_file_location("htz_api_server_feedback_test", ROOT / "htz-api-server.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    from fastapi.testclient import TestClient
    client = TestClient(module.app)
    try:
        yield {"client": client, "upload": upload, "module": module, "tmp": tmp}
    finally:
        os.chdir(old_cwd)


def _upload(client, filename, body, kind="log", content_type="text/plain"):
    return client.post(UPLOAD, data={"type": kind}, files={"file": (filename, body, content_type)})


def test_normalize_accepts_array_string_list_and_single_url():
    one = "/static/feedback/1700000000_abcd1234.log"
    assert json.loads(normalize_feedback_log_urls(json.dumps([one]))) == [one]
    assert json.loads(normalize_feedback_log_urls([one])) == [one]
    assert json.loads(normalize_feedback_log_urls(one)) == [one]
    assert normalize_feedback_log_urls(None) == ""
    assert normalize_feedback_log_urls("") == ""
    assert normalize_feedback_log_urls([]) == ""


@pytest.mark.parametrize("value", [
    "/static/feedback/../../etc/passwd.log",
    "/static/feedback/..%2fpasswd.log",
    "/etc/passwd.log",
    "https://evil.example/a.log",
    ["/static/feedback/a.log", "/static/feedback/b.log", "/static/feedback/c.log", "/static/feedback/d.log"],
    {"url": "/static/feedback/a.log"},
    "not-json",
])
def test_normalize_rejects_unsafe_or_too_many(value):
    with pytest.raises(FeedbackLogUrlError):
        normalize_feedback_log_urls(value)


def test_upload_log_with_android_style_multipart(api):
    body = b"2026-11-10 app log\nline2 <>&\n"
    response = _upload(api["client"], "2026-11-10.log", body, content_type="application/octet-stream")
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == "0"
    assert payload["data"]["size"] == len(body)
    url = payload["data"]["url"]
    assert url.startswith("/static/feedback/")
    assert url.endswith(".log")
    stored = api["upload"] / os.path.basename(url)
    assert stored.read_bytes() == body
    assert stored.parent.resolve() == api["upload"].resolve()


def test_upload_rejects_extension_type_and_size(api):
    client = api["client"]
    cases = [
        ("2026-11-10.jpg", b"img", "log", 400),
        ("2026-11-10.txt", b"txt", "log", 400),
        ("2026-11-10.log.exe", b"exe", "log", 400),
        ("2026-11-10.log", b"log", "image", 200),
        ("2026-11-10.log", b"log", "video", 200),
        ("../../etc/passwd.log.jpg", b"x", "log", 400),
    ]
    for filename, body, kind, status in cases:
        response = _upload(client, filename, body, kind)
        payload = response.json()
        assert payload["code"] != "0"
        assert payload["data"] is None
        if kind == "log":
            assert response.status_code == status
            assert "unsupported file ext" in payload["msg"]
        else:
            # 图片/视频失败仍是原来的 HTTP 200 + 业务 code，避免改旧客户端。
            assert response.status_code == 200
            assert payload["code"] == "400"
    too_big = _upload(client, "2026-11-10.log", b"a" * (MAX_LOG_SIZE + 1))
    assert too_big.status_code == 413
    assert too_big.json()["code"] == "413"
    assert too_big.json()["data"] is None
    assert list(api["upload"].glob("*")) == [] or all(
        path.stat().st_size <= MAX_LOG_SIZE for path in api["upload"].glob("*.log")
    )
    exact = _upload(client, "2026-11-09.log", b"b" * MAX_LOG_SIZE)
    assert exact.status_code == 200
    assert exact.json()["code"] == "0"
    assert exact.json()["data"]["size"] == MAX_LOG_SIZE
    image = _upload(client, "shot.png", b"\x89PNG\r\n", "image")
    assert image.status_code == 200
    assert image.json()["code"] == "0"
    assert image.json()["data"]["url"].endswith(".png")


def test_traversal_filename_stays_inside_upload_dir(api):
    response = _upload(api["client"], "../../2026-11-08.log", b"inside\n")
    assert response.status_code == 200
    url = response.json()["data"]["url"]
    stored = (api["upload"] / os.path.basename(url)).resolve()
    assert stored.parent == api["upload"].resolve()
    assert not (api["tmp"] / "2026-11-08.log").exists()


def test_add_persists_log_urls_and_old_request_still_works(api):
    client = api["client"]
    first = _upload(client, "2026-11-10.log", b"day-1\n").json()["data"]["url"]
    second = _upload(client, "2026-11-09.log", b"day-2\n").json()["data"]["url"]
    created = client.post(ADD, json={
        "content": "隔离反馈-带日志",
        "nickname": "隔离测试",
        "log_urls": [first, second],
        "image_urls": "[]",
        "video_url": "",
    })
    assert created.status_code == 200
    assert created.json()["code"] == "0"

    listed = client.get(LIST, headers={"Authorization": "Bearer isolate-token"})
    assert listed.status_code == 200
    rows = [row for row in listed.json()["data"] if row["content"] == "隔离反馈-带日志"]
    assert len(rows) == 1
    assert json.loads(rows[0]["log_urls"]) == [first, second]

    as_string = client.post(ADD, json={
        "content": "隔离反馈-字符串log_urls",
        "log_urls": json.dumps([first]),
    })
    assert as_string.status_code == 200
    assert as_string.json()["code"] == "0"
    string_row = [row for row in client.get(LIST, headers={"Authorization": "Bearer isolate-token"}).json()["data"]
                  if row["content"] == "隔离反馈-字符串log_urls"][0]
    assert json.loads(string_row["log_urls"]) == [first]

    old = client.post(ADD, json={"content": "隔离反馈-旧客户端", "nickname": "旧"})
    assert old.status_code == 200
    assert old.json()["code"] == "0"
    old_row = [row for row in client.get(LIST, headers={"Authorization": "Bearer isolate-token"}).json()["data"]
               if row["content"] == "隔离反馈-旧客户端"][0]
    assert old_row["log_urls"] in ("", None)

    missing = client.post(ADD, json={"content": "不应保存", "log_urls": ["/static/feedback/missing.log"]})
    assert missing.status_code == 400
    assert missing.json()["code"] == "400"
    assert missing.json()["data"] is None
    assert all(row["content"] != "不应保存" for row in
               client.get(LIST, headers={"Authorization": "Bearer isolate-token"}).json()["data"])

    escaped = client.post(ADD, json={
        "content": "路径穿越不应保存",
        "log_urls": ["/static/feedback/../../htz.db"],
    })
    assert escaped.status_code == 400
    assert escaped.json()["code"] == "400"


def test_feedback_list_and_admin_can_see_log_links(api):
    page = api["client"].get("/admin")
    assert page.status_code == 200
    text = page.text
    assert "function parseLogUrls" in text
    assert "日志附件" in text
    assert "feedbackLogLinksHtml" in text
    assert "download=" in text


def test_old_feedback_table_gains_log_urls(tmp_path):
    script = r"""
import os, sqlite3, sys
os.chdir(sys.argv[1])
sys.path.insert(0, sys.argv[2])
conn = sqlite3.connect("htz.db")
conn.execute('''
CREATE TABLE feedback (
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
''')
conn.execute("INSERT INTO feedback (content, created_at, updated_at) VALUES ('旧行', '2026-11-10 00:00:00', '2026-11-10 00:00:00')")
conn.commit()
conn.close()
import db
db.init_feedback_table()
conn = sqlite3.connect("htz.db")
cols = [row[1] for row in conn.execute("PRAGMA table_info(feedback)")]
assert "log_urls" in cols
old = conn.execute("SELECT log_urls FROM feedback WHERE content='旧行'").fetchone()
assert old[0] in ("", None)
from request import FeedbackItem
db.save_feedback(FeedbackItem(content="迁移后", log_urls='["/static/feedback/1_aaaaaaaa.log"]'))
saved = conn.execute("SELECT log_urls FROM feedback WHERE content='迁移后'").fetchone()
assert saved[0] == '["/static/feedback/1_aaaaaaaa.log"]'
print("ok")
"""
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(ROOT)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
