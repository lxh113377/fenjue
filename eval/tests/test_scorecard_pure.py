#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scorecard 评分纯函数参数化 + unavailable 传播（R193 阶段2）。"""

import os
import sys

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import scorecard  # noqa: E402


@pytest.mark.parametrize("overall,expected", [
    (150, "优秀"),
    (145, "优秀"),
    (140, "良好"),
    (135, "良好"),
    (130, "合格"),
    (120, "合格"),
    (110, "不达标"),
])
def test_band_of(overall, expected):
    assert scorecard.band_of(overall) == expected


def test_compute_verdict_pass():
    ok, blockers = scorecard.compute_verdict(200, True, True, True, 0, 0)
    assert ok and blockers == []


@pytest.mark.parametrize("kwargs,keyword", [
    ({"overall": 100}, "总分"),
    ({"line_pass": False}, "主线"),
    ({"dim_pass": False}, "单维"),
    ({"testset_ok": False}, "测试集"),
    ({"confirmed_n": 1}, "确认缺陷"),
    ({"overdue_pending_n": 1}, "超期 pending"),
    ({"escape_overdue_n": 1}, "逃生门"),
])
def test_compute_verdict_blockers(kwargs, keyword):
    args = {"overall": 200, "line_pass": True, "dim_pass": True,
            "testset_ok": True, "confirmed_n": 0, "overdue_pending_n": 0}
    args.update(kwargs)
    ok, blockers = scorecard.compute_verdict(**args)
    assert not ok
    assert any(keyword in b for b in blockers)


def test_compute_verdict_unavailable_propagation():
    """DATA UNAVAILABLE 维度必须显式阻断 PASS（禁止静默 0 分）。"""
    ok, blockers = scorecard.compute_verdict(
        200, True, True, True, 0, 0, unavailable_dims=["记忆", "路由"])
    assert not ok
    assert any("DATA UNAVAILABLE" in b and "记忆" in b for b in blockers)


def test_disk_skill_count_ignores_nested_skil_md(tmp_path):
    """R198.6 防回归：accuracy 磁盘计数必须只算顶层目录，嵌套 SKILL.md 不算独立 skill。

    构造: 顶层 3 个真 skill（含 cloudbase__skillhub 缩影，其 references/ 内 3 个嵌套 SKILL.md），
    断言 listdir 口径只计 3 个顶层，嵌套不计（os.walk 递归会误计为 6）。
    """
    gs = tmp_path / "gs"
    gs.mkdir()
    # 顶层真 skill
    for name in ("alpha", "beta"):
        d = gs / name
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    # cloudbase__skillhub 缩影：顶层有 SKILL.md + references/ 内嵌套
    hub = gs / "cloudbase__skillhub"
    hub.mkdir()
    (hub / "SKILL.md").write_text("---\nname: cloudbase__skillhub\n---\n", encoding="utf-8")
    refs = hub / "references"
    refs.mkdir()
    for i in range(3):
        sub = refs / f"ref-{i}"
        sub.mkdir()
        (sub / "SKILL.md").write_text(f"---\nname: ref-{i}\n---\n", encoding="utf-8")

    # 与 scorecard.py accuracy 段 L250-257 同款 listdir 扫描逻辑
    sys_dirs = {"_temp", "_trash", "_bak", ".git", ".hermes"}
    names = set()
    for e in os.listdir(gs):
        p = os.path.join(gs, e)
        if os.path.isdir(p) and os.path.exists(os.path.join(p, "SKILL.md")) and e not in sys_dirs:
            names.add(e)
    # 3 个顶层目录计数，references 内嵌套 3 个不计数
    assert len(names) == 3
    assert "ref-0" not in names and "ref-1" not in names and "ref-2" not in names

