#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_bench_router.py — 规模基准入口的自证：读数单调、抽查有效、异常路径判 rc。

三条腿各自防的失效：
  1. 跑通且 JSON 可读 —— 防「脚本存在但一跑就崩」这类只在 CI 少一步时才暴露的缺陷。
  2. 延迟随规模单调不减 —— 防「基准其实没在测它声称的东西」（例如计时块被挪出循环）。
  3. 空 --sizes 判 rc=2 —— 零输入不得记 PASS，与本仓其它入口一致。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "eval" / "bench_router.py"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(BENCH), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(ROOT))


def test_json_face_is_parseable_and_checks_pass():
    r = run("--sizes", "12,60", "--json")
    assert r.returncode == 0, r.stderr[-400:]
    payload = json.loads(r.stdout)
    rows = payload["rows"]
    assert [x["skills"] for x in rows] == [12, 60]
    for x in rows:
        assert x["check"] == "ok", f"抽查失败：{x}"
        assert x["expected_top1_hits"] == x["n_expected"]
        assert x["index_seconds"] > 0 and x["peak_alloc_mb"] > 0
    assert payload["method"], "输出必须自带方法口径，否则读数无法跨机器对账"


def test_latency_is_monotone_in_scale():
    """规模翻 5 倍而单查询延迟不降 —— 若计时块写错位置，这条会静默变绿到某天。"""
    r = run("--sizes", "50,250", "--json")
    assert r.returncode == 0, r.stderr[-400:]
    a, b = json.loads(r.stdout)["rows"]
    assert b["index_seconds"] >= a["index_seconds"], (a, b)
    assert b["peak_alloc_mb"] >= a["peak_alloc_mb"], (a, b)


def test_empty_sizes_returns_2_not_pass():
    r = run("--sizes", "")
    assert r.returncode == 2
    assert "零规模" in r.stderr
