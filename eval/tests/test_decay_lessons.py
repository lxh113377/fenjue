#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""decay_lessons 单元测试（R211-1）：衰减计算 / 数据容错 / dry-run 语义。"""
import datetime
import json
import os
import sys

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import decay_lessons as dl  # noqa: E402

TODAY = datetime.date.today()
OLD = (TODAY - datetime.timedelta(days=35)).isoformat()   # 35 天前 → 满 30 天窗口
RECENT = (TODAY - datetime.timedelta(days=5)).isoformat()  # 近期命中 → 不衰减


def _make_env(tmp_path, entries_md, usage_rows, bom=False, comment_header=False):
    lessons = tmp_path / "lessons"
    lessons.mkdir()
    body = "\n".join(entries_md)
    raw = body.encode("utf-8")
    (lessons / "lessons.test.md").write_bytes(raw)
    usage = tmp_path / "usage.jsonl"
    prefix = b"\xef\xbb\xbf" if bom else b""
    if comment_header:
        prefix += b"# schema_v=1 (test)\n"
    rows = b"".join((json.dumps(r, ensure_ascii=False) + "\n").encode("utf-8") for r in usage_rows)
    usage.write_bytes(prefix + rows)
    return lessons, usage


@pytest.fixture()
def env(tmp_path, monkeypatch):
    lessons = tmp_path / "lessons"
    lessons.mkdir()                     # decay 扫描 listdir 需要目录存在
    usage = tmp_path / "usage.jsonl"
    monkeypatch.setattr(dl, "LESSONS_DIR", str(lessons))
    monkeypatch.setattr(dl, "USAGE_PATH", str(usage))
    return lessons, usage


def _entry_md(title, conf, date):
    return (f"### [{date}] 🔴 {title}\n"
            f"trigger: t1 | t2 | bash\n"
            f"- **问题：** x\n"
            f"- **元：** 来源=t | 版本=v | 置信度={conf} | 日期={date} | 适用范围=bash\n")


def test_recent_hit_no_decay(env):
    lessons, usage = env
    (lessons / "lessons.test.md").write_text(
        _entry_md("近期条目", 0.5, RECENT), encoding="utf-8")
    usage.write_text(json.dumps(
        {"date": RECENT, "loaded": ["lessons.test.md#近期条目"], "used": [],
         "useful": "true"}), encoding="utf-8")
    rep = dl.decay_report(apply=False)
    assert rep["decayed"] == []
    assert rep["total"] == 1


def test_30d_idle_decays_one_step(env):
    lessons, usage = env
    (lessons / "lessons.test.md").write_text(
        _entry_md("陈旧条目", 0.5, OLD), encoding="utf-8")
    rep = dl.decay_report(apply=False)  # 无 usage 记录 → 以条目日期为基线
    assert len(rep["decayed"]) == 1
    d = rep["decayed"][0]
    assert d["old"] == 0.5 and d["new"] == 0.4 and d["steps"] == 1
    assert d["candidate"] is False      # 0.4 ≥ 0.3 非候选


def test_double_window_two_steps_candidate(env):
    older = (TODAY - datetime.timedelta(days=65)).isoformat()
    lessons, usage = env
    (lessons / "lessons.test.md").write_text(
        _entry_md("超期条目", 0.4, older), encoding="utf-8")
    rep = dl.decay_report(apply=False)
    d = rep["decayed"][0]
    assert d["steps"] == 2 and d["new"] == 0.2
    assert d["candidate"] is True       # 0.2 < 0.3 → 遗忘候选


def test_usage_comment_header_and_bom_tolerated(env):
    lessons, usage = env
    (lessons / "lessons.test.md").write_text(
        _entry_md("条目甲", 0.5, OLD), encoding="utf-8")
    raw = (b"\xef\xbb\xbf# schema_v=1 (test)\n" +
           json.dumps({"date": OLD, "loaded": ["lessons.test.md#条目甲"],
                       "used": [], "useful": "true"}).encode("utf-8") + b"\n")
    usage.write_bytes(raw)              # BOM + 注释头 + 数据 → 容错解析
    rep = dl.decay_report(apply=False)
    assert len(rep["decayed"]) == 1     # BOM/注释被跳过，数据生效


def test_dry_run_never_writes(env, tmp_path):
    lessons, usage = env
    f = lessons / "lessons.test.md"
    original = _entry_md("陈旧条目", 0.5, OLD)
    f.write_text(original, encoding="utf-8")
    dl.decay_report(apply=False)
    assert f.read_text(encoding="utf-8") == original  # dry-run 不写盘


def test_apply_writes_confidence_only(env):
    lessons, usage = env
    f = lessons / "lessons.test.md"
    f.write_text(_entry_md("陈旧条目", 0.5, OLD), encoding="utf-8")
    dl.decay_report(apply=True)
    new = f.read_text(encoding="utf-8")
    assert "置信度=0.4" in new and "置信度=0.5" not in new
    assert "### [" in new and "trigger:" in new  # 条目正文/结构不受影响
