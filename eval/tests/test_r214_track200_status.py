#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_r214_track200_status.py — R214-3 status_report track_200 口径回归

背景（R213）: STATUS 壳文档口径漂移 20 天未被发现——评分卡已切 track_200
（170/200）而壳文档仍写 track_150（120/150）、门禁 C1~C12 实为 13 项。
本轮将达标线与门禁编号改为动态取值，本文件防口径回退。

覆盖:
  1. PASS_LINE 随 SCORECARD_ACTIVE_TRACK 动态取（当前=track_200 -> 170/200）
  2. generate_status track_200 分支: 六线行/综合分/达标线渲染
  3. 门禁编号动态 C1~C13（非废弃字面量 C1~C12）
  4. gate all_pass 翻转 -> 头部判定切换; FAIL 计数正确
  5. unavailable_lines 有无 -> ⚠ 行出现/不出现
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import status_report as sr  # noqa: E402
from truth_constants import SCORECARD_ACTIVE_TRACK, SCORECARD_TRACK_200  # noqa: E402


def _gate(n_pass=13, n_fail=0):
    results = []
    for i in range(1, n_pass + n_fail + 1):
        results.append({"id": f"C{i}", "desc": f"门禁{i}",
                        "status": "PASS" if i <= n_pass else "FAIL",
                        "detail": "x"})
    return {"all_pass": n_fail == 0, "results": results}


def _track200(overall=150.1, unavailable=None):
    lines = [{"line": name, "total": t} for name, t in
             zip(("主线① 跨平台skill互通同步", "主线② 多agent统一记忆+路由",
                  "主线③ skill命中率优化", "主线④ lessons命中率度量",
                  "主线⑤ 注意力优化", "主线⑥ 前置使用率采样"),
                 (24.4, 24.6, 32.4, 23.3, 17.6, 27.8))]
    return {"schema": "fenjue-track200-v1", "total_line": 200,
            "verdict": "FAIL", "overall": overall, "ts": "2026-09-06T02:00:00",
            "lines": lines, "unavailable_lines": unavailable}


def _render(**kw):
    """dry_run=True 捕获 stdout 正文，不落盘 STATUS.md。"""
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        sr.generate_status(latest=[], dry_run=True, **kw)
    return buf.getvalue()


def test_pass_line_follows_active_track():
    """口径切换回归: active_track=track_200 时达标线必须是 170/200。

    若有意切回 track_150，应同步修改本测试预期（防无意识回退）。
    """
    expected = "%s/%s" % (SCORECARD_TRACK_200["pass_line"], SCORECARD_TRACK_200["total"])
    if SCORECARD_ACTIVE_TRACK == "track_200":
        assert sr.PASS_LINE == expected == "170/200"


def test_track200_renders_overall_and_pass_line():
    text = _render(scorecard=_track200(), gate=_gate())
    assert "机器实测综合: 150.1/200 (75.0%)" in text
    assert "达标线: 170/200" in text


def test_track200_renders_six_lines():
    text = _render(scorecard=_track200(), gate=_gate())
    assert "① 跨平台skill互通同步=24.4/33" in text or "①跨平台skill互通同步=24.4/33" in text
    assert "⑥" in text and "27.8/33" in text


def test_gate_id_range_dynamic_c13():
    """13 项门禁 -> 标题 C1~C13（废弃字面量 C1~C12 不得出现）。"""
    text = _render(scorecard=_track200(), gate=_gate())
    assert "C1~C13" in text
    assert "C1~C12" not in text


def test_gate_all_pass_true_header():
    text = _render(scorecard=_track200(), gate=_gate())
    assert "✅ 全部通过" in text
    assert "PASS 13 / FAIL 0 / SKIP 0" in text


def test_gate_fail_flips_header_and_counts():
    text = _render(scorecard=_track200(), gate=_gate(n_pass=12, n_fail=1))
    assert "❌ 存在未通过" in text
    assert "PASS 12 / FAIL 1 / SKIP 0" in text


def test_unavailable_lines_rendered_when_present():
    text = _render(scorecard=_track200(unavailable=["主线⑤ 注意力优化"]), gate=_gate())
    assert "不可用线: 主线⑤ 注意力优化" in text


def test_unavailable_lines_absent_when_empty():
    text = _render(scorecard=_track200(unavailable=None), gate=_gate())
    assert "不可用线" not in text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
