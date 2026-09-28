#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
route_miss_report.py — R20 Task#3 生产路由闭环消费端
====================================================
消费 route_trace.jsonl（unified_router._trace 在 FENJUE_ROUTE_TRACE=1 时写入），
产出周期性路由质量报告，形成 Bilibili 方法论的"数据闭环迭代"。

分析维度:
  1. 置信度分布 (HIGH/MEDIUM/LOW) — MEDIUM 比例过高说明边界模糊
  2. NONE 判定率 — 过高说明阈值过严或缺 skill
  3. needs_llm 率 — LLM 决策成本监控
  4. 高频 query 模式 — 反复出现的相似 query 是 DIRECT_MAP 候选
  5. neg_hit 触发榜 — 哪些负标签在生产真实拦截

用法:
  python route_miss_report.py            # 全量分析
  python route_miss_report.py --days 7   # 近7天
  python route_miss_report.py --clear    # 分析后归档清空 trace
"""
import os
import sys
import json
import datetime
from collections import Counter
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
TRACE_PATH = os.path.join(EVAL_DIR, 'route_trace.jsonl')
ARCHIVE_DIR = os.path.join(EVAL_DIR, 'trace_archive')


def load_traces(days=None, source='production'):
    """加载 trace。source: 'production'(默认,只看生产) / 'all'(含regression) / 'regression'"""
    if not os.path.exists(TRACE_PATH):
        return []
    rows = []
    cutoff = None
    if days:
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
    for line in Path(TRACE_PATH).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if cutoff and r.get('ts', '') < cutoff:
            continue
        # source 过滤: 无 src 字段的旧记录视为 production
        rec_src = r.get('src', 'production')
        if source != 'all' and rec_src != source:
            continue
        rows.append(r)
    return rows


def report(rows, source_label='production'):
    n = len(rows)
    print('=' * 60)
    print('生产路由质量报告 [%s] — %d 条 trace' % (source_label, n))
    print('=' * 60)
    if not n:
        print('trace 为空。确认每轮跑 unified_router.py --json。')
        print('提示: --all 查看含 regression 的全部数据。')
        return
    conf = Counter(r.get('confidence') for r in rows)
    print('\n置信度分布:')
    for k, v in conf.most_common():
        print('  %s: %d (%.1f%%)' % (k, v, v / n * 100))
    none_ct = sum(1 for r in rows if r.get('top1') in (None, 'NONE'))
    llm_ct = sum(1 for r in rows if r.get('needs_llm') or r.get('needs_llm_decision'))
    print('\nNONE 判定率: %.1f%% | needs_llm 率: %.1f%%' % (none_ct / n * 100, llm_ct / n * 100))

    print('\nTop-10 命中 skill:')
    top1 = Counter(r.get('top1') for r in rows if r.get('top1'))
    for k, v in top1.most_common(10):
        print('  %s: %d' % (k, v))

    # 高频相似 query 前缀（DIRECT_MAP 候选信号）
    print('\n高频 query 前8字模式 (>=3次 → DIRECT_MAP 候选):')
    pat = Counter((r.get('q') or r.get('query') or '')[:8] for r in rows)
    hits = [(k, v) for k, v in pat.most_common(15) if v >= 3 and k]
    if hits:
        for k, v in hits:
            print('  "%s...": %d' % (k, v))
    else:
        print('  (无)')

    # MEDIUM/LOW 明细 — 人工复核队列
    weak = [r for r in rows if r.get('confidence') in ('MEDIUM', 'LOW')]
    if weak:
        print('\nMEDIUM/LOW 复核队列 (%d 条, 最近10):' % len(weak))
        for r in weak[-10:]:
            print('  [%s] %s -> %s' % (r.get('confidence'), (r.get('q') or r.get('query') or '')[:30], r.get('top1')))


def archive_and_clear():
    if not os.path.exists(TRACE_PATH):
        return
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    dst = os.path.join(ARCHIVE_DIR, 'route_trace_%s.jsonl' % stamp)
    os.replace(TRACE_PATH, dst)
    print('\ntrace 已归档 -> %s' % dst)


if __name__ == '__main__':
    days = None
    if '--days' in sys.argv:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    source = 'all' if '--all' in sys.argv else 'production'
    rows = load_traces(days, source=source)
    report(rows, source_label=source)
    if '--clear' in sys.argv:
        archive_and_clear()
