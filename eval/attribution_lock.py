#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""attribution_lock.py —— 「失败的闸门必须指得出自己的全文输出」（对标轮十五 D-81）。

一手教训：`eval/hooks/pre-commit` 只 `tail -25`，而闸链在 pytest 之后还要打印自己的汇总，
`FAILED ...` 摘要刚好被挤出窗口 ⇒ 连续三轮出现"钩子说红、却说不出红在哪个用例"，我做了
3×20 分钟的上下文对照实验（直跑绿 / 提交红），而真凶一直在它自己写的 `/tmp/fenjue_pch.log`
里。归因成本 = 一次 `grep -aE '^FAILED' <log>`。

所以规则不能写成"记得先看 log"，要写成产物契约：每条 `ci-results/<slug>.json` 只要有
`status=fail`，就必须带**存在的** `log` 路径字段。判据：
  A1 任一 fail 记录缺 log 字段 / log 指向的文件不存在 → FAIL（点名 slug）
  A2 记录面为空（没有任何 ci-results/*.json）→ FAIL（说明闸门没落盘＝接线断了，不是"全绿"）
  A3 全 pass 且每条都有 log → PASS
退出码 0 / 1 / 2（2 = 目录不可读）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def judge(records: list) -> dict:
    """records = [(slug, parsed_or_None, parse_err)]。"""
    if not records:
        return {"verdict": "FAIL", "reason": "没有任何闸门记录：闸门没落盘＝接线断了，不等于全绿（A2）",
                "checked": 0, "failed": 0}
    missing, checked, failed = [], 0, 0
    for slug, rec, err in records:
        if err is not None:
            missing.append(f"{slug}(记录不可解析:{err})")
            continue
        checked += 1
        if rec.get("status") == "fail":
            failed += 1
            log = rec.get("log")
            if not log:
                missing.append(f"{slug}(无 log 字段)")
            elif not os.path.isfile(log):
                missing.append(f"{slug}(log 不存在:{log})")
    return {"verdict": "PASS" if not missing else "FAIL", "checked": checked,
            "failed_gates": failed, "violations": missing,
            "reason": f"{checked} 条记录 / {failed} 条判红且全部可归因" if not missing
                      else "失败闸门缺可指向的全文输出"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="闸门归因锁（D-81）")
    ap.add_argument("--results-dir", default=os.path.join(ROOT, "ci-results"))
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    if not os.path.isdir(ns.results_dir):
        print(f"[attribution] FAIL: 结果目录不存在 {ns.results_dir}（A2）")
        return 1
    records = []
    try:
        paths = sorted(glob.glob(os.path.join(ns.results_dir, "*.json")))
    except OSError as e:
        print(f"[attribution] FAIL-FAST: 目录不可读 {e}")
        return 2
    for p in paths:
        slug = os.path.splitext(os.path.basename(p))[0]
        try:
            records.append((slug, json.loads(open(p, encoding="utf-8").read()), None))
        except (OSError, ValueError) as e:
            records.append((slug, None, str(e)[:60]))
    res = judge(records)
    print(json.dumps(res, ensure_ascii=False) if ns.json else
          f"[attribution] {res['verdict']}: {res['reason']}"
          + "".join(f"\n  - {v}" for v in res.get("violations", [])[:8]))
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
