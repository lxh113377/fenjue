#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_index_refs.py — 同主题多文件指针索引健康检查（R196-05 固化，2026-08-16）

定位：将此前「每次手工编写临时脚本」的指针存在性检测固化为常驻可复用脚本，
杜绝同类路径解析问题反复出现（焚诀\\ 前缀、lessons/meta 子目录假 MISS 等）。

作用对象：
  - 主索引：<MEMORY_ROOT>\\meta\\memory_index.part3.md（15 行主题→三源指针表）
  - 可扩展：--target <file> 指定任意含 `路径` 引用的 md/json 文件

用法：
  python eval/check_index_refs.py                      # 检查默认主索引，缺失 exit 1
  python eval/check_index_refs.py --target <file>      # 检查任意文件
  python eval/check_index_refs.py --json               # 机器可读输出（周维护 Step 4l 消费）
  python eval/check_index_refs.py --list-targets        # 列出默认检测目标
  python eval/check_index_refs.py --verbose             # 输出每个引用解析到的具体路径

路径解析规则（消除假 MISS 的权威定义，2026-08-16 实测）：
  1. 「焚诀\\」前缀 → 解析到项目根 <USER_HOME>\\Desktop\\workspace\\焚诀\\（大小写不敏感）
  2. 无前缀相对引用 → 依序尝试候选根：meta/ → lessons/ → skill_content/ → memory/ →
     core/ → info/ → <MEMORY_ROOT> 根 → 项目根 → <SKILLS_ROOT> → D:\\trae
  3. 搜索式引用（含 partN/|/搜 等通配符或关键词）→ 跳过不校验（非路径）
  4. 绝对路径（盘符开头）→ 直接 exists() 校验
  5. 目录引用（如 utf8-encoding-fix\\）→ 按目录 exists() 校验
  6. 仅校验明确的路径引用：含 .md/.json/.py/.npy/.npz/.pkl/.ps1/.txt/.jsonl/.ini 后缀
     或为绝对路径目录

回归测试：
  python -m pytest eval/tests/test_check_index_refs.py -q   # 正例/假MISS/搜索式/缺失 全覆盖
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ── 权威路径常量 ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(r"<USER_HOME>\Desktop\workspace\焚诀")
GLOBAL_MEMORY = Path(r"<MEMORY_ROOT>")
GLOBAL_SKILLS = Path(r"<SKILLS_ROOT>")
TRAE_ROOT = Path(r"D:\trae")

# 默认检测目标（可 --target 覆盖）：主索引 + 三源路径表
# R278（2026-09-22）：原硬编码 ["memory_index.part3.md", "memory_index.part3-1.md"]，
# 但这两个文件**已不存在**（实测 meta/ 下现为 memory_index.md / .part1.md / .part2.md
# 及 _full.* 系列 —— part3 曾在拆卷调整中被合并/删除）⇒ `test_default_targets_all_pass`
# 与 `test_cli_json` 恒 FAIL（**测试/目标过期，非索引引用损坏**）。
# 改为**动态发现**：meta 下所有 memory_index*.md 主索引，文件增删后本目标自动跟随，
# 杜绝「索引改名 → 目标表忘改 → 门禁恒红」的同型漂移。
DEFAULT_TARGETS = sorted((GLOBAL_MEMORY / "meta").glob("memory_index*.md"))

# 候选根（解析顺序即优先级；相对引用按此顺序尝试）
CANDIDATE_ROOTS = [
    GLOBAL_MEMORY / "meta",
    GLOBAL_MEMORY / "lessons",
    GLOBAL_MEMORY / "skill_content",
    GLOBAL_MEMORY / "memory",
    GLOBAL_MEMORY / "core",
    GLOBAL_MEMORY / "info",
    GLOBAL_MEMORY,
    PROJECT_ROOT,
    GLOBAL_SKILLS,
    TRAE_ROOT,
]

# 明确路径引用后缀（.md/.json/.py/.npy 等机器/文档文件）
PATH_SUFFIXES = (".md", ".json", ".py", ".npy", ".npz", ".pkl",
                 ".ps1", ".txt", ".jsonl", ".ini", ".yaml", ".yml")

# 搜索式/通配符标记（命中任一即跳过——非路径引用）
SEARCH_MARKERS = ("partN", "|", "搜 ", "搜索", "TOP3")
# 命令/glob 前缀（命中即跳过——命令示例或通配符表达式）
CMD_PREFIXES = ("rg ", "grep ", "python ", "find ", "ls ", "dir ")


def _norm(p: str) -> str:
    """路径归一化：反斜杠 → 正斜杠（Windows 路径在正则/比较时统一）。"""
    return p.replace("\\", "/")


