#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scorecard_routing.py — 焚诀评分卡主线③ skill 命中率优化（50分，6维）

R208 O-4 拆分：从 scorecard.py 单体搬移 score_routing() 原样保留（行为等价）。
共享基础设施自 scorecard_shared 导入；scorecard.py（编排层）import 本模块并 re-export。
"""
import os
import sys
import json
import re

from scorecard_shared import (  # noqa: E402
    EVAL_DIR, AUDIT_DIR, LINE_PASS,
    run, is_script_missing, missing_script_name, dead_script_part,
)


# ============ 主线③ skill 命中率优化（50分） ============
def score_routing() -> dict:
    """6维: 直连/全管线/盲测/LLM决策/追问/负标签"""
    parts = {}
    # R168: eval 强制隔离 —— 即使被调用端未自行关闭 trace，也绝不让回归查询进生产 trace
    out = run([sys.executable, os.path.join(EVAL_DIR, 'unified_router.py'), '--eval'],
              timeout=300,
              env={**os.environ, 'FENJUE_ROUTE_TRACE': '0',
                   'FENJUE_TRACE_SOURCE': 'regression'})

    def ev(pattern, default=0):
        m = re.search(pattern, out)
        return float(m.group(1)) if m else default

    # D3-1 直连层 Top-1 (12分)
    if is_script_missing(out):
        # 证据脚本 unified_router.py 缺失 → direct/full/llm 全部隔离（均为 out 派生）
        parts['direct'] = dead_script_part(12, missing_script_name(out))
    else:
        direct = ev(r'直连映射层.*?Top-1:\s*([\d.]+)%', 0)
        # 上面的正则跨多行可能不匹配，用简单方式
        if direct == 0:
            # 直连行: "  命中: 70/77 = 90.9%" 在直连映射层段
            seg = out.split('基础管线')[0]
            m = re.search(r'命中:\s*\d+/\d+\s*=\s*([\d.]+)%', seg)
            direct = float(m.group(1)) if m else 0
        parts['direct'] = {'score': round(direct / 100 * 12, 1), 'max': 12,
                           'detail': f'直连层 Top-1 {direct}%',
                           'evidence': 'unified_router.py --eval',
                           'evidence_fingerprint': 'unified_router_eval:直连层Top1'}

    # D3-2 全管线 Top-1 (14分)
    if is_script_missing(out):
        parts['full'] = dead_script_part(14, missing_script_name(out))
    else:
        full = ev(r'全管线.*?Top-1:\s*([\d.]+)%', 0)
        if full == 0:
            seg = out.split('全管线')[1] if '全管线' in out else ''
            m = re.search(r'Top-1:\s*([\d.]+)%', seg)
            full = float(m.group(1)) if m else 0
        parts['full'] = {'score': round(full / 100 * 14, 1), 'max': 14,
                         'detail': f'全管线 Top-1 {full}%',
                         'evidence': 'unified_router.py --eval',
                         'evidence_fingerprint': 'unified_router_eval:全管线Top1'}

    # D3-3 盲测集 (10分): R163 分层盲测集为主口径, frozen 冻结集保留对照
    # 自写测试集 100% 是过拟合自家 query 的结果（盲评实测虚高 21pp），不能作为盲测
    # frozen_blind_eval.py 跑分层集（永不调参），judge 加权(exact=1.0/usable=0.75/wrong=0.5/blindspot=0.4)
    fbe = run([sys.executable, os.path.join(EVAL_DIR, 'frozen_blind_eval.py'), '--json', '--set', 'layered'], timeout=900)
    fbe_frozen = run([sys.executable, os.path.join(EVAL_DIR, 'frozen_blind_eval.py'), '--json'], timeout=600)
    blind_unavailable = False
    frozen_unavailable = False
    try:
        mf = re.search(r'(\{.*\})', fbe_frozen, re.S)
        frozen_d = json.loads(mf.group(1)) if mf else {}
        frozen_score = float(frozen_d.get('score', 0))
        frozen_n = frozen_d.get('n', 0)
    except Exception:
        # R193: fail-closed——frozen 盲测输出不可解析时显式 unavailable，禁止静默 0 分
        frozen_unavailable = True
        frozen_score, frozen_n = 0, 0
    fbe_findings = []
    bge_status = 'engaged'
    try:
        m = re.search(r'(\{.*\})', fbe, re.S)
        fbe_d = json.loads(m.group(1)) if m else {}
        blind = float(fbe_d.get('score', 0))
        blind_n = fbe_d.get('n', 0)
        blind_ach = float(fbe_d.get('max_achievable', 0))  # R165 U1: 分层集设计上限
        bge_status = fbe_d.get('bge_status', 'engaged')  # R-fix: BGE 真实加载状态
        fbe_findings = [
            r for r in fbe_d.get('results', [])
            if r.get('judge') in ('wrong', 'blindspot') or not r.get('hit')
        ]
    except Exception:
        # R193: fail-closed——分层盲测输出不可解析时显式 unavailable，禁止静默 0 分
        blind_unavailable = True
        blind, blind_n, blind_ach = 0, 0, 0
        bge_status = 'unknown'
    # R165 U1: cap = 全命中时可达上限（judge 加权导致 10/10 不可达时为 <10），
    # 供 collect_red_team 判定"是否低于可达上限"，避免把设计上限误报为缺陷
    if is_script_missing(fbe_frozen):
        # 证据脚本 frozen_blind_eval.py 缺失 → 盲测维隔离计分
        parts['blind'] = dead_script_part(10, missing_script_name(fbe_frozen))
    else:
        parts['blind'] = {'score': round(blind / 100 * 10, 1), 'max': 10,
                          'cap': round(blind_ach / 100 * 10, 1) if blind_ach else 10,
                          'detail': f'分层盲测 {blind}% ({blind_n}条) | frozen对照 {frozen_score}% ({frozen_n}条) | BGE={bge_status}',
                          'evidence': 'eval/layered_testset.json (frozen_blind_eval.py --set layered 实跑)',
                          'evidence_fingerprint': 'frozen_blind_eval:分层盲测加权分'}
    if blind_unavailable or frozen_unavailable:
        parts['blind']['score'] = 0
        parts['blind']['unavailable'] = True
        parts['blind']['detail'] = 'DATA UNAVAILABLE: 分层/frozen 盲测输出不可解析'
    elif bge_status == 'degraded_to_tfidf':
        # R-fix: torch 缺失导致 bge_recall 静默降级 TF-IDF，盲测分数非 BGE 语义层成绩，隔离计分
        parts['blind']['score'] = 0
        parts['blind']['unavailable'] = True
        parts['blind']['detail'] = ('DATA UNAVAILABLE: BGE 语义层降级为 TF-IDF (torch 缺失)，'
                                    '本盲测分数不可作为 BGE 命中率，已隔离计分')

    # D3-4 LLM 决策率 (4分): 越低越好
    if is_script_missing(out):
        parts['llm'] = dead_script_part(4, missing_script_name(out))
    else:
        llm = ev(r'LLM 决策推荐率:.*?([\d.]+)%', 0)
        llm_s = 4 if llm <= 5 else 3 if llm <= 10 else 2 if llm <= 20 else 1
        parts['llm'] = {'score': llm_s, 'max': 4, 'detail': f'LLM 决策率 {llm}%',
                        'evidence': 'unified_router.py --eval',
                        'evidence_fingerprint': 'unified_router_eval:LLM决策率'}

    # D3-5 路由追问能力 (6分): fenjue_measure D27
    fm = run([sys.executable, os.path.join(AUDIT_DIR, 'fenjue_measure.py')], timeout=300)
    if is_script_missing(fm):
        parts['trace'] = dead_script_part(6, missing_script_name(fm))
    else:
        m = re.search(r'D27 追问/经验:\s*(\d+)/6', fm)
        d27 = int(m.group(1)) if m else 0
        parts['trace'] = {'score': d27, 'max': 6, 'detail': f'D27={d27}/6',
                          'evidence': 'fenjue_measure.py D27',
                          'evidence_fingerprint': 'fenjue_measure:D27追问/经验'}

    # D3-6 负标签健康 (4分): negative_tag_audit
    neg_out = run([sys.executable, os.path.join(AUDIT_DIR, 'negative_tag_audit.py')])
    if is_script_missing(neg_out):
        # 证据脚本 negative_tag_audit.py 缺失/失效 → 隔离计分（不再静默 0 分）
        parts['negtag'] = dead_script_part(4, missing_script_name(neg_out))
    else:
        m = re.search(r'健康率: ([\d.]+)%', neg_out)
        neg_rate = float(m.group(1)) if m else 0
        parts['negtag'] = {'score': round(neg_rate / 100 * 4, 1), 'max': 4,
                           'detail': f'负标签健康率 {neg_rate}%',
                           'evidence': 'audit/negative_tag_audit.py',
                           'evidence_fingerprint': 'negative_tag_audit:负标签健康率'}

    total = round(sum(p['score'] for p in parts.values()), 1)
    return {'line': '主线③ skill命中率优化', 'total': total, 'pass': LINE_PASS,
            'parts': parts,
            'blind_findings': fbe_findings,
            'evidence': ['unified_router.py --eval', 'blind_test_queries.json',
                         'negative_tag_audit.py']}