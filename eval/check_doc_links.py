#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_doc_links.py — 根级文档相对链接存在性检查（R192）。

检查 AGENTS*.md / STATUS*.md / index.md / README.md 中的相对 markdown 链接
（[label](relative)），目标不存在即 FAIL。外部 URL/junction/绝对盘符跳过。
"""

import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "D:", "C:", "#")


def collect_check_files() -> list[str]:
    """取数面从仓根实际在场的根文档现算，不由手抄名册得出。

    缺陷实证（2026-09-29 对标轮）：本函数前身是一份硬编名册，含
    `AGENTS.md.part1..5.md` 与 `STATUS.md`/`STATUS.part1.md`——那是**私有源仓**的
    分卷形态。对外子集里这些卷刻意不分发，于是本判据在公开面一上来就印
    「7 个文件缺失」并 rc=1：它量的是「名册与另一个面不符」，不是「链接坏了」。
    一把在交付面上必然判红、且红因与它想防的事无关的尺子，接进 CI 只会教会
    下一个人把整条判据注掉。正解＝名册从盘面派生（同一类文件、零手抄常量）。
    """
    found = []
    for pattern in ("AGENTS*.md", "STATUS*.md", "README*.md", "index.md",
                    "CONTRIBUTING*.md", "SECURITY*.md"):
        found.extend(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, pattern)))
    return sorted(set(found))


def main() -> int:
    bad = []
    files = collect_check_files()
    for fname in files:
        path = os.path.join(ROOT, fname)
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, 1):
                for target in LINK_RE.findall(line):
                    target = target.split("#")[0].strip()
                    if not target or target.startswith(SKIP_PREFIX):
                        continue
                    resolved = os.path.normpath(os.path.join(ROOT, target))
                    if not os.path.exists(resolved):
                        bad.append(f"{fname}:{line_no} -> {target} 不存在")
    if not files:
        # 取数面为空不等于通过：那说明判据什么都没看见（盲区≠零，本仓入口级不变量）。
        print("doc-links UNVERIFIED: 仓根没扫到任何根文档，检查未发生", file=sys.stderr)
        return 2
    if bad:
        print(f"doc-links FAIL: 扫 {len(files)} 份根文档，坏链接 {len(bad)} 处")
        for b in bad:
            print("  " + b)
        return 1
    print(f"doc-links PASS: 扫 {len(files)} 份根文档，相对链接均存在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
