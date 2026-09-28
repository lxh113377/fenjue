#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""claim_count_lock.py —— 「计数断言必须带可复算依据」的静态锁（对标轮十一批注落地，D-71）。

为什么是这个粒度：实测 `reports/` + `deliverables/` 里共 **1516 行**含"N 个 / N 道 / N 项…"式
计数，其中只有 132 行（8.7%）带了可复算命令。全量判红 = 1384 处历史噪声，等于没有判据；
而历史留痕按项目纪律**不可改写**。所以只判**本次新增行**：老账不追，新账必须带依据。

两条放行形态（都不是"贴个标记就过"）：
  A. 行内含反引号包裹的可复算命令（`git …` / `wc …` / `stat …` / `grep …` / `python …` / `rg …` / `gh …` / `pytest …`）；
  B. 行内含**可定位的外部取证**：`路径:行号`、7~40 位 commit hash、或另一份 `reports|deliverables/*.md`。
其余一律计违规。豁免表为空是刻意的——本锁治的正是"数没跑过就写"。

判据面：`--staged`（暂存区，本地/钩子用）｜`--range <rev>`（与上一提交比，CI 用）。
退出码：0 无新增违规 / 1 有 / 2 判据面失效（不在 git 仓、rev 不可解析、面为空且非有意）。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACES = ("reports/", "deliverables/")
CLAIM_RE = re.compile(r"\d+\s*(?:个|道|项|例|卷|次|处|条|轮|端|文件)")
CMD_RE = re.compile(r"`[^`]*\b(?:git|wc|stat|ls|grep|rg|python|pytest|gh|awk|sort|find)\b[^`]*`")
PROOF_RE = re.compile(r"(?:[\w./-]+\.(?:md|py|json|yml):\d+)|\b[0-9a-f]{7,40}\b"
                      r"|(?:reports|deliverables)/[\w.\-%\u4e00-\u9fff-]+\.md")
HUNK_RE = re.compile(r"^@@ -\S+ \+(\d+)")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def added_lines(mode: str, rev: str) -> list:
    """返回 [(file, lineno, text)]，只含新增行。中文路径必须 quotepath=off。"""
    args = ["diff", "--unified=0", "--no-color"]
    if mode == "staged":
        args.append("--cached")
    else:
        args += [rev, "HEAD"]
    out = _git(*args)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip()[:160])
    cur, ln, rows = None, 0, []
    for line in out.stdout.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
            continue
        if line.startswith("@@ "):
            m = HUNK_RE.match(line)
            ln = int(m.group(1)) if m else ln
            continue
        if cur and cur.startswith(FACES):
            if line.startswith("+") and not line.startswith("+++"):
                rows.append((cur, ln, line[1:]))
                ln += 1
            elif not line.startswith("-"):
                ln += 1
    return rows


def judge(rows: list) -> list:
    return [{"file": f, "line": n, "claim": t.strip()[:90]}
            for f, n, t in rows
            if CLAIM_RE.search(t) and not (CMD_RE.search(t) or PROOF_RE.search(t))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="计数断言复算锁（D-71）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true", help="判暂存区新增行")
    g.add_argument("--range", dest="rev", metavar="REV", help="判 REV..HEAD 新增行（CI 用）")
    ns = ap.parse_args(argv)
    mode = "staged" if ns.staged else "range"
    try:
        rows = added_lines(mode, ns.rev or "HEAD~1")
    except (RuntimeError, OSError) as e:
        print(f"[claim-count] FAIL-FAST: 判据面不可达: {e}")
        return 2
    bad = judge(rows)
    print(f"[claim-count] {'PASS' if not bad else 'FAIL'}: 扫新增行 {len(rows)} / "
          f"含计数断言且无复算依据 {len(bad)}")
    for v in bad[:8]:
        print(f"  {v['file']}:{v['line']}  {v['claim']}")
    if bad:
        print("  修法：在该行补反引号包裹的复算命令（如 `git ls-files -z | wc -l`），"
              "或改成指向 路径:行号 / commit / 另一份报告的可定位取证")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
