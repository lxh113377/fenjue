#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_r219_declaration.py — R216-03 收尾（方案 a 机械化）声明行机器兜底单测。

覆盖：
1. 三行声明格式严格匹配 lessons_pread_audit 正则（RE_PREAD/RE_SKILL/RE_MEM）
2. 当日日志不存在 → 跳过返回 False，且不创建日志文件（零副作用）
3. 尾无换行防粘连：append 前自动补 \n
4. 空 skills/mem_files → 只写 lessons 行，不产空声明
5. --dry-run 主流程零写入（main 分支在 append 前返回，函数级验证格式函数纯度）
"""
from __future__ import annotations

import importlib
import os

import pytest

rec = importlib.import_module("record_lessons_usage")
aud = importlib.import_module("lessons_pread_audit")


@pytest.fixture()
def log_dir(tmp_path, monkeypatch):
    """把 record 的 PROJECT_DIR 指向 tmp_path，隔离真实日志。"""
    monkeypatch.setattr(rec, "PROJECT_DIR", str(tmp_path))
    return tmp_path


def _make_log(log_dir, day="2026-09-08", tail="\n"):
    p = os.path.join(log_dir, ".workbuddy", "memory", day + ".md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# 日志" + tail)
    return p


def test_three_lines_match_audit_regex(log_dir):
    p = _make_log(log_dir)
    ok = rec.append_declaration(
        "2026-09-08",
        ["lessons.part41.md#条目A", "lessons-p1-decision.md#条目B"],
        ["A-memory-start", "A-get-memory"],
        ["STATUS.part1.md", "memory_index.md"],
    )
    assert ok is True
    text = open(p, encoding="utf-8").read()
    m1 = aud.RE_PREAD.search(text)
    m2 = aud.RE_SKILL.search(text)
    m3 = aud.RE_MEM.search(text)
    assert m1 and m1.group(1) == "2"
    assert m2 and m2.group(1) == "2" and "A-get-memory" in m2.group(2)
    assert m3 and m3.group(1) == "2" and "STATUS.part1.md" in m3.group(2)


def test_missing_log_skips_without_creation(log_dir):
    ok = rec.append_declaration("2026-09-08", ["lessons.part41.md#X"], [], [])
    assert ok is False
    p = os.path.join(log_dir, ".workbuddy", "memory", "2026-09-08.md")
    assert not os.path.exists(p)  # 不越界代开日志


def test_tail_without_newline_no_glue(log_dir):
    p = _make_log(log_dir, tail="")  # 尾无换行
    rec.append_declaration("2026-09-08", ["lessons.part41.md#X"], [], [])
    text = open(p, encoding="utf-8").read()
    assert "# 日志\nlessons预读: 命中1条" in text  # 无粘连
    m = aud.RE_PREAD.search(text)
    assert m and m.group(1) == "1"


def test_lessons_only_no_empty_lines(log_dir):
    p = _make_log(log_dir)
    rec.append_declaration("2026-09-08", ["lessons.part41.md#X"], "", "")
    text = open(p, encoding="utf-8").read()
    assert "skill加载" not in text and "记忆加载" not in text
    assert aud.RE_PREAD.search(text)


def test_dry_run_writes_nothing(log_dir, capsys, monkeypatch):
    """main 层 dry-run：jsonl 与声明行均零写入。"""
    import sys

    _make_log(log_dir)
    usage = os.path.join(rec.GLOBAL_MEMORY, "meta", "lessons_usage.jsonl")
    before = os.path.getsize(usage) if os.path.exists(usage) else 0
    monkeypatch.setattr(sys, "argv", [
        "record_lessons_usage.py", "--session", "t", "--query", "q",
        "--loaded", "lessons.part41.md#X", "--skills", "A", "--dry-run",
    ])
    assert rec.main() == 0
    after = os.path.getsize(usage) if os.path.exists(usage) else 0
    assert before == after
    p = os.path.join(log_dir, ".workbuddy", "memory", "2026-09-08.md")
    assert "lessons预读" not in open(p, encoding="utf-8").read()
