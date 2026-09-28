#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""failure_cost_metric 单测（P2 #10 回归防护）。

覆盖「非 FAIL 状态」下的 UNACCEPTABLE 翻转边界：
  当 scorecard 其余维度均通过（非 FAIL 态），仅存在一条「高代价失败」
  （单维满分 max>=12 且实际得分低 → risk='高'）时，失败成本块必须给出
  verdict='UNACCEPTABLE'，使 scorecard 的翻转裁决（pass_ok=False）生效
  （scorecard.py:830  `if failure_cost['verdict'] == 'UNACCEPTABLE'`）。
同时验证该翻转不会被「中/低代价失败」误触发（不会误判）。

两条被测路径：
  - compute_failure_cost：scorecard 主路径直接调用（eval/scorecard.py:768）
  - apply_to_result：scorecard result 桥（eval/scorecard.py:859 回写
    result['failure_cost']，翻转依据同源）
"""
import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if EVAL_DIR not in sys.path:
    sys.path.insert(0, EVAL_DIR)

from failure_cost_metric import compute_failure_cost, apply_to_result


def _high_cost_only():
    """非 FAIL 态：除一条高代价失败外无其他破限维（单维满分 14>=12 → 高）。"""
    return [{
        'line': '主线②',
        'dim': 'D2-1 记忆准确',
        'score': 0,
        'max': 14,
    }]


def _low_cost_only():
    """非 FAIL 态：仅一条中/低代价失败（max=10<12 → 非高，即便得分全失也不翻转）。"""
    return [{
        'line': '主线③',
        'dim': 'D3-2 命中率',
        'score': 0,
        'max': 10,
    }]


def test_unacceptable_flip_in_non_fail_state():
    # ===== 路径1：compute_failure_cost（scorecard 主路径直接调用）=====
    block = compute_failure_cost(_high_cost_only())

    # 1) 高代价失败必须触发 UNACCEPTABLE 翻转（scorecard 据此把 pass_ok 翻为 False）
    assert block['verdict'] == 'UNACCEPTABLE'

    # 2) 高代价失败被精确识别（翻裁决依据不漏、不误）
    assert len(block['high_risk_failures']) == 1
    assert '主线②' in block['high_risk_failures'][0]
    assert 'D2-1 记忆准确' in block['high_risk_failures'][0]

    # 3) 量化正确：加权成本 = 损失14 × 高权重3.0 = 42.0；调整分 = 100 - 42 = 58.0
    assert block['weighted_cost'] == 42.0
    assert block['adjusted_score'] == 58.0
    assert block['n_fail'] == 1

    # 4) 不会误判：同一非 FAIL 态下，仅「中/低代价失败」不得触发翻转
    block_low = compute_failure_cost(_low_cost_only())
    assert block_low['verdict'] != 'UNACCEPTABLE'
    assert block_low['verdict'] == 'ACCEPTABLE'
    assert block_low['high_risk_failures'] == []

    # ===== 路径2：apply_to_result（scorecard result 桥，回写 failure_cost）=====
    result = {
        'total_line': 150,
        'dim_fails_risk': _high_cost_only(),
    }
    fc = apply_to_result(result)
    # 桥必须回写且与 compute_failure_cost 同源裁决
    assert result.get('failure_cost') is fc
    assert fc['verdict'] == 'UNACCEPTABLE'
    assert fc['high_risk_failures'] and '主线②' in fc['high_risk_failures'][0]


if __name__ == '__main__':
    test_unacceptable_flip_in_non_fail_state()
    print('OK: test_unacceptable_flip_in_non_fail_state')
