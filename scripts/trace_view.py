#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trace_view.py — 执行追踪视图（R196，部分-8 / 七.2 + 六.3 趋势 + 覆盖-3/5 数据源）

聚合多个日志源生成「执行追踪报告」：
  - memory/sessions/savepoint-gate.jsonl   门禁执行记录（含 v2 failure_cost）
  - eval/route_trace.jsonl                 路由调用链
  - eval/llm_decisions.jsonl               LLM 决策记录
  - <MEMORY_ROOT>\\meta\\lessons_usage.jsonl  lessons 读侧命中率
  - memory/07-next-steps.md                [推荐:<id>] 标记命中率

用法:
  python scripts/trace_view.py [--project <path>] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_DIR, "eval"))
# P1-6 批次②: 单源引用（env 可覆盖）
from config import GLOBAL_MEMORY  # noqa: E402
from io_utils import read_text_safe  # noqa: E402  # P1-5: 读写原语唯一实现

SAVEPOINT_GATE_REL = os.path.join("memory", "sessions", "savepoint-gate.jsonl")
ROUTE_TRACE_REL = os.path.join("eval", "route_trace.jsonl")
LLM_DECISIONS_REL = os.path.join("eval", "llm_decisions.jsonl")
NEXT_STEPS_REL = os.path.join("memory", "07-next-steps.md")
LESSONS_USAGE_PATH = os.path.join(GLOBAL_MEMORY, "meta", "lessons_usage.jsonl")


def _read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return rows


def _read_text(path: str) -> str:
    return read_text_safe(path, errors='strict')


def gate_trace(project: str) -> dict:
    rows = _read_jsonl(os.path.join(project, SAVEPOINT_GATE_REL))
    passed = sum(1 for r in rows if r.get("exit") == 0)
    failed = sum(1 for r in rows if r.get("exit") != 0)
    failed_steps = []
    for r in rows:
        for s in r.get("missing_steps", []) or []:
            failed_steps.append(f"{r.get('ts', '?')} 缺步: {s}")
    # 相邻两行 ts 差近似每步耗时（分钟）
    durations = []
    for prev, cur in zip(rows, rows[1:]):
        try:
            t0 = datetime.fromisoformat(prev["ts"])
            t1 = datetime.fromisoformat(cur["ts"])
            durations.append(max(0, (t1 - t0).total_seconds() / 60))
        except Exception:
            continue
    return {
        "rows": len(rows),
        "passed": passed,
        "failed": failed,
        "failed_steps": failed_steps[:10],
        "avg_interval_minutes": round(sum(durations) / len(durations), 2) if durations else None,
        "last_ts": rows[-1].get("ts") if rows else None,
    }


def failure_cost_trend(project: str) -> dict:
    rows = _read_jsonl(os.path.join(project, SAVEPOINT_GATE_REL))
    by_date: dict[str, dict] = defaultdict(
        lambda: {"gate_fails": 0, "rollbacks": 0, "est_wasted_minutes": 0,
                 "failure_budget": 0, "budget_declared": 0})
    total = {"gate_fails": 0, "rollbacks": 0, "est_wasted_minutes": 0,
             "failure_budget": 0, "budget_declared": 0}
    for r in rows:
        fc = r.get("failure_cost") or {}
        ts = str(r.get("ts") or "")[:10]
        if not ts:
            continue
        d = by_date[ts]
        for k in ("gate_fails", "rollbacks", "est_wasted_minutes", "failure_budget"):
            v = fc.get(k, 0)
            if isinstance(v, (int, float)):
                d[k] += v
                total[k] += v
        if fc.get("failure_budget") is not None:
            d["budget_declared"] += 1
            total["budget_declared"] += 1
    return {
        "by_date": {k: dict(v) for k, v in sorted(by_date.items())},
        "total": dict(total),
    }


