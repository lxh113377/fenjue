#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C26「记忆召回评测集静态健康」（2026-09-24 P1E-1）

判据面：评测集存在/schema 识别（W1）、条目数 30~60 且 id 唯一（W2）、
        期望目标 (file,heading) 零死链（W4，R240 同族）、基线登记（W5）；
        空面不得静默 PASS（R247）；记忆根不可达仅 skip_external 才 SKIP。
隔离手法：testset_path= / root= 注入 tmp 小世界夹具（不碰真实记忆盘）；
         另跑一次真实面确认判据未失效。
覆盖：正例 2（真实面 + 夹具面）+ 违规样本 4（死链/空集/缺基线/schema）+ 边界 3
     （条目数 29 越界、文件缺失、CI SKIP/非 CI FAIL 双语义）。
登记：eval/stubs/registry.json → id=C26-memory-recall
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402


def make_fixture(td, n_items=30, dead=False, no_baseline=False, schema='fenjue-memory-recall-testset-v1', sub=''):
    td = os.path.join(td, sub) if sub else td
    os.makedirs(td, exist_ok=True)
    root = os.path.join(td, 'gm')
    os.makedirs(os.path.join(root, 'lessons'))
    with open(os.path.join(root, 'lessons', 'lessons-a.md'), 'w', encoding='utf-8') as f:
        f.write('# 壳\n## 目标经验\njunction 正文含 LinkType。\n## 干扰条目\n无关内容。\n')
    items = [{'id': 'R%02d' % i, 'query': 'junction 经验', 'keywords': ['junction', '目标'],
              'expected': [{'file': 'lessons/lessons-a.md',
                            'heading': '被删标题' if (dead and i == 0) else '目标经验'}]}
             for i in range(n_items)]
    ts = {'schema': schema, 'corpus_roots': ['lessons'],
          'params': {'top_k': 5, 'hit_at': 3},
          'baseline': ({} if no_baseline else
                       {'hit_at_5': 1.0, 'mrr': 0.9, 'measured': '2026-09-24'}),
          'items': items}
    ts_path = os.path.join(td, 'ts.json')
    with open(ts_path, 'w', encoding='utf-8') as f:
        json.dump(ts, f, ensure_ascii=False)
    return ts_path, root


REAL_ST, REAL_DETAIL = v.check_c26_memory_recall_testset()
SCAN_OK = REAL_ST == 'PASS'

cases = []
with tempfile.TemporaryDirectory() as td:
    ts_p, rt = make_fixture(td)
    cases.append(('正例-真实评测面（判据未失效）', dict(), 'SCAN', ''))
    st, d = v.check_c26_memory_recall_testset(testset_path=ts_p, root=rt)
    cases.append(('正例-夹具小世界合规', dict(testset_path=ts_p, root=rt), 'PASS', '零死链'))

    ts_p2, rt2 = make_fixture(td, sub='f2', dead=True)
    cases.append(('违规-期望死链必拦', dict(testset_path=ts_p2, root=rt2), 'FAIL', 'W4'))

    ts_p3, rt3 = make_fixture(td, sub='f3', n_items=0)
    cases.append(('违规-空评测集不得静默过(R247)', dict(testset_path=ts_p3, root=rt3), 'FAIL', 'W1'))

    ts_p4, rt4 = make_fixture(td, sub='f4', no_baseline=True)
    cases.append(('违规-基线缺失必拦', dict(testset_path=ts_p4, root=rt4), 'FAIL', 'W5'))

    ts_p5, rt5 = make_fixture(td, sub='f5', schema='other-v9')
    cases.append(('违规-schema 不识别必拦', dict(testset_path=ts_p5, root=rt5), 'FAIL', 'schema'))

    ts_p6, rt6 = make_fixture(td, sub='f6', n_items=29)
    cases.append(('边界-条目数 29 低于下限', dict(testset_path=ts_p6, root=rt6), 'FAIL', 'W2'))

    cases.append(('边界-评测集文件缺失', dict(testset_path=os.path.join(td, 'nope.json'), root=rt), 'FAIL', 'W1'))

    ghost = os.path.join(td, 'not-exist')
    cases.append(('边界-CI 记忆根不可达 SKIP',
                  dict(skip_external=True, testset_path=ts_p, root=ghost), 'SKIP', 'CI'))
    cases.append(('边界-非 CI 记忆根不可达 FAIL',
                  dict(skip_external=False, testset_path=ts_p, root=ghost), 'FAIL', 'W1'))

# 注意：消费必须在夹具 TemporaryDirectory 存活期内（判据执行时读文件，禁延迟消费）
    ok = 0
    for name, kw, expect, needle in cases:
        if name.startswith('正例-真实'):
            st, detail = ('SCAN' if SCAN_OK else 'SCAN-LOW', REAL_DETAIL)
        else:
            st, detail = v.check_c26_memory_recall_testset(**kw)
        good = (st == expect) and (needle in (detail or ''))
        ok += 1 if good else 0
        print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:110]))

print('stub_c26_memory_recall: %d/%d' % (ok, len(cases)))
sys.exit(0 if ok == len(cases) else 1)
