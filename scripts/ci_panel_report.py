#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_panel_report.py — 每日 CI 全绿面板上报（驱动脚本，非判据：放 scripts/ 而非 eval/，不进接线普查分母）（判据本体在 global_skills/A-project-handoff/greencheck.py）。

为什么单独一个脚本：`greencheck panel` 只往 stdout 印 ⇒ 没人跑就等于没有。本脚本把
「跑面板 → 落快照 → 只在状态变化时往记忆日志追加一行」串成一条可被计划任务驱动的链。

落点（两份，各司其职；都收在 `.ci/` 与 `reports/`，不散进 eval/ —— 噪声闸 #17）：
  .ci/panel_state.json        机器可读快照（diff 的分母，可再生 ⇒ 已 gitignore）
  reports/ci-panel-log.md     人读日志，自截尾（只留最近 KEEP_LINES 行，防无限长大）

零输入不得记 PASS：面板取不到数时本脚本写 `UNVERIFIED` 行，绝不写「全绿」（R247）。
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_DIR = os.path.join(ROOT, "eval")
sys.path.insert(0, EVAL_DIR)
import config  # noqa: E402  （GLOBAL_SKILLS 由 config 解析，与 pre-push 同源）

GC = os.path.join(config.GLOBAL_SKILLS, "A-project-handoff", "scripts", "greencheck.py")
# 落点在 reports/ 而**不是** memory/：焚诀的 /memory 是指向 <MEMORY_ROOT> 的符号链接且被
# gitignore —— 计划任务往跨端共享记忆根里写文件，既进不了版本史，又会撞其它会话的在途改动。
LOG = os.path.join(ROOT, "reports", "ci-panel-log.md")
KEEP_LINES = 200
HEADER_MARK = "# CI 全绿面板日志"


def run_ledger():
    if not os.path.isfile(GC):
        return None, "判据本体缺失：%s（受管根未挂载？）" % GC
    r = subprocess.run([sys.executable, GC, "ledger", "--write", "--json"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1500)   # 必须 < 调用方 run_gate 的 1800s 预算
    body = (r.stdout or "").strip()
    if not body:
        return None, "ledger 无输出（rc=%s）：%s" % (r.returncode, (r.stderr or "")[:200])
    try:
        return json.loads(body), None
    except ValueError as e:
        return None, "ledger 输出不可解析：%r" % e


def fmt_lines(data):
    """摘要行 + 变化事件行。tally 由数据现算，不抄面板里的字符串。"""
    snap, events = data["snapshot"], data.get("events") or []
    rows = snap.get("rows") or []
    tally = {s: sum(1 for r in rows if r.get("state") == s)
             for s in ("GREEN", "RED", "BLOCKED", "UNKNOWN")}
    mt = snap.get("mute_tally") or {}
    out = ["- [CI面板] rows=%d GREEN=%d RED=%d BLOCKED=%d UNKNOWN=%d | mute covered=%d hollow=%d "
           "naked=%d exempt=%d unverified=%d | verdict=%s" % (
               len(rows), tally["GREEN"], tally["RED"], tally["BLOCKED"], tally["UNKNOWN"],
               mt.get("covered", 0), mt.get("hollow", 0), mt.get("naked", 0),
               mt.get("exempt", 0), mt.get("unverified", 0), snap.get("verdict"))]
    for e in events:
        out.append("  · %s" % json.dumps(e, ensure_ascii=False, sort_keys=True))
    if not rows:
        out.append("  · ⚠️ UNVERIFIED：面板零行 ⇒ 本次读数不可信，不得记全绿")
    return out


def append_log(lines):
    """标题行每次重生（旧文件里的标题行按前缀剔掉，否则每跑一次多一行头）。"""
    body = []
    if os.path.isfile(LOG):
        with open(LOG, encoding="utf-8") as f:
            body = [ln for ln in f.read().splitlines() if not ln.startswith(HEADER_MARK)]
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    merged = body + ["## %s" % stamp] + lines
    trimmed = merged[-KEEP_LINES:]
    dropped = len(merged) - len(trimmed)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "w", encoding="utf-8", newline="\n") as f:
        f.write("%s — 由 scripts/ci_panel_report.py 追加（自截尾最近 %d 行%s）\n\n" % (
            HEADER_MARK, KEEP_LINES, "，本次截掉 %d 行" % dropped if dropped else ""))
        f.write("\n".join(trimmed) + "\n")
    return len(lines), len(trimmed), dropped


def main(argv=None):
    dry = "--dry-run" in (argv if argv is not None else sys.argv[1:])
    data, err = run_ledger()
    if err:
        print("[ci-panel] FAIL: %s" % err)
        if not dry:
            append_log(["- [CI面板] UNVERIFIED — %s" % err])
        return 2
    lines = fmt_lines(data)
    print("\n".join(lines))
    if dry:
        print("[ci-panel] --dry-run：未写日志（快照已由 ledger --write 落盘）")
    else:
        wrote, total, dropped = append_log(lines)
        print("[ci-panel] 日志 %s：+%d 行（保留 %d 行，截掉 %d）" % (LOG, wrote, total, dropped))
    bad = any(e.get("to") in ("RED", "UNKNOWN") or e.get("mute_to") in ("naked", "hollow")
              for e in (data.get("events") or []))
    return 1 if (bad or data["snapshot"].get("verdict") == "RED") else 0


if __name__ == "__main__":
    sys.exit(main())
