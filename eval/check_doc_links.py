#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_doc_links.py — 根级文档相对链接存在性检查（R192）。

检查 AGENTS*.md / STATUS*.md / index.md / README.md 中的相对 markdown 链接
（[label](relative)），目标不存在即 FAIL。外部 URL/junction/绝对盘符跳过。
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK_FILES = [
    "AGENTS.md", "AGENTS.md.part1.md", "AGENTS.md.part2.md", "AGENTS.md.part3.md",
    "AGENTS.md.part4.md", "AGENTS.md.part5.md",
    "STATUS.md", "STATUS.part1.md", "index.md", "README.md",
]
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "D:", "C:", "#")


def main() -> int:
    bad = []
    for fname in CHECK_FILES:
        path = os.path.join(ROOT, fname)
        if not os.path.exists(path):
            bad.append(f"{fname}: 文件缺失")
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, 1):
                for target in LINK_RE.findall(line):
                    target = target.split("#")[0].strip()
                    if not target or target.startswith(SKIP_PREFIX):
                        continue
                    resolved = os.path.normpath(os.path.join(ROOT, target))
                    if not os.path.exists(resolved):
                        bad.append(f"{fname}:{line_no} -> {target} 不存在")
    if bad:
        print("doc-links FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    print("doc-links PASS: 根级文档相对链接均存在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
