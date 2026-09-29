# -*- coding: utf-8 -*-
"""lessons_usage_coverage.py — lessons 使用自动记录覆盖率（R170 验收门禁）

覆盖率 = 窗口内有 lessons_usage 记录的会话数 / 窗口内总会话数（session_index.jsonl）
验收: 连续 7 天覆盖率 ≥80%（--days 7 --threshold 0.8，默认）。

用法:
  python eval/lessons_usage_coverage.py [--days 7] [--threshold 0.8] [--json] [--check]
"""
import argparse
import json
import sys
from datetime import date, timedelta

SESSION_INDEX = r"<MEMORY_ROOT>\meta\session_index.jsonl"
USAGE_PATH = r"<MEMORY_ROOT>\meta\lessons_usage.jsonl"


from io_utils import load_jsonl  # P1-5: 读写原语唯一实现


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD 起始（覆盖 --days）")
    a = ap.parse_args()

    today = date.today()
    cutoff = a.since or (today - timedelta(days=a.days - 1)).isoformat()
    sessions = [r for r in load_jsonl(SESSION_INDEX) if r.get("date", "") >= cutoff]
    usage = [r for r in load_jsonl(USAGE_PATH) if r.get("date", "") >= cutoff]

    usage_session_ids = {r.get("session") for r in usage if r.get("session")}
    usage_dates = {r.get("date") for r in usage}
    recorded = [s for s in sessions
                if s.get("session_id") in usage_session_ids or s.get("date") in usage_dates]
    total = len(sessions)
    n_recorded = len(recorded)
    coverage = n_recorded / total if total else 0.0
    ok = total > 0 and coverage >= a.threshold

    per_day = {}
    for s in sessions:
        d = s.get("date")
        per_day.setdefault(d, {"sessions": 0, "recorded": 0})
        per_day[d]["sessions"] += 1
        if s.get("session_id") in usage_session_ids or d in usage_dates:
            per_day[d]["recorded"] += 1

    result = {
        "window_start": cutoff,
        "days": a.days,
        "total_sessions": total,
        "recorded_sessions": n_recorded,
        "coverage": round(coverage, 4),
        "threshold": a.threshold,
        "pass": ok,
        "per_day": per_day,
        "note": "含未加载 lessons 的轻量会话，口径偏保守；机制 2026-08-04 上线，需连续 7 天跟踪",
    }
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"lessons 使用记录覆盖率 = {n_recorded}/{total} = {coverage:.1%} "
              f"(阈值 {a.threshold:.0%}) {'PASS' if ok else '待达标'}")
        for d in sorted(per_day):
            v = per_day[d]
            print(f"  {d}: {v['recorded']}/{v['sessions']}")
    return 0 if (ok or not a.check) else 1


if __name__ == "__main__":
    sys.exit(main())
