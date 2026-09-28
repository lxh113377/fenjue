#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style_ratchet.py — 风格债棘轮 lint（R210-05，P2 池轮转）。

原理（与 path_hygiene.py 同款棘轮模式，2026-09-04 固化）：
  1. --update-baseline: 以当前 ruff 存量生成基线（存量放行，一次性认可）。
  2. 默认检查: 重扫对比基线——
     - 新文件出现违规 → FAIL
     - 同文件同规则码计数 > 基线 → FAIL（双层键控防「总数不变、结构反弹」）
     - 计数下降 → 放行并提示可再收紧基线（棘轮只进不退）
  3. 行级豁免: 不适用（ruff 原生支持 # noqa），无需自造标记。
  4. ruff 不可用（依赖缺失/非 pip 环境）→ skip 放行并打印原因（与
     workflow_gate git skip 同款降级风格，不误伤只读环境）。

范围: eval/ scripts/ audit/ feedback/（与 R209 六维分析口径一致；
publish/_trash/archive/_temp 由 pyproject.toml [tool.ruff] exclude 覆盖）。
基线: eval/style_ratchet_baseline.json（{rel_path: {rule_code: count}}）。

用法:
  python eval/style_ratchet.py                    # 棘轮检查（门禁用）
  python eval/style_ratchet.py --update-baseline  # 重建基线（存量认可）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(EVAL_DIR)
BASELINE_PATH = os.path.join(EVAL_DIR, "style_ratchet_baseline.json")
SCAN_DIRS = ("eval", "scripts", "audit", "feedback")


def _run_ruff() -> tuple[dict[str, dict[str, int]] | None, str]:
    """跑 ruff 并按 {rel_path: {code: count}} 聚合。ruff 不可用 → (None, 原因)。"""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "ruff", "check", *SCAN_DIRS,
             "--output-format", "json", "--quiet"],
            cwd=REPO_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120)
    except Exception as e:  # noqa: BLE001 — 环境级降级（无 ruff/超时）
        return None, f"ruff 子进程异常: {e}"
    # ruff 有违规时 returncode=1 且 stdout=JSON；不可用时 stdout 非法 JSON
    try:
        findings = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return None, f"ruff 不可用（rc={r.returncode}）: {r.stderr.strip()[:160]}"
    if not isinstance(findings, list):
        return None, "ruff 输出格式异常"
    hits: dict[str, dict[str, int]] = {}
    for f in findings:
        rel = os.path.relpath(f.get("filename", ""), REPO_ROOT).replace("\\", "/")
        code = f.get("code") or "UNKNOWN"
        hits.setdefault(rel, {}).setdefault(code, 0)
        hits[rel][code] += 1
    return hits, ""


def _load_baseline() -> dict[str, dict[str, int]]:
    return json.loads(Path(BASELINE_PATH).read_text(encoding="utf-8"))


def update_baseline() -> int:
    hits, reason = _run_ruff()
    if hits is None:
        print(f"[style-ratchet] SKIP: {reason}")
        return 0
    Path(BASELINE_PATH).write_text(
        json.dumps(hits, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    total = sum(sum(c.values()) for c in hits.values())
    print(f"[style-ratchet] 基线已更新: {len(hits)} 文件 / {total} 处（存量放行，棘轮只进不退）")
    return 0


def check() -> int:
    current, reason = _run_ruff()
    if current is None:
        print(f"[style-ratchet] SKIP: {reason}")
        return 0
    try:
        baseline = _load_baseline()
    except Exception as e:  # noqa: BLE001
        print(f"[style-ratchet] FAIL: 基线不可读（{e}）——先跑 --update-baseline 生成")
        return 2

    violations: list[str] = []
    improved: list[str] = []
    for rel, codes in current.items():
        base = baseline.get(rel)
        if base is None:
            total = sum(codes.values())
            violations.append(f"{rel}: 新文件违规 {total} 处")
            continue
        for code, n in codes.items():
            b = base.get(code, 0)
            if n > b:
                violations.append(f"{rel}: {code} {n} > 基线 {b}（新增 {n - b}）")
            elif n < b:
                improved.append(f"{rel}: {code} {n} < 基线 {b}")
    for rel in baseline:
        if rel not in current and baseline[rel]:
            improved.append(f"{rel}: 已清零")

    if improved:
        print(f"[style-ratchet] 存量改善 {len(improved)} 处（可跑 --update-baseline 收紧基线）")
    if violations:
        print(f"[style-ratchet] FAIL: {len(violations)} 条新增风格违规（棘轮拦截）")
        for v in violations[:15]:
            print(f"  - {v}")
        return 1
    total = sum(sum(c.values()) for c in current.values())
    print(f"[style-ratchet] PASS: 现存 {total} 处 ≤ 基线，棘轮未回退")
    return 0


def main() -> int:
    if "--update-baseline" in sys.argv:
        return update_baseline()
    return check()


if __name__ == "__main__":
    sys.exit(main())
