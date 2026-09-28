#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_scorecard_memory.py — 主线② score_memory 计分逻辑单测（R208 O-5）。

策略: mock run 按 5 次调用序列喂输出（fm/hit/dg/frag/snr）+ load_func_checks 可控。
fm 字符串需同时满足 D2-1（P0税）与 D2-6（D25）两个正则。
"""
import pytest

import scorecard_memory as mem

FM_OK = ('P0税: 10.0KB = 100 token = 5.0% of 128K\n'
         'D25 记忆覆盖: 3/4')


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


def test_score_memory_full_pass(monkeypatch):
    monkeypatch.setattr(mem, 'load_func_checks', lambda: {
        'coverage': {'hit_domains': 13, 'total_domains': 13},
        'version': {'ok': True},
    })
    outs = [
        FM_OK,                                    # ① fenjue_measure（P0/D25）
        '[WEAK] dogfood: 垃圾5/6混:dogfood[name_fragment]\n'
        '[WEAK] bogus: 垃圾2/6混:whatever',       # ② skill_hitrate_audit：1 良性+1 真实
        '{"passed": 3, "total": 3, "fallback_engaged": true}',  # ③ degrade
        '碎片率 = 0.1 个/skill',                  # ④ fragment_detector
        '内容信噪比: 5.5/6',                      # ⑤ content_snr
    ]
    monkeypatch.setattr(mem, 'run', make_runner(outs))

    res = mem.score_memory()
    assert res['line'] == '主线② 多agent统一记忆+路由'
    assert res['parts']['p0']['score'] == 8
    assert res['parts']['coverage']['score'] == 8
    assert res['parts']['triggers']['score'] == 6      # 8 - 1*2（name_fragment 不计）
    assert res['parts']['degrade']['score'] == 6
    assert res['parts']['version']['score'] == 6
    assert res['parts']['memcover']['score'] == 3
    assert res['parts']['kb']['score'] == 4
    assert res['parts']['content_snr']['score'] == 5.5
    assert res['total'] == pytest.approx(46.5)


def test_score_memory_script_missing_isolates_fm_dims(monkeypatch):
    """fenjue_measure 缺失 → p0 与 memcover 两个 fm 派生维隔离计分。"""
    monkeypatch.setattr(mem, 'load_func_checks', lambda: {
        'coverage': {'hit_domains': 0, 'total_domains': 13},
        'version': {'ok': False},
    })
    outs = [
        '__SCRIPT_MISSING__:fenjue_measure.py',       # ① fm → p0/memcover 隔离
        '[PASS] 无 WEAK',                              # ② hit
        '{"passed": 0, "total": 2, "fallback_engaged": false}',  # ③ dg（不 engaged → 0 分）
        '碎片率 = 0.6 个/skill',                      # ④ frag → kb=1
        '内容信噪比: 3.0/6',                          # ⑤ snr
    ]
    monkeypatch.setattr(mem, 'run', make_runner(outs))

    res = mem.score_memory()
    assert res['parts']['p0']['unavailable'] is True
    assert res['parts']['memcover']['unavailable'] is True
    assert res['parts']['degrade']['score'] == 0       # fallback 未 engaged
    assert res['parts']['kb']['score'] == 1
    assert res['parts']['content_snr']['score'] == 3.0