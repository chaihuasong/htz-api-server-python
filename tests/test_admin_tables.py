"""管理后台表格列顺序和 xlsx 导出的读回测试。

使用仓库里的 static/admin-tables.js 生成工作簿，再用 openpyxl 打开比对。
不连接生产库，也不写入业务数据。
"""
import base64
import io
import json
import subprocess
from datetime import datetime
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "admin-tables.js"


def node_call(expr):
    script = (
        "const api = require(%s);\n"
        "const value = (%s);\n"
        "if (value instanceof Uint8Array) {\n"
        "  process.stdout.write(Buffer.from(value).toString('base64'));\n"
        "} else {\n"
        "  process.stdout.write(JSON.stringify(value));\n"
        "}\n"
    ) % (json.dumps(str(JS)), expr)
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True)
    return result.stdout


def resolve(default_keys, saved_keys):
    expr = "api.resolveColumnOrder(%s, %s)" % (json.dumps(default_keys), json.dumps(saved_keys))
    return json.loads(node_call(expr))


def build_workbook(headers, types, rows, scope_rows):
    payload = {
        "headers": headers,
        "types": types,
        "rows": rows,
        "scopeRows": scope_rows,
    }
    expr = "api.buildXlsxBytes(%s)" % json.dumps(payload, ensure_ascii=False)
    raw = base64.b64decode(node_call(expr))
    assert raw[:2] == b"PK"
    workbook = openpyxl.load_workbook(io.BytesIO(raw))
    return workbook


def test_column_order_keeps_saved_permutation_and_drops_unknown():
    assert resolve(["a", "b", "c"], ["c", "a", "b"]) == ["c", "a", "b"]
    # gone 被丢掉，重复的 a 只留一次；缺失的 b 按默认位置插回 c 前面，c 仍在 a 前面。
    assert resolve(["a", "b", "c"], ["c", "gone", "a", "a"]) == ["b", "c", "a"]


def test_column_order_inserts_new_columns_by_default_position():
    # b 是后来新增的列，应插在默认顺序里它和已保存列的相对位置。
    assert resolve(["a", "b", "c"], ["c", "a"]) == ["b", "c", "a"]
    assert resolve(["a", "b", "c", "d"], []) == ["a", "b", "c", "d"]
    assert resolve(["a", "b"], None) == ["a", "b"]


def test_storage_keys_are_independent_per_table():
    expr = "[api.storageKey('users'), api.storageKey('usage')]"
    users_key, usage_key = json.loads(node_call(expr))
    assert users_key != usage_key
    assert users_key.endswith("users")
    assert usage_key.endswith("usage")


def test_xlsx_reads_back_headers_order_types_and_duplicate_rows():
    workbook = build_workbook(
        ["昵称", "数量", "日期", "占比", "备注"],
        ["text", "number", "date", "percent", "text"],
        [
            ["张三", 0, "2026-11-10", 12.5, "中文 <tag> & \"引号\""],
            ["张三", 0, "2026-11-10", 12.5, "中文 <tag> & \"引号\""],
            ["", None, "", "", "=1+1\n第二行"],
            ["李四", -3, "2026-01-02 03:04:05", 0, "  空格  "],
        ],
        [
            ["表格", "隔离测试", "text"],
            ["导出行数", 4, "number"],
            ["页面说明", "当前筛选条件下的全部行，不是只导出当前屏幕", "text"],
        ],
    )
    assert workbook.sheetnames == ["数据", "导出说明"]
    sheet = workbook["数据"]
    headers = [cell.value for cell in sheet[1]]
    assert headers == ["昵称", "数量", "日期", "占比", "备注"]
    assert sheet.max_row == 5

    first = [cell.value for cell in sheet[2]]
    second = [cell.value for cell in sheet[3]]
    assert first == second
    assert first[0] == "张三"
    assert first[1] == 0
    assert first[2] == datetime(2026, 11, 10)
    assert abs(first[3] - 0.125) < 1e-9
    assert first[4] == '中文 <tag> & "引号"'

    blank = [cell.value for cell in sheet[4]]
    assert blank[0] is None
    assert blank[1] is None
    assert blank[2] is None
    assert blank[3] is None
    assert blank[4] == "=1+1\n第二行"
    assert sheet["E4"].data_type == "inlineStr" or isinstance(sheet["E4"].value, str)

    spaced = [cell.value for cell in sheet[5]]
    assert spaced[0] == "李四"
    assert spaced[1] == -3
    assert spaced[2] == datetime(2026, 1, 2, 3, 4, 5)
    assert spaced[3] == 0
    assert spaced[4] == "  空格  "

    scope = workbook["导出说明"]
    scope_map = {row[0].value: row[1].value for row in scope.iter_rows(min_row=2)}
    assert scope_map["表格"] == "隔离测试"
    assert scope_map["导出行数"] == 4
    assert "不是只导出当前屏幕" in scope_map["页面说明"]


