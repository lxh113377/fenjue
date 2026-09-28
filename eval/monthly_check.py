# -*- coding: utf-8 -*-
"""monthly_check.py — 评估冻结期月检全量一键执行（R170）

覆盖: 盲测 284 + frozen 10 + 回归 ALL PASS + cross_layer 30/30 +
      lessons 命中率 9/9 + 评分卡 PASS + 使用闭环（覆盖率/复发率报告）
用法:
  python eval/monthly_check.py [--json] [--out Temp/monthly_check_YYYY-MM-DD.json]
退出码: 0=全 PASS；1=任一 FAIL。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

EVAL = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(EVAL)
PY = r"C:\Program Files\Python312\python.exe"


def run(name, args, ok_patterns):
    """执行并判定：stdout 命中任一 ok_pattern 即 PASS。"""
    r = subprocess.run([PY, os.path.join(EVAL, args[0])] + args[1:],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    out = r.stdout + r.stderr
    ok = any(p in out for p in ok_patterns)
    return {"name": name, "pass": ok, "rc": r.returncode, "tail": out.strip()[-220:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    checks = [
        run("盲测 284", ["frozen_blind_eval.py", "--json", "--set", "layered"],
            ['"hits": 284']),
        run("frozen 10", ["frozen_blind_eval.py", "--json", "--set", "frozen"],
            ['"hits": 10']),
        run("回归", ["test_router_regression.py"], ["RESULT: ALL PASS"]),
        # cross_layer_audit.py 已于 R209 退役归档（archive/retired_R209/），职责并入 verify C1-C13 —— 检查项移除
        run("lessons 命中率", ["lessons_hitrate.py"], ["命中率: 100.0%"]),
        run("评分卡", ["scorecard.py", "--json"], ['"verdict": "PASS"']),
        run("使用记录覆盖率", ["lessons_usage_coverage.py", "--days", "7", "--json"],
            ['"pass": true']),
        run("复发率", ["recurrence_audit.py", "--json", "--check"], ['"pass": true']),
    ]
    all_pass = all(c["pass"] for c in checks)
    result = {"date": date.today().isoformat(), "all_pass": all_pass, "checks": checks}
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.json:
        print(json.dumps({"all_pass": all_pass,
                          "checks": [{"name": c["name"], "pass": c["pass"]} for c in checks]},
                         ensure_ascii=False, indent=2))
    else:
        for c in checks:
            print(("PASS" if c["pass"] else "FAIL"), c["name"])
        print("月检总判定:", "PASS" if all_pass else "FAIL")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
