# -*- coding: utf-8 -*-
"""R20 双回归固定脚本：77 主集 + 48 盲测。直接复用 unified_router.run_eval（权威口径）。
用法: python run_dual_regression.py [--misses]
验收线: 77set full_pipeline.top1 >= 98.7 不回退; blind >= 90.0
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unified_router as ur

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
SHOW_MISSES = '--misses' in sys.argv


def misses_for(test_path):
    """列出真实 miss（R263：期望技能不在役的不可达用例单独计数，不计入 miss）"""
    with open(test_path, encoding='utf-8') as _f:
        data = json.load(_f)
    active = ur._active_skill_set()
    out, stale = [], []
    for tier in data:
        if tier.get('tier') == 'negative':
            continue
        for q in tier['queries']:
            exp = q.get('expected_skill')
            if not exp or not q.get('routable', True):
                continue
            exp_set = {exp} if isinstance(exp, str) else set(exp)
            if active and not (exp_set & active):
                stale.append((q['query'], exp))
                continue
            r = ur.route(q['query'])
            if r['top1'] not in exp_set:
                out.append({
                    'q': q['query'], 'exp': exp, 't1': r['top1'],
                    'conf': r.get('confidence'), 'tier': tier.get('tier'),
                    'llm': r.get('needs_llm_decision'),
                    'top3': [(c['name'], round(c['score'], 4), c.get('neg_hit')) for c in r['candidates'][:3]],
                })
    return out, stale


if __name__ == '__main__':
    p77 = os.path.join(EVAL_DIR, 'test_queries.json')
    pbl = os.path.join(EVAL_DIR, 'blind_test_queries.json')
    r77 = ur.run_eval(p77)
    rbl = ur.run_eval(pbl)
    s77 = {'n': r77['total'], 'direct': r77['direct_rate'],
           'top1': r77['full_pipeline']['top1'], 'top3': r77['full_pipeline']['top3'],
           'llm': r77['llm_recommend_rate'],
           'stale_excluded': r77.get('stale_expected', 0),
           'raw_top1': r77.get('raw_top1')}
    sbl = {'n': rbl['total'], 'direct': rbl['direct_rate'],
           'top1': rbl['full_pipeline']['top1'], 'top3': rbl['full_pipeline']['top3'],
           'llm': rbl['llm_recommend_rate'],
           'stale_excluded': rbl.get('stale_expected', 0),
           'raw_top1': rbl.get('raw_top1')}
    print('77set:', json.dumps(s77))
    print('blind:', json.dumps(sbl))
    if SHOW_MISSES:
        for name, path in (('77set', p77), ('blind', pbl)):
            ms, stale = misses_for(path)
            print('--- %s MISSES (%d；已剔除不可达 %d 条: %s) ---'
                  % (name, len(ms), len(stale), [s[1] for s in stale]))
            for m in ms:
                print(json.dumps(m, ensure_ascii=False))
    ok77 = s77['top1'] >= 98.7
    okbl = sbl['top1'] >= 90.0
    print('ACCEPT:', json.dumps({'77set>=98.7': ok77, 'blind>=90.0': okbl}))
    sys.exit(0 if (ok77 and okbl) else 1)  # 门禁退出码 (pre-cc-check [19])