def _is_path_ref(ref: str) -> bool:
    """判定是否为「明确的路径引用」（需校验存在性）；搜索式/通配符/命令跳过。"""
    if ref.endswith("/") or ref.startswith(("http", "www")):
        return False
    if any(m in ref for m in SEARCH_MARKERS):
        return False
    if "*" in ref or "?" in ref:
        return False  # glob 通配符
    # R278（2026-09-22）：**模板占位符**不算路径 —— 索引里有形态教学式的引用
    # （如 `memory/YYYY-MM-DD.md` 用于说明「今日/昨天」对应的文件名格式），
    # 它永远不可能 exists ⇒ 原判据把它当真实引用并使门禁恒红
    # （实测 memory_index.part1.md:26 → test_check_index_refs 长期 FAIL）。
    #
    # ⚠️ 判据必须**极窄**：首版写成 (YYYY|MM|DD|HH|mm|ss|partN|...) 时，
    #    `ss` 命中了普通单词 `lessons`（l-e-s-s-o-n-s）⇒ `lessons/DEAD.md`
    #    被判为非路径，导致 routing_index_health 的死链检测失效、3 个测试回归
    #    （实测 test_check2_fail_dead 由 PASS 变 FAIL）。只保留真正不会出现在
    #    正常路径里的模板标记。
    if "YYYY" in ref or re.search(r"<[^>]{1,40}>", ref):
        return False
    if any(ref.lower().startswith(p) for p in CMD_PREFIXES):
        return False  # 命令示例（rg/python 等）
    if re.search(r"\.(" + "|".join(s[1:] for s in PATH_SUFFIXES) + r")$", ref, re.I):
        return True
    return os.path.isabs(_norm(ref))  # 绝对路径目录


def resolve_candidates(ref: str) -> list[str]:
    """路径解析规则（权威定义，消除假 MISS）。

    返回候选绝对路径列表（按优先级）；调用方任一 exists 即命中。
    """
    rr = _norm(ref)
    cands: list[str] = []

    # 规则 1：「焚诀\」前缀 → 项目根（大小写不敏感）
    if rr.lower().startswith("焚诀/"):
        cands.append(_norm(str(PROJECT_ROOT)) + "/" + rr[len("焚诀/"):])
        return cands

    # 规则 4：绝对路径（盘符开头）
    if os.path.isabs(rr):
        cands.append(rr)
        return cands

    # 规则 2：无前缀相对引用 → 依序尝试候选根
    for root in CANDIDATE_ROOTS:
        cands.append(_norm(str(root)) + "/" + rr)
    return cands


def extract_refs(content: str) -> list[str]:
    """提取反引号 `path` 引用（去重保序）。"""
    seen: set[str] = set()
    out: list[str] = []
    for m in re.findall(r"`([^`]+)`", content):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def check_file(path: Path, verbose: bool = False) -> dict:
    """检查单文件全部路径引用；返回 {checked, missing, resolved}。"""
    content = path.read_text(encoding="utf-8", errors="replace")
    refs = extract_refs(content)
    missing: list[str] = []
    resolved: dict[str, str] = {}
    checked = 0
    for ref in refs:
        if not _is_path_ref(ref):
            continue
        checked += 1
        cands = resolve_candidates(ref)
        hit = next((c for c in cands if os.path.exists(c)), None)
        if hit:
            resolved[ref] = hit
        else:
            missing.append(ref)
    return {"file": str(path), "refs_total": len(refs),
            "checked": checked, "missing": missing, "resolved": resolved}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="同主题多文件指针索引健康检查（R196-05 固化）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--target", action="append", default=None,
                    help="指定检查文件（可多次）；默认 DEFAULT_TARGETS")
    ap.add_argument("--json", action="store_true", help="机器可读输出（周维护 Step 4l 消费）")
    ap.add_argument("--verbose", action="store_true", help="输出每个引用解析到的具体路径")
    ap.add_argument("--list-targets", action="store_true", help="列出默认检测目标")
    args = ap.parse_args(argv)

    if args.list_targets:
        for t in DEFAULT_TARGETS:
            print(t)
        return 0

    targets = [Path(t) for t in args.target] if args.target else DEFAULT_TARGETS

    results = []
    all_missing: list[str] = []
    for t in targets:
        if not t.exists():
            print(f"⚠️ 目标不存在（跳过）: {t}")
            continue
        r = check_file(t, verbose=args.verbose)
        results.append(r)
        all_missing.extend(r["missing"])
        if args.verbose:
            for ref, hit in r["resolved"].items():
                print(f"  ✅ {ref} → {hit}")

    total_checked = sum(r["checked"] for r in results)
    if args.json:
        print(json.dumps({
            "schema": "fenjue-check-index-refs-v1",
            "ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "targets": [str(t) for t in targets],
            "refs_checked": total_checked,
            "missing": all_missing,
            "all_pass": not all_missing,
        }, ensure_ascii=False, indent=2))
    else:
        for r in results:
            status = "✅" if not r["missing"] else "🔴"
            print(f"{status} {r['file']}: 路径引用 {r['checked']} 个"
                  + (f"，缺失 {len(r['missing'])}" if r["missing"] else ""))
        for m in all_missing[:15]:
            print(f"  🔴 MISS: {m}")
        print(f"总计: 路径引用 {total_checked} 个，缺失 {len(all_missing)} 个 → "
              + ("PASS 全部可循" if not all_missing else "FAIL"))

    return 1 if all_missing else 0


if __name__ == "__main__":
    sys.exit(main())
