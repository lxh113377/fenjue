#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feedback API 单测（R194）：写入/字段校验/重复 id/统计/关闭 + HTTP 冒烟。"""


import pytest

from feedback.app import (
    append_entry,
    build_app,
    close_entry,
    load_entries,
    summarize,
    validate_entry,
)


def base_entry(**overrides):
    entry = {
        "task": "执行焚诀闭环补全",
        "wrong": "路由把规划消息指到了 A-prompt-better",
        "expected": "应指向 A-ask-questions",
        "category": "工具调用",
        "severity": "高",
        "recovered": False,
        "source": "web",
        "status": "open",
    }
    entry.update(overrides)
    return entry


def test_validate_ok():
    assert validate_entry(base_entry()) == []


def test_validate_rejects_missing_and_bad_enums():
    errors = validate_entry({"task": "", "category": "不存在", "severity": "致命级"})
    assert any("task" in e for e in errors)
    assert any("category" in e for e in errors)
    assert any("severity" in e for e in errors)


def test_append_load_roundtrip(tmp_path):
    path = str(tmp_path / "feedback.jsonl")
    fid = append_entry(base_entry(), path)
    rows = load_entries(path)
    assert len(rows) == 1
    assert rows[0]["id"] == fid
    assert rows[0]["status"] == "open"
    assert rows[0]["ts"]


def test_duplicate_id_rejected(tmp_path):
    path = str(tmp_path / "feedback.jsonl")
    fid = append_entry(base_entry(id="abc123"), path)
    assert fid == "abc123"
    with pytest.raises(ValueError):
        append_entry(base_entry(id="abc123"), path)


def test_summary_counts(tmp_path):
    path = str(tmp_path / "feedback.jsonl")
    append_entry(base_entry(id="a1", severity="致命"), path)
    append_entry(base_entry(id="a2", severity="中"), path)
    close_entry("a1", path)
    s = summarize(path)
    assert s["total"] == 2
    assert s["open"] == 1
    assert s["closed"] == 1
    assert s["by_severity"]["致命"] == 1
    assert s["open_items"][0]["id"] == "a2"


def test_close_entry(tmp_path):
    path = str(tmp_path / "feedback.jsonl")
    fid = append_entry(base_entry(), path)
    assert close_entry(fid, path) is True
    assert close_entry(fid, path) is False  # 已 closed
    assert close_entry("no-such", path) is False
    assert load_entries(path)[0]["status"] == "closed"


def test_http_get_form_and_post(tmp_path):
    app = build_app(str(tmp_path / "feedback.jsonl"))
    client = app.test_client()
    assert client.get("/").status_code == 200
    resp = client.post("/api/feedback", json=base_entry(id="web1"))
    assert resp.status_code == 201
    assert resp.get_json()["id"] == "web1"
    rows = load_entries(str(tmp_path / "feedback.jsonl"))
    assert len(rows) == 1


def test_http_duplicate_id_400(tmp_path):
    app = build_app(str(tmp_path / "feedback.jsonl"))
    client = app.test_client()
    assert client.post("/api/feedback", json=base_entry(id="dup1")).status_code == 201
    resp = client.post("/api/feedback", json=base_entry(id="dup1"))
    assert resp.status_code == 400
    assert "id 重复" in resp.get_json()["error"]


def test_http_invalid_400(tmp_path):
    app = build_app(str(tmp_path / "feedback.jsonl"))
    resp = app.test_client().post("/api/feedback", json={"task": "", "category": "x"})
    assert resp.status_code == 400
