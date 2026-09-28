# -*- coding: utf-8 -*-
"""P0-2 会话级技能触发验收（离线预筛 + 基线棘轮）。

对标 Superpowers `AGENTS.md` 的 acceptance test（一句固定 prompt 必须自动触发指定技能）。
本仓的「路由命中率」只覆盖离线 query->skill 映射；本脚本补上**固定口语 prompt 集合**的
可复跑预筛，并输出人工会话验证清单（真实会话层验证需在新会话中原样输入 prompt）。

用法::

    python eval/skill_trigger_acceptance.py            # 预筛（对照基线）
    python eval/skill_trigger_acceptance.py --update   # 采集/收紧基线
    python eval/skill_trigger_acceptance.py --json     # 机器可读
    python eval/skill_trigger_acceptance.py --list     # 只出人工验证清单

判据：
  · 每条用例的 router top-1（或 top-3 之一）命中 expect_skills -> pass
  · 基线棘轮：总命中数 < 基线 -> FAIL（回退）；> 基线 -> PASS（提示可 --update 收紧）
  · 基线缺失 / 用例集为空 -> FAIL（R247：无处可比不得判过）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
CASES_FILE = EVAL_DIR / "skill_trigger_acceptance.json"
BASELINE_FILE = EVAL_DIR / "skill_trigger_acceptance_baseline.json"


def load_cases(path=None):
    p = Path(path) if path else CASES_FILE
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("cases") or []


def load_baseline(path=None):
    p = Path(path) if path else BASELINE_FILE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_baseline(results, path=None):
    p = Path(path) if path else BASELINE_FILE
    passed = [r["id"] for r in results if r["pass"]]
    payload = {
        "schema": "fenjue-skill-trigger-acceptance-baseline-v1",
        "generated": datetime.now().strftime("%Y-%m-%d"),
        "note": "会话级技能触发验收基线（棘轮）：命中数只许升不许降；改进后可 --update 收紧。",
        "total": len(results),
        "passed": len(passed),
        "failed_ids": [r["id"] for r in results if not r["pass"]],
        "top1_hits": [r["id"] for r in results if r.get("top1_hit")],
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def run_cases(cases, top_k=3):
    """跑全部用例；返回 [{id, prompt, expect, got, top1_hit, pass, error}]。"""
    sys.path.insert(0, str(EVAL_DIR))
    results = []
    try:
        import unified_router as ur
    except Exception as e:  # noqa: BLE001
        for c in cases:
            results.append({"id": c["id"], "prompt": c["prompt"], "expect": c["expect_skills"],
                            "got": [], "top1_hit": False, "pass": False,
                            "error": "unified_router 不可用: {0}".format(e)})
        return results
    for c in cases:
        expect = set(c.get("expect_skills") or [])
        got, top1_hit, err = [], False, ""
        try:
            res = ur.route(c["prompt"])
            if isinstance(res, dict):
                cands = res.get("skills") or res.get("candidates") or []
                names = []
                for item in cands:
                    if isinstance(item, dict):
                        names.append(item.get("name") or item.get("skill") or "")
                    elif isinstance(item, str):
                        names.append(item)
                if not names:
                    n1 = res.get("top1") or res.get("top_1") or ""
                    names = [n1] if n1 and n1 != "NONE" else []
                got = names[:top_k]
                top1_hit = bool(got) and got[0] in expect
            else:
                err = "route() 返回类型异常: {0}".format(type(res).__name__)
        except Exception as e:  # noqa: BLE001
            err = "route() 异常: {0}".format(e)
        results.append({
            "id": c["id"], "prompt": c["prompt"], "expect": sorted(expect),
            "got": got, "top1_hit": top1_hit,
            "pass": bool(set(got) & expect), "error": err,
        })
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="会话级技能触发验收（P0-2）")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true", help="只输出人工会话验证清单")
    ap.add_argument("--cases", default=None)
    ap.add_argument("--baseline", default=None)
    args = ap.parse_args(argv)

    cases = load_cases(args.cases)
    if not cases:
        print("🔴 用例集为空（判据面失效，R247）")
        return 1

    if args.list:
        print("人工会话验证清单（请在新会话中原样输入 prompt，核对首个动作）")
        print("=" * 72)
        for c in cases:
            print("\n[{0}] {1}".format(c["id"], c["prompt"]))
            print("     期望技能（任一）: {0}".format(" / ".join(c["expect_skills"])))
            print("     期望首个动作    : {0}".format(c["expect_first_action"]))
        return 0

    results = run_cases(cases)
    passed = [r for r in results if r["pass"]]
    top1 = [r for r in results if r["top1_hit"]]

    if args.update:
        p = write_baseline(results, args.baseline)
        print("✅ 基线已更新: {0}（{1}/{2} 命中，top1 {3}）".format(
            p, len(passed), len(results), len(top1)))
        return 0

    base = load_baseline(args.baseline)
    failures = []
    if base is None:
        failures.append("基线缺失（先跑 --update 采集）")
    elif len(passed) < base.get("passed", 0):
        failures.append("命中数回退 {0} -> {1}（基线 {2}）".format(
            base.get("passed"), len(passed), base.get("failed_ids")))
    elif len(passed) > base.get("passed", 0):
        failures = []  # 上升不算失败，仅提示

    if args.json:
        print(json.dumps({
            "schema": "fenjue-skill-trigger-acceptance-result-v1",
            "ok": not failures, "total": len(results),
            "passed": len(passed), "top1_hits": len(top1),
            "baseline": (base or {}).get("passed"),
            "failures": failures,
            "results": [{"id": r["id"], "pass": r["pass"], "top1": r["top1_hit"],
                         "got": r["got"], "expect": r["expect"], "err": r["error"]}
                        for r in results],
        }, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    print("🎯 会话级技能触发验收（离线预筛）")
    print("   命中 {0}/{1}（top-1 命中 {2}）｜基线 {3}".format(
        len(passed), len(results), len(top1), (base or {}).get("passed", "（无）")))
    print("   " + "-" * 68)
    for r in results:
        mark = "✅" if r["pass"] else "❌"
        t1 = " [top1]" if r["top1_hit"] else ""
        print("   {0} {1}  expect={2}  got={3}{4}{5}".format(
            mark, r["id"], "/".join(r["expect"]), r["got"] or "-", t1,
            "  err=" + r["error"] if r["error"] else ""))
    print("   " + "-" * 68)
    if failures:
        print("🔴 [GATE:trigger-acceptance-fail] " + "；".join(failures))
        return 1
    print("✅ [GATE:trigger-acceptance-pass] 无回退（人工会话验证见 --list）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
