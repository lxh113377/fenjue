#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
failure_cost_metric.py — 失败成本度量（P2 缺口 #10 修复）
=====================================================================
问题：原评分卡只看「成功率 / 总分」，不区分失败的代价。
      一个 agent 99% 成功、但 1% 的失败会删库 → 这不能用。
本模块把「失败成本」显式量化，并能在出现高代价（高权重/高影响）失败时
把整体裁决翻转为 UNACCEPTABLE，使指标不再「只看成功率」。

设计：
  - 风险权重与 scorecard 单维风险判定同源（max>=12 高 / >=8 中 / 否则 低）
  - 加权成本 = Σ(维度损失 × 风险权重)
  - 失败成本调整分 = 100 − 加权成本（封顶 0）
  - 任一高代价维度失败 → verdict=UNACCEPTABLE（可翻转整体裁决）

不修改 scorecard 既有 20 维 schema，仅作为附加裁决块接入。
"""
from typing import List, Dict, Any

# 风险权重：高代价失败代价远高于低代价
RISK_WEIGHT = {'高': 3.0, '中': 1.5, '低': 1.0}


def risk_of(dim_max: float) -> str:
    """与 scorecard 单维风险判定同源：max>=12 高 / >=8 中 / 否则 低。"""
    if dim_max >= 12:
        return '高'
    if dim_max >= 8:
        return '中'
    return '低'


def compute_failure_cost(dim_fails_risk: List[Dict[str, Any]], total_max: float = 150.0) -> Dict[str, Any]:
    """dim_fails_risk: scorecard 产出的失败维度清单（每项含 score/max/line/dim）。
    返回失败成本块（纯函数，可单测）。
    """
    dim_fails_risk = dim_fails_risk or []
    n_fail = len(dim_fails_risk)
    weighted = 0.0
    high_risk_failures = []
    for d in dim_fails_risk:
        m = float(d.get('max', 0) or 0)
        s = float(d.get('score', 0) or 0)
        loss = max(0.0, m - s)
        r = risk_of(m)
        weighted += loss * RISK_WEIGHT[r]
        if r == '高':
            high_risk_failures.append(
                f"{d.get('line', '?')}/{d.get('dim', '?')} (损失 {loss:.1f}/{m:.0f})")
    adjusted = max(0.0, round(100.0 - weighted, 1))
    if high_risk_failures:
        verdict = 'UNACCEPTABLE'
    elif n_fail:
        verdict = 'ACCEPTABLE'
    else:
        verdict = 'PERFECT'
    return {
        'n_fail': n_fail,
        'weighted_cost': round(weighted, 2),
        'adjusted_score': adjusted,
        'high_risk_failures': high_risk_failures,
        'verdict': verdict,
        'detail': (
            '高代价维度失败 → 整体不可接受' if verdict == 'UNACCEPTABLE'
            else f'失败 {n_fail} 项，加权成本 {round(weighted, 1)}（满分100 调整分 {adjusted}）'),
    }


def apply_to_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """从 scorecard result 取 dim_fails_risk 计算失败成本并回写 result['failure_cost']。
    返回失败成本块（翻裁决的动作由调用方在 compute_verdict 之后执行，保持局部可控）。
    """
    dim_fails_risk = result.get('dim_fails_risk', []) or []
    fc = compute_failure_cost(dim_fails_risk, total_max=float(result.get('total_line', 150) or 150))
    result['failure_cost'] = fc
    return fc


if __name__ == '__main__':
    # 自测：模拟一个高代价失败 → 应判 UNACCEPTABLE
    demo = [
        {'line': '主线②', 'dim': 'D2-1 记忆准确', 'score': 0, 'max': 14},
        {'line': '主线③', 'dim': 'D3-2 命中率', 'score': 30, 'max': 10},
    ]
    import json
    print(json.dumps(compute_failure_cost(demo), ensure_ascii=False, indent=2))
