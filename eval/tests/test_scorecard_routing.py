#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_scorecard_routing.py — 主线③ score_routing 计分逻辑单测（R208 O-5）。

策略: mock run 按 5 次调用序列喂输出（out/fbe/fbe_frozen/fm/neg）。
out 需同时满足直连层/全管线/LLM 决策率三个正则。
"""
import pytest

import scorecard_routing as rt

OUT_OK = ('直连映射层 Top-1: 90.0%\n'
          '全管线 Top-1: 70.0%\n'
          'LLM 决策推荐率: 3.0%')
FBE_OK = '{"score": 90.0, "n": 40, "max_achievable": 95.0, "bge_status": "engaged", "results": []}'
FBE_FROZEN_OK = '{"score": 85.0, "n": 30}'
FM_OK = 'D27 追问/经验: 4/6'
NEG_OK = '健康率: 100.0%'


def make_runner(outs):
    it = iter(outs)
    calls = []

    def fab(*args, **kwargs):
        calls.append(args)
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(f'run 被调用次数超过提供的输出数: {len(outs)}')

    fab.calls = calls
    return fab


def test_score_routing_full_pass(monkeypatch):
    outs = [OUT_OK, FBE_OK, FBE_FROZEN_OK, FM_OK, NEG_OK]
    monkeypatch.setattr(rt, 'run', make_runner(outs))

    res = rt.score_routing()
    assert res['line'] == '主线③ skill命中率优化'
    assert res['parts']['direct']['score'] == pytest.approx(10.8)   # 90% * 12
    assert res['parts']['full']['score'] == pytest.approx(9.8)      # 70% * 14
    assert res['parts']['blind']['score'] == pytest.approx(9.0)     # 90% * 10
    assert res['parts']['blind']['cap'] == pytest.approx(9.5)       # 95% 可达上限
    assert res['parts']['llm']['score'] == 4                        # LLM 率 3% ≤5 → 满
    assert res['parts']['trace']['score'] == 4                      # D27=4/6
    assert res['parts']['negtag']['score'] == 4                     # 健康率 100%
    assert res['total'] == pytest.approx(41.6)


def test_score_routing_script_missing_isolates_eval_dims(monkeypatch):
    """unified_router --eval 缺失 → direct/full/llm 三维隔离计分（熟练 out 派生）。"""
    outs = [
        '__SCRIPT_MISSING__:unified_router.py',
        FBE_OK, FBE_FROZEN_OK, FM_OK, NEG_OK,
    ]
    monkeypatch.setattr(rt, 'run', make_runner(outs))

    res = rt.score_routing()
    assert res['parts']['direct']['unavailable'] is True
    assert res['parts']['full']['unavailable'] is True
    assert res['parts']['llm']['unavailable'] is True
    # blind/negtag 仍正常计分（独立证据源不受 out 缺失影响）
    assert res['parts']['blind']['score'] == pytest.approx(9.0)
    assert res['parts']['negtag']['score'] == 4


def test_score_routing_bge_degraded_isolates_blind(monkeypatch):
    """BGE 降级为 TF-IDF → 盲测维隔离（分数不可作为 BGE 命中率）。"""
    fbe_degraded = ('{"score": 90.0, "n": 40, "max_achievable": 95.0,'
                    ' "bge_status": "degraded_to_tfidf", "results": []}')
    outs = [OUT_OK, fbe_degraded, FBE_FROZEN_OK, FM_OK, NEG_OK]
    monkeypatch.setattr(rt, 'run', make_runner(outs))

    res = rt.score_routing()
    assert res['parts']['blind']['unavailable'] is True
    assert res['parts']['blind']['score'] == 0
    assert '降级为 TF-IDF' in res['parts']['blind']['detail']