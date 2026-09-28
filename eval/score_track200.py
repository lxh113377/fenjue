#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
score_track200.py — 焚诀 track_200 六线全评（R198.10）
=====================================================================
依据 truth_constants.json scorecard.track_200（200/170/85%，六线全评，
2026-08-16 用户拍板"①⑤⑥也纳入打分，6线各约33分"）。

六线构成：
  ① 跨平台 skill 互通同步  — 复用 scorecard.score_sync()（归一化到 33 分）
  ② 多 agent 统一记忆+路由 — 复用 scorecard.score_memory()
  ③ skill 命中率优化        — 复用 scorecard.score_routing()
  ④ lessons 命中率度量      — eval/lessons_hitrate.py --json（可判定口径 hit/total）
  ⑤ 注意力优化（注意力税）  — audit/attention_sim.py --json（dilution + haystack Top-1）
  ⑥ 前置使用率采样度量      — eval/skill_usage_stats.py --json（low_frequency_candidates 治理度）

打分规则（每线 0-33 分，合计 200 分制取整到 198 结构）：
  ①②③：原 50 分制 × 33/50 归一化
  ④ lessons 命中率：score = 33 × (hit/total)（可判定口径；total=0 → 0 分 + unavailable）
  ⑤ 注意力税：score = 33 × (0.5×dilution_sess + 0.5×hit_top1)
     - dilution_sess = 本会话场景 dilution_vs_p0（0.916 → 91.6%）
     - hit_top1 = haystack Top-1 命中率（0.2 → 20%）
     - 权重理由：dilution 反映上下文健康，haystack 反映检索精度，各半
  ⑥ 使用率：score = 33 × (1 - 低频候选治理缺口)
     - 治理缺口 = min(low_frequency_candidates / total_skills, 1.0)
     - 低频候选越少（治理越彻底）分越高；total_skills=0 → 0 分 + unavailable

防幻觉：每维附 evidence（脚本路径）+ evidence_fingerprint（稳定指纹）；
        脚本缺失/JSON 解析失败 → 0 分 + unavailable=True（fail-closed）。

用法:
  python score_track200.py               # 全量评分（文本）
  python score_track200.py --json        # JSON（供 aggregate_status 消费）
  python score_track200.py --no-legacy   # 不跑 ①②③ 传统线（仅度量线，调试用）
"""
import os
import sys
import json
import subprocess

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
AUDIT_DIR = os.path.join(PROJECT_DIR, 'audit')
sys.path.insert(0, EVAL_DIR)

import scorecard  # noqa: E402  # 复用 score_sync/score_memory/score_routing

LINE_TOTAL = 33      # 每线满分（6 线 × 33 ≈ 198，取整结构）
TOTAL = 200
PASS_LINE = 170      # 与 truth_constants track_200.pass_line 一致


# 子进程预算必须**低于**测试链的每例上限（pyproject addopts `--timeout=120`），否则冷态机器
# 上「子进程还在等」会被 pytest-timeout 先打死 ⇒ 表现为 pre-commit FAIL: pytest 而指不出用例。
# 实测边界值（2026-09-25，对标轮八 D-56）：attention_sim 冷态 240 s / 热态 <120 s；旧预算 180 s
# 夹在两者之间，既跑不完冷态、又超过 120 s 天花板 —— 是「预算与天花板自相矛盾」，不是阈值调错。
SUBPROCESS_BUDGET_S = int(os.environ.get("FENJUE_SCORE_BUDGET_S", "90"))


def run_json(cmd):
    """执行脚本并解析 JSON。失败/超预算 → (None, err)（调用方须显式降级，不得静默给分）。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=SUBPROCESS_BUDGET_S)
        if p.returncode != 0:
            return None, f'exit={p.returncode}: {p.stderr[-200:]}'
        return json.loads(p.stdout), None
    except json.JSONDecodeError as e:
        return None, f'JSON解析失败: {e}'
    except Exception as e:
        return None, str(e)


def scale_legacy(line_result, line_name):
    """传统线（①②③）归一化：50 分制 → 33 分制。返回 {score, max, detail}。"""
    if line_result is None:
        return {'score': 0.0, 'max': LINE_TOTAL, 'unavailable': True,
                'detail': f'{line_name}: 原评分不可用', 'evidence': 'scorecard.score_*()',
                'evidence_fingerprint': f'track200:{line_name}:scale33'}
    raw_total = line_result.get('total', 0)
    scaled = round(raw_total * LINE_TOTAL / 50.0, 1)
    return {'score': scaled, 'max': LINE_TOTAL,
            'detail': f'{line_name}: {raw_total}/50 → {scaled}/{LINE_TOTAL}（50→33 归一化）',
            'evidence': f'scorecard.score_{line_name}()', 'evidence_fingerprint': f'track200:{line_name}:scale33'}


