#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""part_size_lock.py —— 分卷件 4KB 上限的机器判据（对标轮十一 D-64 / D-69）。

为什么现在才有：R161/`truth_constants.fragment.max_bytes=4096` 只管受管根记忆文件，报告与
清单分卷件全靠自觉。实测（2026-09-25）109 个 `*.partN.md` 里 **8 个超限**（最大 14,791 B），
其中两个是本人轮七/轮八报告卷 —— 而我在报告里写过"逐卷 ≤4KB"。**没判据的约定必然漂移。**

D-69（同一轮实测踩到，已锁进测试）：普查命令若用 `git ls-files`（默认 `core.quotepath=true`），
非 ASCII 路径会输出成带引号的八进制转义串，行尾多一个 `"` ⇒ `grep -E '\\.part[0-9]+\\.md$'`
的 `$` 锚定全部失配，实测 109 个只数到 79 个、8 个超限只数到 3 个。**漏的恰好是中文命名的卷。**
所以本工具一律走 `git -c core.quotepath=off ls-files -z` 并以 NUL 分隔。

口径：
  S1 超限件数 > 基线件数 -> FAIL（只降不升）；
  S2 某登记件本次实测 > 其登记 size -> FAIL（单件棘轮，防"总数不变、内容变胖"）；
  S3 基线缺失/不可读 -> FAIL-FAST；分卷件面为空 -> FAIL-FAST（R247 无处可比不得判过）；
  S4 上限值不得写死，读 truth_constants.fragment.max_bytes（C7 无裸常量同族）。
退出码：0 合规 / 1 违规 / 2 判据面失效。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "eval", "part_size_baseline.json")
PART_RE = re.compile(r"\.part\d+\.md$")


def limit_bytes() -> int:
    sys.path.insert(0, os.path.join(ROOT, "eval"))
    import truth_constants as t
    return int(t.FRAGMENT_MAX_BYTES)


def list_parts(repo: str | None = None) -> list:
    """仓内 tracked 分卷件（NUL 分隔 + quotepath=off，中文路径不再漏报）。"""
    out = subprocess.run(
        ["git", "-c", "core.quotepath=off", "ls-files", "-z", "--", "*.md"],
        cwd=repo or ROOT, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(f"git ls-files 失败: {out.stderr.strip()[:120]}")
    names = [n for n in out.stdout.split("\0") if PART_RE.search(n)]
    return sorted(names)


def scan(repo: str | None = None) -> dict:
    base = repo or ROOT
    sizes = {}
    for rel in list_parts(base):
        p = os.path.join(base, rel)
        sizes[rel.replace(os.sep, "/")] = os.path.getsize(p) if os.path.isfile(p) else 0
    return sizes


def judge(sizes: dict, cap: int, baseline: dict | None = None) -> dict:
    if not sizes:
        return {"verdict": "FAIL-FAST", "reason": "分卷件面为空（判据面无从核验，R247）",
                "violations": []}
    over = {rel: n for rel, n in sizes.items() if n > cap}
    if baseline is None:
        return {"verdict": "FAIL-FAST",
                "reason": f"基线缺失：跑 --update-baseline 先登记存量 {len(over)} 个超限件",
                "violations": []}
    reg = baseline.get("over", {})
    violations = []
    if len(over) > len(reg):
        violations.append({"kind": "count", "now": len(over), "baseline": len(reg),
                           "new": sorted(set(over) - set(reg))})
    for rel, n in sorted(over.items()):
        if rel in reg and n > reg[rel]:
            violations.append({"kind": "size", "file": rel, "now": n, "baseline": reg[rel]})
    return {"verdict": "PASS" if not violations else "FAIL", "cap": cap,
            "scanned": len(sizes), "oversize": len(over),
            "grandfathered": len(reg), "violations": violations}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="分卷件 4KB 上限棘轮（D-64）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    ns = ap.parse_args(argv)
    try:
        cap = limit_bytes()
        sizes = scan()
    except (RuntimeError, OSError, ValueError) as e:
        print(f"[part-size] FAIL-FAST: {e}")
        return 2
    if ns.update_baseline:
        over = {rel: n for rel, n in sizes.items() if n > cap}
        data = {"cap": cap, "scanned": len(sizes), "measured": __import__("datetime")
                .date.today().isoformat(), "over": over}
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"[part-size] 基线已写：{len(over)} 个存量超限件登记在案（只降不升）")
        return 0
    baseline = json.load(open(BASELINE, encoding="utf-8")) if os.path.isfile(BASELINE) else None
    res = judge(sizes, cap, baseline)
    if ns.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        if res["verdict"] == "FAIL-FAST":
            print(f"[part-size] FAIL-FAST: {res['reason']}")
        else:
            print(f"[part-size] {res['verdict']}: 扫 {res['scanned']} 个分卷件 / 上限 {cap} B / "
                  f"超限 {res['oversize']}（基线登记 {res.get('grandfathered', 0)}）")
            for v in res["violations"][:6]:
                print("  " + (f"件数上升 {v['baseline']}->{v['now']} 新增 {v['new']}"
                              if v["kind"] == "count" else
                              f"{v['file']} {v['baseline']}->{v['now']} B（单件变胖）"))
    return {"PASS": 0, "FAIL": 1}.get(res["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