def route_chain(project: str) -> dict:
    rows = _read_jsonl(os.path.join(project, ROUTE_TRACE_REL))
    per_src = Counter(r.get("src", "?") for r in rows)
    per_skill = Counter(r.get("top1", "?") for r in rows)
    return {
        "rows": len(rows),
        "per_src": dict(per_src),
        "top_skills": per_skill.most_common(15),
    }


def llm_decisions(project: str) -> dict:
    rows = _read_jsonl(os.path.join(project, LLM_DECISIONS_REL))
    per_resolution = Counter(r.get("resolution", "?") for r in rows)
    return {"rows": len(rows), "per_resolution": dict(per_resolution)}


def lessons_hitrate() -> dict:
    rows = _read_jsonl(LESSONS_USAGE_PATH)
    useful = sum(1 for r in rows if str(r.get("useful")).lower() in ("true", "1"))
    unused = sum(1 for r in rows if str(r.get("useful")).lower() in ("unused", "false", "0"))
    return {
        "rows": len(rows),
        "useful": useful,
        "unused_or_false": unused,
        "hit_rate": round(useful / len(rows), 3) if rows else None,
    }


def recommendation_hitrate(project: str) -> dict:
    text = _read_text(os.path.join(project, NEXT_STEPS_REL))
    open_ids = set(re.findall(r"^-\s*\[ \]\s*.*?\[推荐:([\w\-]+)\]", text, re.M))
    closed_ids = set(re.findall(r"^-\s*\[[xX]\]\s*.*?\[推荐:([\w\-]+)\]", text, re.M))
    total = len(open_ids | closed_ids)
    return {
        "total": total,
        "closed": len(closed_ids),
        "open": len(open_ids),
        "hit_rate": round(len(closed_ids) / total, 3) if total else None,
        "open_ids": sorted(open_ids)[:20],
    }


def build_report(project: str) -> dict:
    return {
        "schema": "fenjue-trace-view-v1",
        "generated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "gate_trace": gate_trace(project),
        "failure_cost_trend": failure_cost_trend(project),
        "route_chain": route_chain(project),
        "llm_decisions": llm_decisions(project),
        "lessons_hitrate": lessons_hitrate(),
        "recommendation_hitrate": recommendation_hitrate(project),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="执行追踪视图（R196）")
    p.add_argument("--project", default=PROJECT_DIR)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    report = build_report(os.path.abspath(args.project))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    g = report["gate_trace"]
    print(f"门禁执行追踪: 共 {g['rows']} 次（通过 {g['passed']} / 失败 {g['failed']}）"
          f" | 平均间隔 {g['avg_interval_minutes']} 分钟 | 最近 {g['last_ts']}")
    for s in g["failed_steps"]:
        print(f"  失败点: {s}")
    fc = report["failure_cost_trend"]
    t = fc["total"]
    print(f"失败成本: 门禁失败 {t['gate_fails']} / 回滚 {t['rollbacks']} / "
          f"浪费 {t['est_wasted_minutes']} 分钟 / 预算声明 {t['budget_declared']} 次")
    rc = report["route_chain"]
    print(f"路由调用链: {rc['rows']} 条 trace | 来源 {rc['per_src']}")
    print("  高频 skill: " + ", ".join(f"{k}({v})" for k, v in rc["top_skills"][:8]))
    ld = report["llm_decisions"]
    print(f"LLM 决策: {ld['rows']} 条 | 解析 {ld['per_resolution']}")
    lh = report["lessons_hitrate"]
    print(f"lessons 命中率: {lh['rows']} 条记录 | 有效 {lh['useful']} "
          f"| 未用/无效 {lh['unused_or_false']} | 命中率 {lh['hit_rate']}")
    rh = report["recommendation_hitrate"]
    print(f"推荐命中率: {rh['closed']}/{rh['total']}（{rh['hit_rate']}）")
    for rid in rh["open_ids"]:
        print(f"  未命中推荐: {rid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