def score_line4():
    """④ lessons 命中率：33 × hit/(hit+miss)（可判定口径，R214-2 分母修正）。

    R214-2: 修正实现与注释口径不符——原实现 total 取 len(fps)（含 manual
    「无目标文件」条目），把不可判定样本计入分母，系统性低估命中率
    （12/17=70.6% vs 真实可判定 12/13=92.3%，与 lessons_hitrate 输出的
    hit_rate 字段同口径）。manual 无目标文件 = 无法度量，不是未命中。
    """
    data, err = run_json([sys.executable, os.path.join(EVAL_DIR, 'lessons_hitrate.py'), '--json'])
    if data is None:
        return {'score': 0.0, 'max': LINE_TOTAL, 'unavailable': True,
                'detail': f'lessons_hitrate 不可用: {err}', 'evidence': 'eval/lessons_hitrate.py --json',
                'evidence_fingerprint': 'track200:line4:lessons_hitrate'}
    hit = data.get('hit', 0)
    miss = data.get('miss', 0)
    manual = data.get('manual', 0)
    decidible = hit + miss
    if decidible <= 0:
        return {'score': 0.0, 'max': LINE_TOTAL, 'unavailable': True,
                'detail': 'lessons 可判定样本为 0（无法度量）', 'evidence': 'eval/lessons_hitrate.py --json',
                'evidence_fingerprint': 'track200:line4:lessons_hitrate'}
    rate = hit / decidible
    return {'score': round(LINE_TOTAL * rate, 1), 'max': LINE_TOTAL,
            'detail': (f'lessons 命中率 {hit}/{decidible} = {rate*100:.1f}% '
                       f'→ {LINE_TOTAL*rate:.1f}/{LINE_TOTAL}'
                       f'（可判定口径；manual {manual} 条无目标文件不计分母）'),
            'evidence': 'eval/lessons_hitrate.py --json', 'evidence_fingerprint': 'track200:line4:lessons_hitrate'}


def score_line5():
    """⑤ 注意力税：33 × (w_dil×dilution_sess + w_t1×hit_top1 + w_t10×hit_top10)。

    R217 用户拍板：Top-10 加权纳入——语义近亲竞争下 hit_top10 反映检索可用性
    （median_rank=1 时答案就在头部几个）；权重单源 truth_constants.line5_weights
    （C7 无裸常量）；strict 本体口径双轨透明披露，防刷分。
    """
    from truth_constants import LINE5_WEIGHTS
    w_dil = LINE5_WEIGHTS['dilution']
    w_t1 = LINE5_WEIGHTS['hit_top1']
    w_t10 = LINE5_WEIGHTS['hit_top10']
    if abs(w_dil + w_t1 + w_t10 - 1.0) > 1e-9:
        raise ValueError(f'line5_weights 三权和必须=1.0，实测 {w_dil + w_t1 + w_t10}')
    data, err = run_json([sys.executable, os.path.join(AUDIT_DIR, 'attention_sim.py'), '--json'])
    if data is None:
        return {'score': 0.0, 'max': LINE_TOTAL, 'unavailable': True,
                'detail': f'attention_sim 不可用: {err}', 'evidence': 'audit/attention_sim.py --json',
                'evidence_fingerprint': 'track200:line5:attention'}
    dilution_sess = 0.0
    for s in data.get('dilution', {}).get('scenarios', []):
        if '会话' in s.get('scenario', ''):
            dilution_sess = s.get('dilution_vs_p0', 0.0)
            break
    haystack = data.get('haystack', {})
    hit_top1 = haystack.get('hit_top1_rate', 0.0)
    top10_key = f"hit_top{haystack.get('top_k', 10)}_rate"
    hit_top10_raw = haystack.get(top10_key)
    top10_note = '' if hit_top10_raw is not None else f'（{top10_key} 缺失按 0 计）'
    hit_top10 = hit_top10_raw if hit_top10_raw is not None else 0.0
    hit_exact = haystack.get('hit_top1_rate_exact')
    exact_note = f' | strict本体Top1={hit_exact:.3f}' if hit_exact is not None else ''
    composite = w_dil * dilution_sess + w_t1 * hit_top1 + w_t10 * hit_top10
    return {'score': round(LINE_TOTAL * composite, 1), 'max': LINE_TOTAL,
            'detail': (f'注意力税: dilution={dilution_sess:.3f}×{w_dil} + Top1={hit_top1:.3f}×{w_t1} '
                       f'+ Top10={hit_top10:.3f}×{w_t10} → {composite:.3f} → '
                       f'{LINE_TOTAL*composite:.1f}/{LINE_TOTAL}{exact_note}{top10_note}'
                       f'（R217 Top-10 加权纳入，双轨披露）'),
            'evidence': 'audit/attention_sim.py --json', 'evidence_fingerprint': 'track200:line5:attention'}


