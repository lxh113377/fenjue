#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_historical_regression.py — 历史 FAIL/WEAK 回归门禁（R193 重建）

背景：R192 声称已建 historical_regression_queries.json + 本 runner，但源文件
在清场中丢失（仅剩 __pycache__ pyc）——"日志声明 ≠ 文件存在"实证（R193 重建）。
本版本全部 query 走 DIRECT_MAP 直连层（零 ML 依赖），CI 无 BGE/TF-IDF 也可全量跑；
任一 FAIL 退出码 1（历史缺陷复发 = 提交/CI 被拒）。

用法: python eval/test_historical_regression.py
"""
import json
import os
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EVAL_DIR)
os.environ["FENJUE_ROUTE_TRACE"] = "0"


def main() -> int:
    with open(os.path.join(EVAL_DIR, "historical_regression_queries.json"), encoding="utf-8") as f:
        cases = json.load(f)
    from direct_layer import direct_route

    failed = []
    for case in cases:
        q = case["query"]
        exp = case["expected_skill"]
        got = direct_route(q)
        ok = (got in (None, "NONE")) if exp == "NONE" else got == exp
        if not ok:
            failed.append((q, exp, got))
    if failed:
        print(f"历史回归 FAIL: {len(failed)}/{len(cases)}")
        for q, exp, got in failed:
            print(f"  ✗ {q} 期望={exp} 实得={got}")
        return 1
    print(f"历史回归 PASS: {len(cases)}/{len(cases)}（直连层，零 ML 依赖）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
