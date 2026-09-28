#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scorecard_memory.py — 焚诀评分卡主线② 多 agent 统一记忆 + 路由系统（50分，8维）

R208 O-4 拆分：从 scorecard.py 单体搬移 score_memory() 原样保留（行为等价）。
共享基础设施自 scorecard_shared 导入；scorecard.py（编排层）import 本模块并 re-export。
"""
import os
import sys
import json
import re

from scorecard_shared import (  # noqa: E402
    EVAL_DIR, AUDIT_DIR, GM, LINE_PASS,
    load_func_checks, run, is_script_missing, missing_script_name, dead_script_part,
)


# ============ 主线② 多 agent 统一记忆 + 路由系统（50分） ============
def score_memory() -> dict:
    """8维: P0/路由覆盖/触发词/降级/版本/记忆覆盖/4KB/内容信噪比"""
    parts = {}
    func = load_func_checks()
    fm = run([sys.executable, os.path.join(AUDIT_DIR, 'fenjue_measure.py')], timeout=300)

    def fm_val(pattern, default=0):
        m = re.search(pattern, fm)
        return float(m.group(1)) if m else default

    # D2-1 P0 注入量/首Token税 (8分)
    if is_script_missing(fm):
        # 证据脚本 fenjue_measure.py 缺失 → P0/memcover/trace 全部隔离（均为 fm 派生）
        parts['p0'] = dead_script_part(8, missing_script_name(fm))
    else:
        pct = fm_val(r'P0税: [\d.]+KB = \d+ token = ([\d.]+)% of 128K')
        d1 = 8 if pct <= 10 else 6 if pct <= 20 else 4 if pct <= 35 else 2
        parts['p0'] = {'score': d1, 'max': 8, 'detail': f'P0 占 {pct}%',
                       'evidence': 'fenjue_measure.py D1',
                       'evidence_fingerprint': 'fenjue_measure:P0首Token税'}

    # D2-2 路由覆盖度 (8分): skill_content 13 域 vs skill_routing
    # R166-U2: 从"域 JSON 存在"改为"每域真实路由命中"
    cov = func.get('coverage', {})
    if func.get('unavailable'):
        parts['coverage'] = {'score': 0, 'max': 8, 'unavailable': True,
                             'detail': f"DATA UNAVAILABLE: {func.get('reason', 'functional_dim_checks 不可用')}",
                             'evidence': 'eval/functional_dim_checks.py (每域实测路由)',
                             'evidence_fingerprint': 'coverage:每域实测路由命中'}
    else:
        cov_hit = int(cov.get('hit_domains', 0))
        cov_total = int(cov.get('total_domains', 13))
        parts['coverage'] = {'score': round(cov_hit / max(cov_total, 1) * 8, 1), 'max': 8,
                             'detail': cov.get('detail', '每域实测路由不可用'),
                             'evidence': 'eval/functional_dim_checks.py (每域实测路由)',
                             'evidence_fingerprint': 'coverage:每域实测路由命中'}

    # D2-3 触发词质量 (8分): skill_hitrate_audit WEAK 数
    hit_out = run([sys.executable, os.path.join(AUDIT_DIR, 'skill_hitrate_audit.py')])
    if is_script_missing(hit_out):
        parts['triggers'] = dead_script_part(8, missing_script_name(hit_out))
    else:
        # name_fragment 是良性（skill 名作为触发词，合理匹配），不计为问题
        # 明细行格式: "[WEAK] dogfood: 垃圾5/6混:dogfood[name_fragment]"
        weak_lines = [line for line in hit_out.split('\n') if '[WEAK]' in line and '垃圾' in line]
        weak_benign = sum(1 for line in weak_lines if 'name_fragment' in line)
        weak_real = len(weak_lines) - weak_benign
        parts['triggers'] = {'score': max(0, 8 - weak_real * 2), 'max': 8,
                             'detail': f'{weak_real} 个真实 WEAK（{weak_benign} 个良性 name_fragment）',
                             'evidence': 'audit/skill_hitrate_audit.py',
                             'evidence_fingerprint': 'skill_hitrate_audit:真实WEAK触发词数'}

    # D2-4 降级容错 (6分) — R163: 行为验证替代关键词搜索
    # 实跑 degrade_behavior_test.py（FENJUE_BGE_DISABLE=1 断掉 BGE → TF-IDF 兜底）
    dg_out = run([sys.executable, os.path.join(EVAL_DIR, 'degrade_behavior_test.py'), '--json'], timeout=300)
    dg_detail = ''
    dg_score: float = 0
    dg_unavailable = False
    try:
        dg = json.loads(dg_out)
        dg_pass = int(dg.get('passed', 0))
        dg_total = int(dg.get('total', 0))
        dg_engaged = bool(dg.get('fallback_engaged', False))
        dg_score = round(6 * dg_pass / dg_total, 1) if dg_total else 0
        if not dg_engaged:
            dg_score = 0
        dg_detail = f"degrade 行为验证 {dg_pass}/{dg_total} 走TF-IDF兜底={dg_engaged}"
    except Exception as e:
        dg_unavailable = True
        dg_detail = f"degrade 行为验证脚本异常: {e}"
    if is_script_missing(dg_out):
        # 证据脚本 degrade_behavior_test.py 缺失 → 隔离计分
        parts['degrade'] = dead_script_part(6, missing_script_name(dg_out))
    else:
        # 文本检查降为证据注释（不再独立计分）
        mi = ''
        mi_path = os.path.join(GM, 'meta', 'memory_index.md')
        if os.path.exists(mi_path):
            with open(mi_path, encoding='utf-8', errors='ignore') as f:
                mi = f.read()
        dg_text_ok = bool(re.search(r'降级|fallback|L2|L3', mi))
        parts['degrade'] = {'score': dg_score, 'max': 6,
                            'detail': f"{dg_detail} | 降级指令文本={'有' if dg_text_ok else '缺'}",
                            'evidence': 'eval/degrade_behavior_test.py 实跑',
                            'evidence_fingerprint': 'degrade_behavior_test:TF-IDF兜底行为验证'}
        if dg_unavailable:
            # R193: fail-closed——degrade 输出不可解析时显式 unavailable，禁止静默 0 分
            parts['degrade']['score'] = 0
            parts['degrade']['unavailable'] = True
            parts['degrade']['detail'] = 'DATA UNAVAILABLE: ' + dg_detail

    # D2-5 版本一致性 (6分): VERSION_LOCK 分卷格式兼容
    # R166-U2: 从"分卷数量"改为"regen --check SHA 一致性 + TOC 双向一致"
    vf = func.get('version', {})
    if func.get('unavailable'):
        parts['version'] = {'score': 0, 'max': 6, 'unavailable': True,
                            'detail': f"DATA UNAVAILABLE: {func.get('reason', 'functional_dim_checks 不可用')}",
                            'evidence': 'regen_ic_parts.py --check + VERSION_LOCK TOC 双向校验',
                            'evidence_fingerprint': 'version:regen SHA+TOC一致性'}
    else:
        v_score = 6 if vf.get('ok') else (4 if vf.get('regen_ok') else 3 if vf.get('toc_ok') else 0)
        parts['version'] = {'score': v_score, 'max': 6,
                            'detail': vf.get('detail', 'version 检查不可用'),
                            'evidence': 'regen_ic_parts.py --check + VERSION_LOCK TOC 双向校验',
                            'evidence_fingerprint': 'version:regen SHA+TOC一致性'}

    # D2-6 记忆覆盖度 (4分): fenjue_measure D25
    if is_script_missing(fm):
        parts['memcover'] = dead_script_part(4, missing_script_name(fm))
    else:
        m = re.search(r'D25 记忆覆盖:\s*(\d+)/4', fm)
        d25 = int(m.group(1)) if m else 0
        parts['memcover'] = {'score': d25, 'max': 4,
                             'detail': f'D25={d25}/4', 'evidence': 'fenjue_measure.py D25',
                             'evidence_fingerprint': 'fenjue_measure:D25记忆覆盖'}

    # D2-7 4KB 合规 (4分): fragment_detector + 大文件扫描
    # R164: 4KB 零豁免拆分是刻意为之（用户拍板），合规维度降权 6→4，
    #       让位给 D2-8 内容信噪比；碎片化本身不计入噪声扣分。
    frag_out = run([sys.executable, os.path.join(AUDIT_DIR, 'fragment_detector.py')])
    if is_script_missing(frag_out):
        parts['kb'] = dead_script_part(4, missing_script_name(frag_out))
    else:
        frag_rate = 1.0
        m = re.search(r'=\s*([\d.]+)\s*个/skill', frag_out)
        if m:
            frag_rate = float(m.group(1))
        kb = 4 if frag_rate <= 0.2 else 2 if frag_rate <= 0.5 else 1
        parts['kb'] = {'score': kb, 'max': 4, 'detail': f'碎片率 {frag_rate}',
                       'evidence': 'audit/fragment_detector.py',
                       'evidence_fingerprint': 'fragment_detector:碎片率'}

    # D2-8 内容信噪比 (6分): 噪声大雨点小专项（R164 新增）
    # 四子项: 元经验占比 / 大SKILL文件数 / 索引声明失真 / 自检金标准陈旧。
    # 4KB 拆分碎片化刻意为之，不在本维度扣分（见 audit/content_snr.py 豁免说明）。
    snr_out = run([sys.executable, os.path.join(AUDIT_DIR, 'content_snr.py')], timeout=120)
    if is_script_missing(snr_out):
        parts['content_snr'] = dead_script_part(6, missing_script_name(snr_out))
    else:
        m = re.search(r'内容信噪比:\s*([\d.]+)/6', snr_out)
        snr = float(m.group(1)) if m else 0
        snr_detail = '内容信噪比脚本无输出' if not snr_out else \
            next((line for line in snr_out.splitlines() if '内容信噪比:' in line), '')
        parts['content_snr'] = {'score': snr, 'max': 6,
                                'detail': snr_detail,
                                'evidence': 'audit/content_snr.py',
                                'evidence_fingerprint': 'content_snr:信噪比'}

    total = round(sum(p['score'] for p in parts.values()), 1)
    return {'line': '主线② 多agent统一记忆+路由', 'total': total, 'pass': LINE_PASS,
            'parts': parts,
            'evidence': ['fenjue_measure.py', 'skill_hitrate_audit.py',
                         'fragment_detector.py', 'content_snr.py']}