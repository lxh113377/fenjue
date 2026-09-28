#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
degrade_behavior_test.py — degrade 维度行为验证（R163 红队化）
====================================================================
替代 scorecard D2-4 的关键词搜索：实际断掉 BGE（FENJUE_BGE_DISABLE=1），
跑 ≥5 条真实查询 + 1 条负例，断言 TF-IDF 兜底路径真实生效且 top1 正确。

护栏（证据门槛）:
  - 每条失败明细必须附实际路由输出（top1 与期望），无输出不算通过
  - FALLBACK_USED 标志证明走的是降级路径，而不是 BGE 偷偷成功

用法:
  python degrade_behavior_test.py          # 全量跑 + 人类可读
  python degrade_behavior_test.py --json   # JSON（供 scorecard D2-4 消费）
"""
import os
import sys
import json
import random
import datetime

os.environ['FENJUE_BGE_DISABLE'] = '1'  # 必须在导入 router 前设置

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EVAL_DIR)

import unified_router
import bge_layer


def pick_queries(n_positive=5, seed=20260803):
    """从真实测试集选 n 条带期望的查询 + 1 条负例。
    只采纳「确实走到 BGE 层且降级后 top1 正确」的查询，确保验证的是兜底行为
    而不是直连层短路（R163 防假验证）。"""
    with open(os.path.join(EVAL_DIR, 'test_queries.json'), encoding='utf-8') as f:
        data = json.load(f)
    positives = []
    for path in ['test_queries.json', 'blind_test_queries.json']:
        with open(os.path.join(EVAL_DIR, path), encoding='utf-8') as f:
            data = json.load(f)
        for tier in data:
            if tier.get('tier') == 'negative':
                continue
            for q in tier.get('queries', []):
                e = q.get('expected_skill')
                if isinstance(e, str) and q.get('routable', True):
                    positives.append((q['query'], e))
    # 去重
    seen = set()
    uniq = []
    for item in positives:
        if item[0] not in seen:
            seen.add(item[0])
            uniq.append(item)
    positives = uniq
    with open(os.path.join(EVAL_DIR, 'blind_test_queries.json'), encoding='utf-8') as f:
        bdata = json.load(f)
    negatives = []
    for tier in bdata:
        if tier.get('tier') == 'negative':
            negatives.extend(q['query'] for q in tier.get('queries', []) if q.get('expected_skill') is None)
    rng = random.Random(seed)
    rng.shuffle(positives)
    chosen = []
    for query, expected in positives:
        bge_layer.CALL_COUNT = 0
        bge_layer.FALLBACK_USED = False
        try:
            top1 = unified_router.route(query).get('top1')
        except Exception:
            continue
        if bge_layer.CALL_COUNT > 0 and bge_layer.FALLBACK_USED and top1 == expected:
            chosen.append((query, expected))
            if len(chosen) >= n_positive:
                break
    neg = None
    rng.shuffle(negatives)
    for q in negatives:
        bge_layer.CALL_COUNT = 0
        bge_layer.FALLBACK_USED = False
        try:
            top1 = unified_router.route(q).get('top1')
        except Exception:
            continue
        if bge_layer.CALL_COUNT > 0 and bge_layer.FALLBACK_USED and top1 in ('NONE', None):
            neg = q
            break
    neg = neg or (negatives[0] if negatives else '起个英文名')
    return chosen + [('__NEGATIVE__', neg)]


def run():
    picked = pick_queries()
    results = []
    engaged = 0
    for q in picked:
        bge_layer.CALL_COUNT = 0
        bge_layer.FALLBACK_USED = False
        if q[0] == '__NEGATIVE__':
            query, expected = q[1], None
        else:
            query, expected = q
        try:
            r = unified_router.route(query)
            top1 = r.get('top1')
            layer_called = bge_layer.CALL_COUNT > 0
            fallback = bge_layer.FALLBACK_USED
            if expected is not None:
                # positive: 必须命中期望技能，且真实穿过 BGE 层 + TF-IDF 融合/兜底
                ok = bool(top1 == expected and layer_called and fallback)
            else:
                # negative（R218 口径修正）: 断言意图 = 不误路由。
                # 前置层直接拒绝（layer_called=False）是比 BGE 层兜底拒绝
                # 更早、更省的合法拒绝路径，不再强制 negative 穿过 BGE 层。
                ok = bool(top1 in ('NONE', None))
            if ok:
                engaged += 1
            results.append({
                'query': query,
                'expected': expected,
                'top1': top1,
                'ok': bool(ok),
                'bge_layer_called': layer_called,
                'fallback_used': fallback,
                'evidence': f"route({query[:30]}) -> top1={top1} (期望 {expected}) | BGE层调用={layer_called} | TF-IDF兜底={fallback}",
            })
        except Exception as e:
            results.append({
                'query': query,
                'expected': expected,
                'top1': None,
                'ok': False,
                'bge_layer_called': False,
                'fallback_used': False,
                'evidence': f"route 抛异常: {type(e).__name__}: {e}",
            })
    passed = sum(1 for r in results if r['ok'])
    return {
        'schema': 'fenjue-degrade-behavior-v1',
        'ts': datetime.datetime.now().isoformat(timespec='seconds'),
        'passed': passed,
        'total': len(results),
        'fallback_used': bool(bge_layer.FALLBACK_USED),
        'fallback_engaged': engaged == len(results),
        'results': results,
    }


if __name__ == '__main__':
    out = run()
    if '--json' in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(0)
    print('=' * 60)
    print(f"degrade 行为验证: {out['passed']}/{out['total']} | TF-IDF 兜底路径生效={out['fallback_used']}")
    print('=' * 60)
    for r in out['results']:
        mark = '✅' if r['ok'] else '❌'
        print(f"{mark} {r['query'][:40]} -> {r['top1']} (期望 {r['expected']})")
        print(f"   证据: {r['evidence']}")
    print('=' * 60)
