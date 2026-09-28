#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""external_write_audit.py — 门禁 2c 外部写入 AST 识别器 CLI/自测壳（R208 O-4 拆分）。

引擎迁至同目录 ewa_taint.py（常量/AST 污染分析/analyze_* 主流程）。本文件保留:
  自测样本载入 / SELFTEST_CASES / selftest / main CLI 入口，
  并从 ewa_taint re-export 引擎符号（Finding / analyze_source / analyze_paths）——
  adversarial_test.py 的 `import external_write_audit as ewa` 无感兼容。
拆分保持行为等价（门禁 2c 一直生效）。

样本数据（P0-11，2026-09-24）：SELFTEST_CASES 的 41 条样本源码迁至
``scripts/ewa_selftest_cases.json``（数据/逻辑分离）。样本正文含
open/exec/subprocess 等模式文本，留在 .py 内会被 Mimosa 静态扫描按文本级命中
（实证：probe 字符串字面量被 flag）；JSON 非源码扫描面，等价载入。

用法:
  python scripts/external_write_audit.py --selftest   # 跑自测
  git ls-files *.py | python scripts/external_write_audit.py   # 扫描
"""
from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ewa_taint import Finding, analyze_paths, analyze_source  # noqa: E402,F401  re-export 兼容

_CASES_PATH = Path(__file__).with_name("ewa_selftest_cases.json")


def _load_selftest_cases() -> tuple[tuple[str, str, int, int], ...]:
    """从 JSON 数据文件载入自测样本（名称, 源码, 期望判红数, 期望豁免数）。"""
    with _CASES_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return tuple(
        (case["name"], case["source"], case["want_hit"], case["want_exempt"])
        for case in payload["cases"]
    )


# (名称, 源码, 期望判红处数, 期望豁免处数) —— 载入自 ewa_selftest_cases.json
SELFTEST_CASES: tuple[tuple[str, str, int, int], ...] = _load_selftest_cases()


def selftest() -> int:
    """跑检查器自身的正反用例。

    Returns:
        0 表示全部通过，1 表示存在失败（调用方据此判红）。
    """
    failures: list[str] = []
    for name, source, want_hit, want_exempt in SELFTEST_CASES:
        findings = analyze_source(source, f"<selftest:{name}>")
        got_hit = sum(1 for f in findings if f.status == "hit")
        got_exempt = sum(1 for f in findings if f.status in ("guard", "comment"))
        if got_hit != want_hit or got_exempt != want_exempt:
            detail = "; ".join(f"{f.line}:{f.status}:{f.text}" for f in findings) or "<无记录>"
            failures.append(
                f"  - {name}: 期望 判红={want_hit} 豁免={want_exempt} "
                f"实际 判红={got_hit} 豁免={got_exempt} [{detail}]"
            )

    if failures:
        print("门禁自测未通过（检查器本身失效）:")
        for line in failures:
            print(line)
        return 1
    print(f"外部写入检查器自测通过（{len(SELFTEST_CASES)} 条断言）")
    return 0


def main(argv: Sequence[str]) -> int:
    """CLI 入口。

    用法：
      ``python scripts/external_write_audit.py --selftest``  跑自测
      ``git ls-files '*.py' | python scripts/external_write_audit.py``  扫描

    Returns:
        0 无命中，1 有命中或自测失败。
    """
    if "--selftest" in argv:
        return selftest()

    try:
        raw = sys.stdin.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"__SUMMARY__ 读取待扫描列表失败（fail-closed 判红）: {exc}")
        return 1

    paths = [line for line in raw.splitlines() if line.strip()]
    findings = analyze_paths(paths)

    hits = [f for f in findings if f.status == "hit"]
    exempts = [f for f in findings if f.status in ("guard", "comment")]

    for f in exempts:
        tag = "守卫" if f.status == "guard" else f"豁免:{f.reason}"
        # 警示前缀交给调用方 shell 添加，避免 Windows cp936 控制台编码炸掉
        print(f"__EXEMPT__ {f.path}:{f.line}:{f.text} [{tag}]")

    for f in hits:
        print(f"{f.path}:{f.line}:{f.text}")

    if hits:
        files = len({f.path for f in hits})
        print(f"__SUMMARY__ 命中 {len(hits)} 处，涉及 {files} 个文件")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
