#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
frozen_blind_eval.py — 冻结独立盲测集评估（2026-08-01 盲评建立）

原则: frozen_blind_test.json 的 query 永不参与任何调参/训练。
每次评分只跑不调，作为路由真实能力的独立基准，与自写测试集对比暴露虚高。

用法:
  python eval/frozen_blind_eval.py          # 全量跑 + 计分
  python eval/frozen_blind_eval.py --json   # JSON 输出（供 scorecard 消费）
  python eval/frozen_blind_eval.py --json --set layered  # R163: 分层盲测集（批2）

计分规则（与盲评一致）:
  exact=1.0, usable-suboptimal=0.75, wrong=0.5, blindspot=0.4
  Top-1 合理性 = 加权平均 × 100%
"""
import json
import os
import sys
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
ROUTER = os.path.join(EVAL_DIR, 'unified_router.py')
FROZEN = os.path.join(EVAL_DIR, 'frozen_blind_test.json')

JUDGE_WEIGHT = {'exact': 1.0, 'usable-suboptimal': 0.75, 'wrong': 0.5, 'blindspot': 0.4}


def load_frozen(set_name='frozen'):
    path = os.path.join(EVAL_DIR, 'layered_testset.json') if set_name == 'layered' else FROZEN
    return json.loads(Path(path).read_text(encoding='utf-8'))


def run_router(query):
    """打路由器，返回 Top-1 skill 名（L1 默认选择，无则 LLM 决策段最后选择）"""
    # R163: 进程内路由（BGE 只加载一次），top1 与 CLI 输出同源（route()['top1']）
    # R214-3 治本: enable_memory=False —— memory_boost 按 route_trace 尾部 1MB 的
    # 会话频率做 boost，盲测自身跑 291 条会冲刷 trace 窗口（实证：同日 3 次盲测后
    # 2 条 ffmpeg/mediakit query 从 exact 翻向高频 skill video-whisper-transcribe）。
    # 盲测 = 确定性回归门禁，频率自适应属生产行为，评估必须与 trace 状态解耦。
    try:
        os.environ['TRANSFORMERS_VERBOSITY'] = 'error'
        os.environ['FENJUE_ROUTE_TRACE'] = '0'
        sys.path.insert(0, EVAL_DIR)
        import unified_router
        r = unified_router.route(query, enable_memory=False)
        return r.get('top1'), ''
    except Exception as e:
        return '?', str(e)


def evaluate(set_name='frozen'):
    tiers = load_frozen(set_name)
    results = []
    total_w = 0.0
    hit_w = 0.0
    n = 0
    for tier in tiers:
        for q in tier.get('queries', []):
            query = q['query']
            expected = q.get('expected_skill')
            judge = q.get('judge', 'exact')
            top1, _ = run_router(query)
            w = JUDGE_WEIGHT.get(judge, 0.5)
            total_w += w
            n += 1
            # R164 修正: 盲区(期望 None)命中 = 路由器返回 NONE; 否则 top1 == 期望
            hit = (top1 in (None, 'NONE')) if expected is None else (top1 == expected)
            if hit:
                hit_w += w
            results.append({
                'query': query,
                'expected': expected,
                'judge': judge,
                'weight': w,
                'router_top1': top1,
                'hit': bool(hit),
            })
    # R164 修正: 分数 = 命中条目的加权和 / 总条数（原实现只算判定权重均值, 与路由质量无关）
    score = round(hit_w / n * 100, 1) if n else 0.0
    # R165 U1 审计: 暴露设计上限（全命中时的最大得分）供 scorecard 红队判定用
    # —— blindspot 等部分权重类目使 max(10/10) 不可达，上限 = 权重和/条数
    max_achievable = round(total_w / n * 100, 1) if n else 0.0
    # R-fix: 暴露 BGE 真实加载状态 —— torch 缺失会令 _load_bge 探测失败、bge_recall 静默降级 TF-IDF，
    # 该情况下盲测分数实为 TF-IDF 命中率，不可当作 BGE 语义层成绩。engaged=已加载 / degraded_to_tfidf=未加载
    bge_mod = sys.modules.get('bge_layer')
    bge_loaded = bool(bge_mod and getattr(bge_mod, '_bge_model', None) is not None)
    bge_status = 'engaged' if bge_loaded else ('degraded_to_tfidf' if bge_mod else 'unknown')
    return {'score': score, 'max_achievable': max_achievable, 'n': n,
            'bge_status': bge_status,
            'hits': sum(1 for r in results if r['hit']), 'results': results}


if __name__ == '__main__':
    as_json = '--json' in sys.argv
    set_name = 'layered' if '--set' in sys.argv and sys.argv[sys.argv.index('--set') + 1] == 'layered' else 'frozen'
    r = evaluate(set_name)
    # R-fix: BGE 降级时打明显告警（仍输出 JSON 供 scorecard 拦截，不靠退出码破坏管线）
    if r.get('bge_status') == 'degraded_to_tfidf':
        print('⚠️ [BGE 降级] torch 未加载，bge_recall 已静默降级 TF-IDF —— 本分数非 BGE 语义层成绩',
              file=sys.stderr)
    if as_json:
        r['set'] = set_name
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0)
    print('=' * 60)
    print(f'盲测集评估 ({set_name}): Top-1 合理性 = {r["score"]}% ({r["n"]} 条)')
    print('=' * 60)
    for row in r['results']:
        mark = '✅' if row['hit'] else ('⚠️' if row['judge'] != 'exact' else '❌')
        print(f"{mark} [{row['judge']}] {row['query'][:30]}")
        print(f"    期望: {row['expected']} | 实路由: {row['router_top1']} | 权重: {row['weight']}")
    print('=' * 60)
    print('注意: 此集冻结永不调参。分数与自写测试集(100%)的差值 = 真实虚高幅度。')
