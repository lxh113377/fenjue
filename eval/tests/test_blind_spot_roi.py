#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_blind_spot_roi.py — 盲区 ROI 计算模块单测（R198.9）"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from blind_spot_roi import (  # noqa: E402
    is_miss, is_whitelist, is_true_miss, cluster_true_miss,
    classify_tier, roi_score, roi_level, blind_spot_roi,
)


def mk(q, top1=None, direct=False, src='production'):
    """构造 trace 记录。"""
    return {'ts': '2026-08-16T00:00:00', 'src': src, 'q': q,
            'top1': top1, 'confidence': 'HIGH', 'direct': direct}


class TestPredicates:
    def test_is_miss(self):
        assert is_miss(mk('x', top1=None)) is True
        assert is_miss(mk('x', top1='NONE')) is True
        assert is_miss(mk('x', top1='A-get-memory')) is False

    def test_is_whitelist(self):
        assert is_whitelist(mk('x', top1=None, direct=True)) is True
        assert is_whitelist(mk('x', top1=None, direct=False)) is False

    def test_is_true_miss(self):
        assert is_true_miss(mk('x', top1=None, direct=False)) is True
        assert is_true_miss(mk('x', top1=None, direct=True)) is False


class TestCluster:
    def test_basic_cluster(self):
        rows = [mk('苹果和香蕉哪个热量高'), mk('苹果和香蕉哪个甜'), mk('显存不够用了')]
        cnt = dict(cluster_true_miss(rows, prefix_len=4))
        assert cnt['苹果和香'] == 2
        assert cnt['显存不够'] == 1

    def test_empty_query_skipped(self):
        rows = [mk(''), mk(None)]
        assert cluster_true_miss(rows) == []

    def test_whitelist_excluded_from_cluster(self):
        rows = [mk('苹果和香蕉', top1=None, direct=True), mk('苹果和香蕉')]
        cnt = dict(cluster_true_miss(rows, prefix_len=4))
        assert cnt['苹果和香'] == 1  # 白名单不计入真实盲区


class TestTier:
    def test_whitelist_hint_tier3(self):
        assert classify_tier('帮我起个', 5) == 3

    def test_direct_hint_tier1(self):
        assert classify_tier('显存不够', 5) == 1

    def test_default_tier2(self):
        assert classify_tier('未知前缀xx', 5) == 2


class TestRoi:
    def test_roi_score(self):
        assert roi_score(100, 1) == 100.0
        assert roi_score(100, 2) == 50.0
        assert roi_score(0, 1) == 0.0

    def test_roi_level(self):
        assert roi_level(100, 1) == 'HIGH'
        assert roi_level(100, 2) == 'MEDIUM'
        assert roi_level(5, 3) == 'LOW'
        assert roi_level(15, 2) == 'MEDIUM'


class TestIntegration:
    def test_full_report_smoke(self):
        rows = [mk('显存不够用了') for _ in range(35)] + \
               [mk('苹果和香蕉') for _ in range(20)] + \
               [mk('正常查询', top1='A-get-memory')] + \
               [mk('白名单项', top1=None, direct=True)]
        res = blind_spot_roi(rows, top_n=10, prefix_len=4)
        s = res['summary']
        assert s['total_traces'] == 57
        assert s['true_miss_cnt'] == 55
        assert s['whitelist_cnt'] == 1
        assert res['top_candidates'][0]['prefix'] == '显存不够'
        assert res['top_candidates'][0]['roi_level'] == 'HIGH'
        # JSON 可序列化
        json.dumps(res, ensure_ascii=False)

    def test_empty_input(self):
        res = blind_spot_roi([])
        assert res['summary']['total_traces'] == 0
        assert res['summary']['blind_ratio'] == 0.0
        assert res['top_candidates'] == []
        json.dumps(res)

    def test_all_whitelist_no_true_miss(self):
        rows = [mk('x', top1=None, direct=True) for _ in range(10)]
        res = blind_spot_roi(rows)
        assert res['summary']['true_miss_cnt'] == 0
        assert res['top_candidates'] == []


if __name__ == '__main__':
    # 极简自跑（无 pytest 依赖时）
    failures = 0
    for name, cls in sorted(globals().items()):
        if name.startswith('Test') and hasattr(cls, '__call__'):
            for mname in dir(cls):
                if mname.startswith('test'):
                    try:
                        getattr(cls(), mname)()
                        print('PASS %s.%s' % (name, mname))
                    except AssertionError as e:
                        failures += 1
                        print('FAIL %s.%s: %s' % (name, mname, e))
    print('\n%s' % ('ALL PASS' if failures == 0 else '%d FAILURES' % failures))
    sys.exit(1 if failures else 0)
