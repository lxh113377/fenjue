# -*- coding: utf-8 -*-
"""recurrence_audit.py — lessons 复发率周审计（R170 真实使用闭环主 KPI）

定义（weekly_maintenance Step 14）:
  复发率 = 本周同源复发事件数 / 本周 lessons 命中使用事件数（目标 <10% 且逐周下降）

用法:
  python eval/recurrence_audit.py [--json] [--since 7] [--threshold 0.10] [--check]
  python eval/recurrence_audit.py --errors "os error 123|ParserError" --json

数据源:
  <MEMORY_ROOT>\\meta\\lessons_usage.jsonl（读侧使用记录）
  <MEMORY_ROOT>\\lessons\\*.md（trigger 三栏行 + 条目日期）
"""
import argparse
import json
import os
import re
import sys
from datetime import date, timedelta

from config import GLOBAL_MEMORY  # P1-6 收口: 单源引用（env 可覆盖）

LESSONS_DIR = os.path.join(GLOBAL_MEMORY, "lessons")
USAGE_PATH = os.path.join(GLOBAL_MEMORY, "meta", "lessons_usage.jsonl")


def load_usage():
    rows = []
    if os.path.exists(USAGE_PATH):
        for line in open(USAGE_PATH, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_lesson_triggers():
    """返回 [(entry_date, file, trigger_line)] — 从 ### [date] 头向后关联 trigger 行。"""
    out = []
    if not os.path.isdir(LESSONS_DIR):
        return out
    for fn in sorted(os.listdir(LESSONS_DIR)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(LESSONS_DIR, fn)
        cur_date = None
        for line in open(path, encoding="utf-8", errors="replace"):
            m = re.search(r"###\s*\[(\d{4}-\d{2}-\d{2})\]", line)
            if m:
                cur_date = m.group(1)
            if line.lower().startswith("trigger:"):
                out.append((cur_date, fn, line.strip()))
    return out


def is_recurrence(text, triggers, cutoff):
    """text 命中某个创建早于 cutoff 的 trigger 片段 → 同源复发。"""
    text = text or ""
    for entry_date, fn, tline in triggers:
        if entry_date and entry_date < cutoff:
            # trigger 三栏第一栏是错误串/关键词
            first = tline.split("|")[0].replace("trigger:", "").strip()
            if len(first) >= 4 and first.lower() in text.lower():
                return fn, first
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--since", type=int, default=7, help="窗口天数（默认 7）")
    ap.add_argument("--threshold", type=float, default=0.10)
    ap.add_argument("--check", action="store_true", help="超出阈值时 exit 1")
    ap.add_argument("--errors", default="", help="本周错误串，| 分隔；缺省用 usage 记录的 query/used")
    args = ap.parse_args()

    today = date.today()
    cutoff = (today - timedelta(days=args.since)).isoformat()
    usage = load_usage()
    triggers = load_lesson_triggers()

    window = [r for r in usage if r.get("date", "") >= cutoff]
    usage_events = [r for r in window if r.get("used")]
    error_texts = [e.strip() for e in args.errors.split("|") if e.strip()]

    details = []
    for r in usage_events:
        texts = [r.get("query", "")] + r.get("used", []) + r.get("loaded", [])
        found = None
        for t in texts:
            found = is_recurrence(t, triggers, r.get("date", cutoff))
            if found:
                break
        if found:
            details.append({"session": r.get("session"), "date": r.get("date"),
                            "matched_lesson": found[0], "matched_trigger": found[1],
                            "event": r.get("query", "")})
    for e in error_texts:
        found = is_recurrence(e, triggers, today.isoformat())
        if found:
            details.append({"error": e, "matched_lesson": found[0], "matched_trigger": found[1]})

    recurrence_events = len(details)
    denominator = max(1, len(usage_events) + len(error_texts))
    rate = recurrence_events / denominator
    ok = rate <= args.threshold

    result = {
        "window_days": args.since,
        "window_start": cutoff,
        "usage_events": len(usage_events),
        "manual_error_events": len(error_texts),
        "recurrence_events": recurrence_events,
        "recurrence_rate": round(rate, 4),
        "threshold": args.threshold,
        "pass": ok,
        "details": details,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"复发率 = {recurrence_events}/{denominator} = {rate:.1%} (阈值 {args.threshold:.0%}) "
              f"{'PASS' if ok else 'FAIL'}")
        for d in details:
            print("  -", d)
    return 0 if ok or not args.check else 1


if __name__ == "__main__":
    sys.exit(main())
