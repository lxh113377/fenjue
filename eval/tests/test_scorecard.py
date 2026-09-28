#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scorecard 编排层冒烟（R209-2③ 补测簇：392 stmts 4.5%）。

覆盖: collect_red_team 聚合口径——confirmed 严重度分档 / cap 满分护栏 /
blindspots 与 wrong 判定 / 空输入全零。计分主体（scorecard_*）不在本冒烟范围。
"""
import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import scorecard as sc  # noqa: E402


def _dim(score, mx, cap=None, detail='d', evidence='e'):
    d = {'score': score, 'max': mx, 'detail': detail, 'evidence': evidence}
    if cap is not None:
        d['cap'] = cap
    return d


def test_collect_red_team_confirmed_and_severity():
    sync = {'line': '主线①', 'parts': {'a': _dim(5, 10)}}     # 5<10 → 中 (8<=10<12)
    mem = {'line': '主线②', 'parts': {'b': _dim(20, 20)}}     # 满分 → 不进
    routing = {'line': '主线③', 'parts': {'c': _dim(0, 15)}}  # 0<15 → 高 (15>=12)
    out = sc.collect_red_team(sync, mem, routing)
    assert out['counts']['confirmed'] == 2
    dims = {c['dim']: c for c in out['confirmed']}
    assert dims['主线①/a']['severity'] == '中'
    assert dims['主线③/c']['severity'] == '高'


def test_collect_red_team_cap_full_score_not_confirmed():
    # score == cap（但 cap < max）→ 不算扣分（R165 U1: 基准是可达上限）
    sync = {'line': '主线①', 'parts': {'a': _dim(8, 10, cap=8)}}
    mem = {'line': '主线②', 'parts': {}}
    routing = {'line': '主线③', 'parts': {}}
    out = sc.collect_red_team(sync, mem, routing)
    assert out['counts']['confirmed'] == 0


def test_collect_red_team_blindspots_and_wrong():
    sync = {'line': '主线①', 'parts': {}}
    mem = {'line': '主线②', 'parts': {}}
    routing = {'line': '主线③', 'parts': {},
               'blind_findings': [
                   {'judge': 'blindspot', 'query': 'q1', 'router_top1': 'some-skill'},
                   {'judge': 'blindspot', 'query': 'q2', 'router_top1': 'NONE'},  # 路由正确返回 NONE → 非盲区
                   {'judge': 'wrong', 'query': 'q3', 'expected': 'x', 'router_top1': 'y'},
               ]}
    out = sc.collect_red_team(sync, mem, routing)
    assert out['counts']['blindspots'] == 1
    assert out['counts']['confirmed'] == 1                     # wrong 进 confirmed
    assert out['blindspots'][0]['query'] == 'q1'
    assert out['confirmed'][0]['dim'] == '主线③/盲测(wrong)'


def test_collect_red_team_empty_all_zero(tmp_path, monkeypatch):
    # 隔离真实 codex_audit_scores.json（只读补充源），确保确定性全零
    monkeypatch.setattr(sc, 'EVAL_DIR', str(tmp_path))
    empty = {'line': 'x', 'parts': {}}
    out = sc.collect_red_team(empty, empty, empty)
    assert out['counts'] == {'confirmed': 0, 'false_positive': 0, 'blindspots': 0}