def score_line6():
    """⑥ 使用率采样：33 × (1 - min(低频候选/技能总数, 1))。"""
    data, err = run_json([sys.executable, os.path.join(EVAL_DIR, 'skill_usage_stats.py'), '--json'])
    if data is None:
        return {'score': 0.0, 'max': LINE_TOTAL, 'unavailable': True,
                'detail': f'skill_usage_stats 不可用: {err}', 'evidence': 'eval/skill_usage_stats.py --json',
                'evidence_fingerprint': 'track200:line6:usage'}
    low_freq = len(data.get('low_frequency_candidates', []))
    total_skills = data.get('skills_seen', 0)
    if total_skills <= 0:
        return {'score': 0.0, 'max': LINE_TOTAL, 'unavailable': True,
                'detail': 'skill 采样数为 0（无法度量）', 'evidence': 'eval/skill_usage_stats.py --json',
                'evidence_fingerprint': 'track200:line6:usage'}
    gap = min(low_freq / total_skills, 1.0)
    score = LINE_TOTAL * (1 - gap)
    return {'score': round(score, 1), 'max': LINE_TOTAL,
            'detail': f'使用率: 低频候选 {low_freq}/{total_skills} → 治理缺口 {gap:.3f} → {score:.1f}/{LINE_TOTAL}',
            'evidence': 'eval/skill_usage_stats.py --json', 'evidence_fingerprint': 'track200:line6:usage'}


def run_track200(no_legacy=False):
    """执行六线全评，返回结构化结果（兼容 aggregate_status 消费字段）。"""
    lines = {}
    if not no_legacy:
        lines['line1'] = scale_legacy(scorecard.score_sync(), 'sync')
        lines['line2'] = scale_legacy(scorecard.score_memory(), 'memory')
        lines['line3'] = scale_legacy(scorecard.score_routing(), 'routing')
    else:
        for k in ('line1', 'line2', 'line3'):
            lines[k] = {'score': 0.0, 'max': LINE_TOTAL, 'unavailable': True,
                        'detail': '--no-legacy 跳过', 'evidence': 'CLI 参数',
                        'evidence_fingerprint': f'track200:{k}:skipped'}
    lines['line4'] = score_line4()
    lines['line5'] = score_line5()
    lines['line6'] = score_line6()

    overall = round(sum(v['score'] for v in lines.values()), 1)
    unavailable = [k for k, v in lines.items() if v.get('unavailable')]
    names = {'line1': '主线① 跨平台skill互通同步', 'line2': '主线② 多agent统一记忆+路由',
             'line3': '主线③ skill命中率优化', 'line4': '主线④ lessons命中率度量',
             'line5': '主线⑤ 注意力优化', 'line6': '主线⑥ 前置使用率采样'}
    # aggregate_status 兼容：lines 列表格式（label/total/max）
    lines_list = [{'line': names[k], 'total': v['score'], 'max': v['max']}
                  for k, v in lines.items()]
    verdict = 'PASS' if overall >= PASS_LINE else 'FAIL'
    return {
        'schema': 'fenjue-track200-v1',
        'generated_at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
        'ts': __import__('datetime').datetime.now().isoformat(timespec='seconds'),  # aggregate_status 兼容
        'total': TOTAL,
        'total_line': TOTAL,          # aggregate_status 兼容
        'pass_line': PASS_LINE,
        'line_pass': 0,               # 六线各自 33 分不设统一线门槛（以总分+单线可用性为准）
        'overall': overall,
        'pass': overall >= PASS_LINE,
        'verdict': verdict,           # aggregate_status 兼容
        'band': band_of(overall),
        'lines': lines_list,          # aggregate_status 兼容（list 格式）
        'lines_map': lines,           # 详细结构（dict）
        'unavailable_lines': unavailable,
    }


def band_of(overall):
    """分数带：≥170 优秀 / 150-169 良好 / 130-149 合格 / <130 不达标"""
    if overall >= PASS_LINE:
        return '优秀'
    if overall >= 150:
        return '良好'
    if overall >= 130:
        return '合格'
    return '不达标'


def main():
    as_json = '--json' in sys.argv
    no_legacy = '--no-legacy' in sys.argv
    result = run_track200(no_legacy=no_legacy)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print('=' * 60)
    print('track_200 六线全评 — %s/%s (%s)' % (result['overall'], result['total'],
                                                'PASS' if result['pass'] else 'FAIL'))
    print('=' * 60)
    names = {'line1': '①跨平台同步', 'line2': '②记忆+路由', 'line3': '③命中率',
             'line4': '④lessons命中', 'line5': '⑤注意力税', 'line6': '⑥使用率'}
    for k, v in result['lines_map'].items():
        mark = '⚠不可用' if v.get('unavailable') else ''
        print('  %s: %s/%s %s' % (names[k], v['score'], v['max'], mark))
        print('    %s' % v['detail'])
    if result['unavailable_lines']:
        print('WARN: 不可用线: %s' % ', '.join(result['unavailable_lines']))
    print('达标线: %s/%s' % (PASS_LINE, TOTAL))


if __name__ == '__main__':
    main()
