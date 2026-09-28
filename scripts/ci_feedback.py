#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_feedback.py — 反馈闭环接入 CI（item 12）

从 feedback/feedback.jsonl 聚合反馈统计，产出:
  - feedback-summary.json   供 ci_summary 消费
  - feedback-report.md       可读报告 + 写入 $GITHUB_STEP_SUMMARY

门禁:
  --fail-on-critical N    open 且严重度=致命 数量 >= N 则 exit 2（默认 1）
  --fail-on-high N        open 且严重度=高 数量 >= N 则 exit 2（默认 10**9，即默认不卡高）

回收（自动触发闭环）:
  --auto-close-recovered   把已标记 recovered=True 但仍是 open 的条目关闭（落盘）。
                           CI 中仅在 workflow_dispatch/schedule 下启用，随后由工作流 commit 回仓库。

依赖: feedback/app.py（仅在 build_app() 内 import flask，顶层无重依赖，可安全 import）。
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_JSONL = os.path.join(REPO_ROOT, "feedback", "feedback.jsonl")


def _load_feedback_app():
    path = os.path.join(REPO_ROOT, "feedback", "app.py")
    spec = importlib.util.spec_from_file_location("feedback_app", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="反馈闭环 CI 聚合")
    ap.add_argument("--file", default=DEFAULT_JSONL)
    ap.add_argument("--json-out", default=os.path.join(REPO_ROOT, "feedback-summary.json"))
    ap.add_argument("--report-md", default=os.path.join(REPO_ROOT, "feedback-report.md"))
    ap.add_argument("--fail-on-critical", type=int, default=1)
    ap.add_argument("--fail-on-high", type=int, default=10 ** 9)
    ap.add_argument("--auto-close-recovered", action="store_true")
    args = ap.parse_args()

    fb = _load_feedback_app()
    rows = fb.load_entries(args.file)
    s = fb.summarize(args.file)

    recovered_pending = [
        r for r in rows
        if r.get("recovered") is True and r.get("status") == "open"
    ]
    closed_now = 0
    if args.auto_close_recovered:
        for r in recovered_pending:
            if fb.close_entry(r.get("id"), args.file):
                closed_now += 1

    out = {
        "total": s["total"],
        "open": s["open"],
        "closed": s["closed"],
        "by_category": s["by_category"],
        "by_severity": s["by_severity"],
        "open_items": s["open_items"],
        "recovered_pending": len(recovered_pending),
        "closed_now": closed_now,
    }
    Path(args.json_out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    L = ["# 反馈闭环汇总", ""]
    L.append(f"- 总数 **{s['total']}** | open {s['open']} | closed {s['closed']}")
    if closed_now:
        L.append(f"- 本次自动回收(关闭)已恢复条目: **{closed_now}**")
    elif recovered_pending:
        L.append(f"- 待回收(已恢复未关闭): **{len(recovered_pending)}**（dispatch 运行可自动关闭）")
    if s["by_category"]:
        L.append("- 按类别: " + ", ".join(f"{k}={v}" for k, v in sorted(s["by_category"].items())))
    if s["open_items"]:
        L.append("- 待处理(open):")
        for it in s["open_items"]:
            L.append(f"  - [{it['severity']}] {it['id']}: {it['task']}")
    md = "\n".join(L)
    Path(args.report_md).write_text(md, encoding="utf-8")
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with Path(gh).open("a", encoding="utf-8") as f:
            f.write(md + "\n")

    crit = s["by_severity"].get("致命", 0)
    high = s["by_severity"].get("高", 0)
    print(f"feedback total={s['total']} open={s['open']} critical(open)={crit} high(open)={high}")
    if crit >= args.fail_on_critical:
        print(f"[GATE] FAIL: open 致命={crit} >= {args.fail_on_critical}")
        return 2
    if high >= args.fail_on_high:
        print(f"[GATE] FAIL: open 高={high} >= {args.fail_on_high}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
