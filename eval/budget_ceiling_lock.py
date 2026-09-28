#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""budget_ceiling_lock.py —— 子进程预算与调用方天花板的一致性锁（对标轮九 D-63）。

病灶（一手实测，2026-09-25）：`pytest` 每例天花板 120 s（pyproject `--timeout=120`），而生产码里
`subprocess(..., timeout=180/300/600/900)` 比比皆是；轮八两次提交被 `pre-commit FAIL: pytest` 拦下，
根因就是 `score_track200.run_json` 的 180 s 预算夹在「冷态 240 s」与「天花板 120 s」之间——
谁都没错，**只有关系是错的**。这类失效不会由任何单点测试抓到，只能靠对账判据。

口径：
  L1 预算 > 其所属调用链天花板 -> 越界（必须显式降到天花板下，或改走 integration 档）；
  L2 天花板本身取不到（pytest 配置缺失/无 addopts）-> 判红（R247：无处可比不得判过）；
  L3 扫描面为空 -> 判红（判据面被清空不等于通过）。
只读、stdlib-only、不依赖外盘 ⇒ CI 干净签出可跑（与 D-41/D-48 口径一致）。

用法：python eval/budget_ceiling_lock.py [--json] [--update-baseline]
退出码：0 全清 / 1 有越界 / 2 判据面失效
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ("eval", "scripts", "audit", "skill/tools")
BASELINE = os.path.join(ROOT, "eval", "budget_ceiling_baseline.json")
TIMEOUT_KW = re.compile(r"\btimeout\s*=\s*([0-9_]+)")


def pytest_ceiling(pyproject_path: str | None = None) -> int:
    """读 pytest 每例天花板（秒）。取不到即抛错，由调用方按 L2 判红。"""
    path = pyproject_path or os.path.join(ROOT, "pyproject.toml")
    txt = open(path, encoding="utf-8").read()
    m = re.search(r"--timeout=([0-9]+)", txt)
    if not m:
        raise ValueError("pyproject 无 --timeout，天花板不可得")
    return int(m.group(1))


def scan(scan_root: str | None = None) -> list:
    """返回 [(rel, line, budget_s)]。

    用 **AST** 取 `Call` 节点上的 `timeout=<整数字面量>`，而不是正则扫行——实测正则会把本文件
    文档串里的 `subprocess(timeout=…)` 叙述当成预算（首版 11 条越界里就混了 1 条假阳性）。
    变量型预算（`timeout=SOME_CONST`）不判定，交人工裁定并在基线外点名。
    """
    root = scan_root or ROOT
    hits = []
    for d in SCAN_DIRS:
        base = os.path.join(root, d)
        for dirpath, _dirs, files in os.walk(base):
            if "__pycache__" in dirpath or os.sep + "." in dirpath:
                continue
            for fn in files:
                if not fn.endswith(".py") or fn.startswith("test_"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    tree = ast.parse(open(p, encoding="utf-8").read())
                except (OSError, SyntaxError):
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    for kw in node.keywords:
                        if kw.arg != "timeout" or not isinstance(kw.value, ast.Constant):
                            continue
                        val = kw.value.value
                        if isinstance(val, int) and val > 0:
                            hits.append((os.path.relpath(p, root).replace(os.sep, "/"),
                                         node.lineno, val))
    return hits


def judge(hits: list, ceiling: int, baseline: dict | None = None) -> dict:
    """棘轮口径（D-104 修正）：**只认「预算档位 + 越界点数」两把尺，行号不参与判定**。

    一手实测：本轮 3 条"越界"（`scripts/run_gate.py:85` 1800s、`cross_writer:221` 900s、
    `stubs/stub_secret_scan.py:25` 300s）预算与基线记的**一字不差**，只是别人在它们上方插了几行
    注释 ⇒ `line <= max_line` 不成立 ⇒ 判红。用行号当棘轮坐标 = 任何一次上方插入都造出假越界，
    而假越界的代价是真越界永远排不进队（狼来了）。改为：
      豁免条件 = 该文件越界点数 <= 基线登记数 且 每处预算 <= 基线 max_budget；
      于是"抬预算"与"多加一个越界点"都判红，收口（减少点数/降档）永远放行 —— 只降不升。
    """
    if not hits:
        return {"verdict": "FAIL-FAST", "reason": "扫描面为空（R247 判据面失效）", "violations": []}
    base = (baseline or {}).get("grandfathered", {})
    per_file = {}
    for rel, line, budget in hits:
        if budget > ceiling:
            per_file.setdefault(rel, []).append((line, budget))
    violations = []
    for rel, sites in sorted(per_file.items()):
        rec = base.get(rel)
        allowed = (rec or {}).get("violations", (rec or {}).get("max_line") and 1 or 0)
        max_budget = (rec or {}).get("max_budget", 0)
        sites = sorted(sites, key=lambda x: -x[1])
        for idx, (line, budget) in enumerate(sites):
            if rec and idx < allowed and budget <= max_budget:
                continue      # 存量：登记过的档位与条数之内（行号只用于展示，不参与判定）
            violations.append({"file": rel, "line": line, "budget_s": budget,
                               "ceiling_s": ceiling,
                               "why": "预算超基线档位" if rec and idx < allowed else
                                      ("新增越界点（超出基线登记条数）" if rec else
                                       "该文件从未登记豁免")})
    return {"verdict": "PASS" if not violations else "FAIL", "scanned": len(hits),
            "ceiling_s": ceiling, "grandfathered_files": len(base), "violations": violations}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="子进程预算 vs 天花板一致性锁（D-63）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    ns = ap.parse_args(argv)
    try:
        ceiling = pytest_ceiling()
    except (OSError, ValueError) as e:
        print(f"[budget-lock] FAIL-FAST: {e}")
        return 2
    hits = scan()
    if ns.update_baseline:
        grand: dict = {}
        for rel, ln, b in hits:
            if b <= ceiling:
                continue
            cur = grand.get(rel) or {"max_line": 0, "max_budget": 0, "violations": 0}
            # 同文件多处越界必须取**真最大**（首版 last-wins 把 600 记成 300，反而让存量自判红）
            grand[rel] = {"max_line": max(ln, cur["max_line"]),
                          "max_budget": max(b, cur["max_budget"]),
                          "violations": cur["violations"] + 1}
        data = {"ceiling_s": ceiling, "scanned": len(hits), "grandfathered": grand}
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f"[budget-lock] 基线已写：{len(data['grandfathered'])} 处存量越界登记在案")
        return 0
    baseline = None
    if os.path.isfile(BASELINE):
        baseline = json.load(open(BASELINE, encoding="utf-8"))
    res = judge(hits, ceiling, baseline)
    if ns.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(f"[budget-lock] {res['verdict']}: 扫 {res.get('scanned', 0)} 处预算 / 天花板 "
              f"{ceiling}s / 越界 {len(res['violations'])}"
              + (f"（基线豁免 {res['grandfathered_files']} 文件）" if baseline else "（无基线）"))
        for v in res["violations"][:8]:
            print(f"  {v['file']}:{v['line']} budget={v['budget_s']}s > ceiling={v['ceiling_s']}s")
    if res["verdict"] == "FAIL-FAST":
        print("  " + res["reason"])
        return 2
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
