#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trace_view 契约测试（R196）：聚合日志 → 报告结构。"""

import json
import os
import sys

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "scripts")
sys.path.insert(0, os.path.abspath(SCRIPT_DIR))

import trace_view as tv  # noqa: E402


def _mk(tmp_path, name, rows):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_gate_trace_counts_pass_fail(tmp_path):
    _mk(tmp_path, "memory/sessions/savepoint-gate.jsonl", [
        {"ts": "2026-08-12T10:00:00", "exit": 0, "all_pass": True, "missing_steps": []},
        {"ts": "2026-08-12T10:05:00", "exit": 1, "all_pass": False,
         "missing_steps": ["步骤未达可收尾态: ['1']"]},
    ])
    out = tv.gate_trace(str(tmp_path))
    assert out["rows"] == 2
    assert out["passed"] == 1
    assert out["failed"] == 1
    assert len(out["failed_steps"]) == 1
    assert out["avg_interval_minutes"] == 5.0


def test_failure_cost_trend_v2(tmp_path):
    _mk(tmp_path, "memory/sessions/savepoint-gate.jsonl", [
        {"ts": "2026-08-12T10:00:00", "exit": 0, "schema_v": 2,
         "failure_cost": {"gate_fails": 0, "rollbacks": 1,
                          "est_wasted_minutes": 30, "failure_budget": 2}},
        {"ts": "2026-08-12T11:00:00", "exit": 0, "schema_v": 1},  # 旧行兼容
    ])
    out = tv.failure_cost_trend(str(tmp_path))
    assert out["total"]["rollbacks"] == 1
    assert out["total"]["est_wasted_minutes"] == 30
    assert out["total"]["failure_budget"] == 2
    assert "2026-08-12" in out["by_date"]


def test_recommendation_hitrate(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "07-next-steps.md").write_text(
        "## P0\n\n- [ ] 任务一 [推荐:R196-01]\n- [x] 任务二 [推荐:R196-02]\n",
        encoding="utf-8")
    out = tv.recommendation_hitrate(str(tmp_path))
    assert out["total"] == 2
    assert out["closed"] == 1
    assert out["hit_rate"] == 0.5


def test_lessons_hitrate(tmp_path, monkeypatch):
    usage = tmp_path / "lessons_usage.jsonl"
    usage.write_text(
        '{"date":"2026-08-12","useful":true}\n'
        '{"date":"2026-08-12","useful":"unused"}\n'
        '{"date":"2026-08-12","useful":false}\n', encoding="utf-8")
    monkeypatch.setattr(tv, "LESSONS_USAGE_PATH", str(usage))
    out = tv.lessons_hitrate()
    assert out["rows"] == 3
    assert out["useful"] == 1
    assert out["hit_rate"] == round(1 / 3, 3)


def test_build_report_schema(tmp_path):
    report = tv.build_report(str(tmp_path))
    assert report["schema"] == "fenjue-trace-view-v1"
    for key in ("gate_trace", "failure_cost_trend", "route_chain",
                "llm_decisions", "lessons_hitrate", "recommendation_hitrate"):
        assert key in report
