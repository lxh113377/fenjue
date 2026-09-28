#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_path_index_due 回归测试（R199 机器强制化，2026-08-17）。"""

import datetime
import json
import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import check_path_index_due as due  # noqa: E402


def _mk(tmp_path, text):
    p = tmp_path / "path_index.md"
    p.write_text(text, encoding="utf-8")
    return p


STATUS_OK = """# path_index.md

> **季度实测校验状态（R199）**：上次 = 2026-01-01 | 下次 = 2999-12-31 | 逾期处理见 Step 4m
"""


def test_not_overdue(tmp_path) -> None:
    p = _mk(tmp_path, STATUS_OK)
    r = due.check_due(p, today=datetime.date(2026, 4, 1))  # = 下次当天，不算逾期
    assert r["exit_code"] == 0 and r["status"] == "ok"


def test_overdue(tmp_path) -> None:
    p = _mk(tmp_path, "# path_index.md\n\n> **季度实测校验状态**：上次 = 2026-01-01 | 下次 = 2026-04-01\n")
    r = due.check_due(p, today=datetime.date(2026, 4, 2))  # > 下次
    assert r["exit_code"] == 1 and r["status"] == "overdue"
    assert r["days"] == 1


def test_status_field_missing(tmp_path) -> None:
    p = _mk(tmp_path, "# path_index.md\n\n无状态字段\n")
    r = due.check_due(p, today=datetime.date(2026, 4, 2))
    assert r["exit_code"] == 2 and r["status"] == "misconfig"
    assert "季度实测校验状态" in r["error"]


def test_bad_date_format(tmp_path) -> None:
    p = _mk(tmp_path, "# path_index.md\n\n> **季度实测校验状态**：上次 = 2026-01-01 | 无下次\n")
    r = due.check_due(p, today=datetime.date(2026, 4, 2))
    assert r["exit_code"] == 2 and "下次" in r["error"]


def test_file_missing(tmp_path) -> None:
    r = due.check_due(tmp_path / "nope.md", today=datetime.date(2026, 4, 2))
    assert r["exit_code"] == 2 and "不存在" in r["error"]


def test_main_json(tmp_path, capsys) -> None:
    p = _mk(tmp_path, STATUS_OK)
    assert due.main(["--path", str(p), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "fenjue-check-path-index-due-v1"
    assert out["status"] == "ok"