def test_empty_table_still_has_headers():
    workbook = build_workbook(
        ["ID", "内容"],
        ["number", "text"],
        [],
        [["导出行数", 0, "number"], ["页面说明", "当前筛选无数据", "text"]],
    )
    sheet = workbook["数据"]
    assert [cell.value for cell in sheet[1]] == ["ID", "内容"]
    assert sheet.max_row == 1
    scope = {row[0].value: row[1].value for row in workbook["导出说明"].iter_rows(min_row=2)}
    assert scope["导出行数"] == 0


def test_export_spec_follows_custom_order_and_skips_actions():
    columns = [
        {"key": "id", "label": "ID", "type": "number"},
        {"key": "name", "label": "名称", "type": "text"},
        {"key": "actions", "label": "操作", "type": "text", "export": False},
    ]
    rows = [
        {"id": 2, "name": "甲", "actions": "删除"},
        {"id": 2, "name": "甲", "actions": "删除"},
    ]
    script = """
    global.localStorage = { getItem(key) { return this._[key] || null; }, _: {
      'htz-admin-col-order:demo': JSON.stringify(['name', 'missing', 'id', 'actions'])
    } };
    const api = require(%s);
    const result = api.exportSpec({
      id: 'demo',
      title: '演示/表格',
      columns: %s,
      rows: %s,
      scope: () => ({ filterText: '关键词「甲」', sortText: 'ID 降序', partial: true, coverage: '接口最多 1000 条。导出的是已加载数据里的全部行，不是屏幕上的几行。' })
    });
    process.stdout.write(JSON.stringify({
      filename: result.filename,
      headers: result.headers,
      rowCount: result.rowCount,
      b64: Buffer.from(result.bytes).toString('base64')
    }));
    """ % (
        json.dumps(str(JS)),
        json.dumps(columns, ensure_ascii=False),
        json.dumps(rows, ensure_ascii=False),
    )
    payload = json.loads(subprocess.run(["node", "-e", script], check=True, capture_output=True).stdout)
    assert payload["headers"] == ["名称", "ID"]
    assert payload["rowCount"] == 2
    assert payload["filename"].endswith(".xlsx")
    assert "/" not in payload["filename"]
    workbook = openpyxl.load_workbook(io.BytesIO(base64.b64decode(payload["b64"])))
    headers = [cell.value for cell in workbook["数据"][1]]
    assert headers == ["名称", "ID"]
    assert workbook["数据"].max_row == 3
    assert [cell.value for cell in workbook["数据"][2]] == ["甲", 2]
    assert [cell.value for cell in workbook["数据"][3]] == ["甲", 2]
    scope = {row[0].value: row[1].value for row in workbook["导出说明"].iter_rows(min_row=2)}
    assert scope["导出行数"] == 2
    assert scope["是否只含已加载的部分数据"] == "是"
    assert "不是屏幕上的几行" in scope["页面说明"]
