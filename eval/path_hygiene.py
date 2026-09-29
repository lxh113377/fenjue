#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""path_hygiene.py — 盘符路径字面量 ratchet lint（P1-6 收口，2026-09-02）。

原理（棘轮模式）：
  - 存量硬编码路径以 baseline 快照放行（eval/path_hygiene_baseline.json），
    不要求一次性清完 49 个历史文件；
  - 任何文件的字面量计数 **超过基线**、或基线中不存在的新文件出现字面量 → FAIL；
  - 收口一个文件就把它的基线计数改成 0（或删除条目），棘轮只进不退。

扫描范围: eval/ 与 scripts/ 的 .py（排除 tests/、_cache/、__pycache__）。
匹配模式: 盘符绝对路径（D:\\global_*、C:\\Users、<NPM_GLOBAL> 等真实机器路径）。
白名单: 注释行（以 # 开头，去首空白）不计数；env 兜底写法 r"<SKILLS_ROOT>"
       在 truth_constants.py 定义点白名单（文件级）。

退出码: 0 = PASS（未超基线），1 = FAIL（有新增），2 = 基线文件损坏。
用法:
    python eval/path_hygiene.py                # 校验
    python eval/path_hygiene.py --update-baseline  # 重新生成基线（显式收口后用）
"""
import json
import os
import re
import sys
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(EVAL_DIR)
BASELINE_PATH = os.path.join(EVAL_DIR, "path_hygiene_baseline.json")

# 盘符绝对路径（匹配 D:\xxx / C:\Users\... 等机器真实路径；单盘符+冒号+反斜杠）。
# 前置 (?<![A-Za-z0-9_]) 是承重的：少了它，正则源码里的 `version:\s`、`x:\d` 这类
# 「字母 + 冒号 + 转义」会被当成盘符路径（本轮实测误伤 `verify_truth_consistency.py:199`）。
PATTERN = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:\\[^\s'\"]*")
# 允许字面量的文件（truth 常量定义点 / 本 lint 自身 / 生成器）
FILE_WHITELIST = {"truth_constants.py", "path_hygiene.py", "config.py"}
SKIP_DIRS = {"tests", "_cache", "__pycache__"}


def _iter_targets():
    for top in ("eval", "scripts"):
        base = os.path.join(REPO_ROOT, top)
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                if fn.endswith(".py"):
                    yield os.path.join(root, fn)


def scan():
    """返回 {相对路径: 命中行号列表}。注释行不计数。"""
    hits = {}
    for path in _iter_targets():
        rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
        if os.path.basename(path) in FILE_WHITELIST:
            continue
        try:
            with Path(path).open(encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        found = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # R209: 行内豁免机制落地（修复「提示文字有、机器逻辑无」漂移）——
            # 行尾含 path-hygiene:ok 标记的行视为已人工裁定（如 Windows 系统常量
            # C:\Windows 等非机器特定路径），不计入棘轮命中。
            if "path-hygiene:ok" in line:
                continue
            if PATTERN.search(line):
                found.append(i)
        if found:
            hits[rel] = found
    return hits


def main() -> int:
    hits = scan()
    if "--update-baseline" in sys.argv:
        Path(BASELINE_PATH).write_text(
            json.dumps(hits, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        total = sum(len(v) for v in hits.values())
        print(f"[path-hygiene] 基线已更新: {len(hits)} 文件 / {total} 处（存量放行，棘轮只进不退）")
        return 0

    try:
        baseline = json.loads(Path(BASELINE_PATH).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[path-hygiene] FAIL: 基线文件不可读（{e}）——先跑 --update-baseline 生成")
        return 2

    violations = {}
    for rel, lines in hits.items():
        base_lines = baseline.get(rel)
        if base_lines is None:
            if rel not in baseline:  # 新文件出现字面量
                violations[rel] = lines
        elif len(lines) > len(base_lines):
            # 同文件超基线计数（行号可能漂移，按数量棘轮）
            violations[rel] = lines[len(base_lines):]
    if violations:
        print(f"[path-hygiene] FAIL: {len(violations)} 个文件出现新增盘符字面量（棘轮拦截）")
        for rel, lines in list(violations.items())[:10]:
            print(f"  {rel}: 行 {lines[:8]}")
        print("  修复: 改用 config/truth_constants 导入；确属外部平台遗留路径可加行内注释豁免说明")
        return 1
    total = sum(len(v) for v in hits.values())
    print(f"[path-hygiene] PASS: 无新增字面量（存量 {len(hits)} 文件 / {total} 处由基线放行，待逐步收口）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
