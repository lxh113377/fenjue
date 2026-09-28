# -*- coding: utf-8 -*-
"""lessons_quality_report.py — 记忆注入质量评估（R1 评估轮 T11 补缺）

补齐 memory.txt 蓝图「可观测性-2 质量评估」缺口：
统计 lessons_usage.jsonl 中 improved_output 分布与 yes 率，
输出注入质量趋势，供 trace_view / 周维护消费。

口径（对齐 A-get-memory Step 1.5）：
  yes 率 = improved_output=yes 条目数 / used=true 条目数
  yes 率 < 30% → 路由精度预警（Step 1.5 既有口径）
  连续 3 次 no → 触发 R5 陈旧候选（提示，不自动处置）

用法:
  python eval/lessons_quality_report.py [--json] [--threshold 0.3] [--since YYYY-MM-DD]
"""
import argparse
import json
import os
from collections import Counter

USAGE_PATH = r"<MEMORY_ROOT>\meta\lessons_usage.jsonl"


from io_utils import load_jsonl  # P1-5: 读写原语唯一实现


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.3)
    ap.add_argument("--since", default=None, help="YYYY-MM-DD 起始（默认全量）")
    a = ap.parse_args()

    rows = load_jsonl(USAGE_PATH)
    # 过滤 manual_forget 动作行（无 improved_output 字段）
    usage = [r for r in rows if r.get("query") or r.get("session")]
    if a.since:
        usage = [r for r in usage if r.get("date", "") >= a.since]

    total = len(usage)
    used = [r for r in usage if r.get("used") or r.get("useful") == "true"]
    improved = Counter(r.get("improved_output", "unknown") for r in used)

    yes_n = improved.get("yes", 0)
    used_n = len(used)
    yes_rate = yes_n / used_n if used_n else 0.0
    ok = used_n == 0 or yes_rate >= a.threshold

    # 连续 no 候选（简化：统计 no 条目清单）
    stale = [r for r in used if r.get("improved_output") == "no"]

    result = {
        "source": USAGE_PATH,
        "window": a.since or "all",
        "total_records": total,
        "used_records": used_n,
        "improved_dist": dict(improved),
        "yes_rate": round(yes_rate, 4),
        "threshold": a.threshold,
        "pass": ok,
        "stale_candidates": len(stale),
        "stale_detail": [
            {"date": r.get("date"), "session": r.get("session"), "key": (r.get("used") or [""])[0]}
            for r in stale[:5]
        ],
        "note": "yes率=improved_output=yes/used=true；unknown=历史数据未回填（Step 1.5 口径）；连续3次no触发R5陈旧候选",
    }
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"记忆注入质量：used={used_n}/{total} | yes率={yes_rate:.1%} "
              f"(阈值 {a.threshold:.0%}) {'PASS' if ok else '预警'}")
        print(f"  improved 分布: {dict(improved)}")
        print(f"  R5 陈旧候选: {len(stale)} 条")
    return 0 if ok else 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
