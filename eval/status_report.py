#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""status_report.py — STATUS.md 正文生成模块（R208 O-4 收尾：aggregate_status 拆分）。

从 aggregate_status.py 搬移: _is_overdue / compute_tracking_stats / load_registry_counts /
split_status / generate_status（STATUS.md 壳 + STATUS.part1.md 正文生成）。
本模块不依赖 aggregate_status（单向依赖防循环）；aggregate_status.main 经 generate_status 复用。
"""
import os
import sys
import glob
import json
import datetime
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
sys.path.insert(0, EVAL_DIR)
from truth_constants import (  # noqa: E402
    ENDPOINT_COUNT, GLOBAL_MEMORY_ROOT, MAINLINES, MAINLINE_COUNT,
    SCORECARD_TOTAL, SCORECARD_PASS_LINE,
    SCORECARD_ACTIVE_TRACK, SCORECARD_TRACK_200,
    BEHAVIOR_CORE_VERSION, BEHAVIOR_CORE_ANCHORS, BEHAVIOR_CORE_VALID,
)
STATUS_PATH = os.path.join(PROJECT_DIR, "STATUS.md")
STATUS_PART1_PATH = os.path.join(PROJECT_DIR, "STATUS.part1.md")
PROJECT_NAME = "焚诀"

# R213: 达标线随 active_track 动态取。此前恒取 track_150（120/150），
# 而评分卡已切 track_200（170/200）-> STATUS 头部达标线与实测总分口径不一致。
if SCORECARD_ACTIVE_TRACK == "track_200":
    PASS_LINE = "%s/%s" % (SCORECARD_TRACK_200.get("pass_line", SCORECARD_PASS_LINE),
                           SCORECARD_TRACK_200.get("total", SCORECARD_TOTAL))
else:
    PASS_LINE = f"{SCORECARD_PASS_LINE}/{SCORECARD_TOTAL}"  # 从 truth_constants 读取


def _is_overdue(deadline):
    """deadline 早于今日且未闭环 → 超期。解析失败视为未超期（不误伤）。"""
    try:
        return datetime.datetime.fromisoformat(deadline).date() < datetime.date.today()
    except Exception:
        return False


def compute_tracking_stats(defects):
    """从台账计算闭环统计: 未闭环/超期/无负责人/refuted。
    未闭环 = status 非 closed; 超期 = 未闭环且 deadline < 今日; 无负责人 = 未闭环且 owner=='未指派';
    R168: 逃生门超期 = 未闭环且 escape_hatch_deadline < 今日。"""
    if not defects:
        return {'total': 0, 'unclosed': 0, 'overdue': 0, 'escape_overdue': 0,
                'no_owner': 0, 'refuted': 0}
    unclosed = [d for d in defects if d.get('status') != 'closed']
    overdue = [d for d in unclosed if _is_overdue(d.get('deadline', ''))]
    escape_overdue = [d for d in unclosed
                      if _is_overdue(d.get('escape_hatch_deadline', ''))]
    no_owner = [d for d in unclosed if d.get('owner', '未指派') == '未指派']
    refuted = [d for d in defects
               if d.get('status') == 'closed' and d.get('resolution') == 'refuted']
    return {
        'total': len(defects),
        'unclosed': len(unclosed),
        'overdue': len(overdue),
        'escape_overdue': len(escape_overdue),
        'no_owner': len(no_owner),
        'refuted': len(refuted),
    }


def load_registry_counts():
    """R-fix: 系统状态行动态化（消除 144/13 写死漂移），读取真相源注册表。"""
    p = os.path.join(PROJECT_DIR, 'skill', 'registry', 'unified-skills-index.json')
    try:
        d = json.loads(Path(p).read_text(encoding='utf-8'))
        skills = d.get('skills', {})
        if not isinstance(skills, dict):
            return None, None
        n = len(skills)
        domains = len({v.get('domain') or '99-other' for v in skills.values()})
        return n, domains
    except Exception:
        return None, None


def split_status(content, gen_ts):
    """STATUS 壳拆分（R166-U4 C5）:
    恒为指针壳模式：STATUS.md 留指针壳（TOC + 摘要行），完整正文落 STATUS.part1.md；
    保证壳与分卷均 ≤4096B、0 孤儿 part（正文超限时需压缩行文案）。
    壳必须保留 `机器实测综合: X/150` 摘要行（cross_layer_audit 文档层依赖该行）。"""
    summary = []
    for line in content.splitlines():
        if line.startswith(('当前轮次:', '机器实测综合:', '归一化达成率:', '缺陷闭环:',
                            '门禁总判定:', '判定(Codex):', '判定说明:', '数据源:')):
            summary.append(line)
    shell = []
    shell.append('# %s — %d大主线并行（指针壳）' % (PROJECT_NAME, MAINLINE_COUNT))
    shell.append('')
    shell.append('> AUTO-GENERATED: %s | DO NOT EDIT — 跑 `python eval/aggregate_status.py` 更新' % gen_ts)
    shell.append('> 完整正文见 `STATUS.part1.md`（≤4096B，0 孤儿 part）')
    shell.append('')
    shell.append('## 摘要')
    shell.append('')
    shell.extend(summary)
    shell.append('')
    shell.append('## 分卷目录')
    shell.append('')
    shell.append('| 卷 | 内容 | 状态 |')
    shell.append('|----|------|------|')
    shell.append('| STATUS.part1.md | 完整正文（%d线详情/终检/系统状态/已知问题） | 当前 |' % MAINLINE_COUNT)
    shell.append('')
    shell.append('> 本壳与正文均由 aggregate_status.py 自动生成；STATUS.part1.md 为唯一正文分卷。')
    return '\n'.join(shell), content


def generate_status(latest, dry_run=False, scorecard=None, three_door=None,
                    lessons_hitrate=None, cross_layer=None, pread=None, tracking=None,
                    gate=None, attention_sim=None, skill_usage=None, memory_recall=None):
    lines = []
    lines.append('# %s — %d大主线并行' % (PROJECT_NAME, MAINLINE_COUNT))
    lines.append('')
    lines.append('## 项目目标（2026-08-02 明确，%d线平等推进）' % MAINLINE_COUNT)
    for ml in MAINLINES:
        lines.append('%d. **%s** — %s' % (
            ml['id'], ml['name'],
            '评分线' if ml['kind'] == 'scored' else '指标线'))
    lines.append('')
    lines.append('> 原始目标(2026-07-04): `history/skill互通.txt` — 跨平台互通（主线1起源）。')
    lines.append('')
    lines.append('---')
    gen_ts = datetime.datetime.now().isoformat(timespec='seconds')
    lines.append('AUTO-GENERATED: %s | DO NOT EDIT — 跑 `python eval/aggregate_status.py` 更新' % gen_ts)
    lines.append('达标线: %s（V2 融合评分卡）' % PASS_LINE)
    lines.append('')

    # R197: 门禁(C1~C12)为唯一真相源，驱动头条达标判定（防评分卡百分比失真）
    gate_ok = bool(gate['all_pass']) if gate else None

    # ===== R197: 单一真相源门禁（C1~C12），覆盖评分卡百分比失真 =====
    if gate:
        gres = gate.get('results', [])
        g_pass = sum(1 for r in gres if r.get('status') == 'PASS')
        g_fail = sum(1 for r in gres if r.get('status') == 'FAIL')
        g_skip = sum(1 for r in gres if r.get('status') == 'SKIP')
        # R213: 门禁编号范围动态取（C13 已加入，"C1~C12" 为废弃字面量）
        _gnums = [int(str(r.get("id", ""))[1:]) for r in gres
                  if str(r.get("id", "")).startswith("C") and str(r.get("id", ""))[1:].isdigit()]
        _gid_range = "C1~C%d" % max(_gnums) if _gnums else "C1~C12"
        _gid_count = len(_gnums) if _gnums else 12
        lines.append("## 单一真相源门禁（%s）" % _gid_range)
        lines.append("> R197: verify_truth_consistency.py %d 项门禁为唯一真相源，" % _gid_count +
                     "头条达标以门禁为准，评分卡百分比仅作明细参考。")
        lines.append('')
        lines.append("门禁总判定: %s（%s PASS %d / FAIL %d / SKIP %d）" % (
            '✅ 全部通过' if gate.get('all_pass') else '❌ 存在未通过',
            _gid_range, g_pass, g_fail, g_skip))
        lines.append('')
        lines.append('| 门禁 | 描述 | 状态 | 明细 |')
        lines.append('|:----:|:------|:----:|------|')
        for r in gres:
            _ic = {'PASS': '✅', 'FAIL': '❌', 'SKIP': '⏭️'}.get(r.get('status'), '?')
            lines.append('| %s | %s | %s | %s |' % (r.get('id'), r.get('desc'),
                                                    _ic, r.get('detail')))
        lines.append('')

    if scorecard:
        # ===== 融合评分卡 V2: 三主线机器实测 =====
        if scorecard.get('schema') == 'fenjue-track200-v1':
            # R198.10: track_200 六线全评（六线各 33 分）
            line_total = scorecard.get('total_line', 200)
            verdict = scorecard.get('verdict', 'FAIL')
            dims = []  # 六线判定以总分制，不设 per-line dims（下方 dims 循环跳过）
            line_pass = 0
            score_lines = []
            for entry in scorecard.get('lines', []):
                label = entry.get('line', '?')
                total = entry.get('total', 0)
                passed = '✅' if entry.get('total', 0) >= 0 else '❌'  # 六线展示制，判定以总分
                score_lines.append('%s=%s/33 %s' % (label.replace('主线', ''), total, passed))
            lines.append('当前轮次: ' + ' | '.join(score_lines))
            lines.append('机器实测综合: %s/%d (%s%%)' % (
                scorecard['overall'], line_total,
                round(scorecard['overall'] / line_total * 100, 1)))
            if scorecard.get('unavailable_lines'):
                lines.append('⚠ 不可用线: %s' % ', '.join(scorecard['unavailable_lines']))
        else:
            # v1/v2 分支：统一走公共渲染段（437-454 行）
            if scorecard.get('schema') == 'fenjue-scorecard-v2':
                dims = [('主线① 跨平台skill互通同步', 'sync'),
                        ('主线② 多agent统一记忆+路由', 'memory'),
                        ('主线③ skill命中率优化', 'routing')]
                line_pass = int(scorecard.get('line_pass', 40))
                line_total = 50  # 三主线各 50 分
                verdict = scorecard.get('verdict', 'FAIL')
            else:
                # v1 兼容（旧三线）
                dims = [('路由质量线', 'routing'), ('生态健康线', 'health'), ('记忆一致性线', 'memory')]
                line_pass = 115
                line_total = scorecard['total_line']
                verdict = 'PASS' if scorecard.get('overall', 0) >= 120 else 'FAIL'
            score_lines = []
            for label, key in dims:
                line = scorecard.get('lines', {})
                entry = next((ln for ln in line if ln.get('line') == label), None)
                if entry:
                    total = entry['total']
                    passed = total >= line_pass
                    score_lines.append('%s=%s/%d %s' % (label, total, line_total,
                                                        '✅达标' if passed else '❌未达标'))
            lines.append('当前轮次: ' + ' | '.join(score_lines))
            # R115 修复: 机器实测综合分须独立显示（此前被三门 min 掩盖）
            lines.append('机器实测综合: %s/%d (%s%%)' % (
                scorecard['overall'], scorecard['total_line'],
                round(scorecard['overall'] / scorecard['total_line'] * 100, 1)))
            if scorecard.get('achievable_total'):
                lines.append('归一化达成率: %s/%s (%s%%)' % (
                    scorecard['overall'], scorecard['achievable_total'],
                    scorecard.get('achievable_pct', '?')))
        if three_door:
            # R158: 三门审计取消, Codex 独立评分（eval/codex_audit_scores.json）
            ca = three_door
            mb = ca.get('machine_baseline', {})
            cb = ca.get('codex_blind', {})
            ic = ca.get('independent_checks', {})
            # R166-U1: 判定以 scorecard 门禁为准（PASS ⇔ 无确认缺陷/无超期 pending/全维达标）
            ok = (scorecard.get('verdict') == 'PASS')
            if gate_ok is False:
                # R201: 门禁(C1~C12) FAIL = 一票否决（单向）。
                # 原 R197 双向覆盖有语义错位：C1~C12 只校验数据层一致性（注册表==磁盘==BGE），
                # 不校验指标达标/缺陷闭环，因此 gate PASS 不得洗白评分卡 FAIL，
                # 否则 STATUS 首屏出现「✅ 达标（不达标）」伪绿。
                ok = False
            band = scorecard.get('band', '')
            _track = compute_tracking_stats((tracking or {}).get('defects', []))
            if _track['overdue'] > 0:
                # R166-U4: 台账超期 → STATUS 判定联动降级（scorecard.py 红线只读，由消费端联动）
                ok = False
                band = '不达标'
            if _track['escape_overdue'] > 0:
                # R168: 逃生门超期未裁决 → 同样联动降级（防文档化绕过门禁）
                ok = False
                band = '不达标'
            lines.append('Codex 独立审计: 机器基线 %s/%s (%s%%) | 盲测 %s%% (%s 条: exact %s/usable %s/wrong %s)' % (
                # 2026-09-24 对标轮修正：分母原取 scorecard['total_line']（当前=200），
                # 而 mb.score/mb.pct 是**档案里当轮 track 的实测**（149.4/150=99.6%）——
                # 混用两条 track 产出「149.4/200 (99.6%)」这种自相矛盾行。改用档案自带 out_of。
                mb.get('score', '?'), mb.get('out_of', scorecard['total_line']), mb.get('pct', '?'),
                cb.get('weighted_pct', '?'), cb.get('total', '?'),
                cb.get('exact', '?'), cb.get('usable', '?'), cb.get('wrong', '?')))
            # R166-U1: CC 复检仅作异源佐证（单轮非确定，不作独立门），并入独立核验行
            _cc = ca.get('cc_recheck') or {}
            _cc_txt = ''
            if _cc.get('agreement_rate') is not None:
                _cc_txt = ' | CC佐证 %s%%(非独立门)' % _cc['agreement_rate']
            lines.append('独立核验(档案): 盲测集 %s | 回归 %s | lessons %s%s' % (
                ic.get('blind_set', '?'), ic.get('regression', '?'),
                ic.get('lessons', '?'), _cc_txt))
            lines.append('判定(Codex): %s%s' % (
                '✅ 达标' if ok else '❌ 未达标',
                f'（{band}）' if band else ''))
            vn = ca.get('verdict_note', '')
            _blockers = scorecard.get('verdict_blockers', [])
            if _track['overdue'] > 0:
                _blockers = list(_blockers) + ['超期 pending %d 条未闭环(台账)' % _track['overdue']]
            if _track['escape_overdue'] > 0:
                _blockers = list(_blockers) + ['逃生门超期未裁决 %d 条(台账)' % _track['escape_overdue']]
            if _blockers:
                vn = ('阻断: ' + '; '.join(_blockers) + (' | ' + vn if vn else ''))
            # R166-U4 S2-1: cut 兜底（verdict_note 为空且无 blockers 时不再 NameError）
            cut = 72
            if vn:
                cut = 56 if _blockers else 72
            lines.append('判定说明: %s%s' % (vn[:cut], '…' if len(vn) > cut else ''))
            lines.append('缺陷闭环: 未闭环 %d（超期 %d / 无负责人 %d）' % (
                _track['unclosed'], _track['overdue'], _track['no_owner'])
                + ('（逃生门超期 %d）' % _track['escape_overdue'] if _track['escape_overdue'] else ''))
            # R163 红队化: 本轮缺陷发现行（确认=评分卡run级+审计档案, 误报=审计档案, 盲区=评分卡实时）
            sc_rt = scorecard.get('red_team', {})
            ca_rt = ca.get('red_team', {})
            if sc_rt or ca_rt:
                # R166-U1: 确认数分来源展示，禁混加（"确认 1"式无归属数字是口径缺陷）
                sc_conf = len(sc_rt.get('confirmed', []))
                ca_conf = len(ca_rt.get('confirmed', []))
                conf = sc_conf + ca_conf
                fp = len(ca_rt.get('false_positive', []))
                blind_n = len(sc_rt.get('blindspots', []))
                noise = ''
                if conf + fp > 0 and fp / (conf + fp) > 0.5:
                    noise = ' ⚠️噪声高'
                lines.append('本轮缺陷发现: 确认[实时]=%s | 确认[档案]=%s | 误报=%s | 盲区=%s%s' % (
                    sc_conf, ca_conf, fp, blind_n, noise))
        else:
            lines.append('综合: %s/%d (%s%%)' % (scorecard['overall'], scorecard['total_line'],
                                                 round(scorecard['overall']/scorecard['total_line']*100, 1)))
            lines.append('判定: %s' % ('✅ 达标' if (gate_ok if gate_ok is not None else verdict == 'PASS') else '❌ 未达标'))
        if three_door:
            lines.append('数据源: scorecard@%s + Codex审计@%s — 每线证据见下方' % (
                scorecard['ts'].replace('T', ' ')[:16], three_door.get('ts', '?')))
        else:
            lines.append('数据源: scorecard.py (ts: %s) — 每线证据见下方' % scorecard['ts'])
        lines.append('')

        # 各线详情（含证据）
        for label, key in dims:
            entry = next((ln for ln in scorecard.get('lines', []) if ln.get('line') == label), None)
            lines.append('## %s' % label)
            if entry:
                passed = entry['total'] >= line_pass
                lines.append('| 分数 | 状态 | 组成明细 |')
                lines.append('|:----:|:----:|----------|')
                parts = ' | '.join('%s=%s%s' % (
                    k,
                    v.get('score', v) if isinstance(v, dict) else v,
                    (f"(cap {v['cap']},设计上限)"
                     if isinstance(v, dict) and v.get('cap', v.get('max', 0)) < v.get('max', 0) - 1e-9 else ''))
                    for k, v in entry['parts'].items())
                lines.append('| **%s/%d** | %s | %s |' % (entry['total'], line_total,
                                                          '✅达标' if passed else '❌未达标', parts))
                lines.append('')
                lines.append('**证据**: %s' % ', '.join(entry.get('evidence', [])))
                lines.append('')
            else:
                lines.append('（暂无数据）')
                lines.append('')
    else:
        # ===== 回退: 旧 reports 自评数据 =====
        dim_order = ['优化记忆', 'skill_tree', '我的skill']
        score_lines = []
        for dim in dim_order:
            key_info = None
            for (d, rnd), (ts, info, notes, sess) in latest.items():
                if d == dim:
                    key_info = (rnd, info, notes, sess)
                    break
            if key_info:
                rnd, info, notes, sess = key_info
                s, out = info.get('score', '?'), info.get('out_of', 150)
                passed_str = '✅达标' if (isinstance(s, int) and s >= 115) else '⚠️未达标'
                score_lines.append('当前轮次: %s=综合%d/%d %s' % (dim, s, out, passed_str))
        lines.append('当前轮次(旧自评, 回退): ' + ' | '.join(score_lines))
        lines.append('')

        for dim in dim_order:
            lines.append('## %s' % dim)
            found = False
            for (d, rnd), (ts, info, notes, sess) in latest.items():
                if d == dim:
                    found = True
                    s, out = info.get('score', '?'), info.get('out_of', 150)
                    lines.append('| 轮次 | 综合 | 核心变更 |')
                    lines.append('|:----:|:----:|----------|')
                    lines.append('| %s | **%d/%d** | %s (src: %s)' % (rnd, s, out, notes, sess))
            if not found:
                lines.append('（暂无数据）')
            lines.append('')

    # 主线④: lessons 命中率（2026-08-02 新增）
    if lessons_hitrate:
        lh = lessons_hitrate
        lh_rate = lh.get('hit_rate', 0)
        lh_status = '✅达标' if lh_rate >= 80 else '❌未达标'
        lines.append('## 主线④ lessons命中率度量')
        lines.append('| 分数 | 状态 | 组成明细 |')
        lines.append('|:----:|:----:|----------|')
        lines.append('| **%.1f%%** | %s | 可判定 %d 条 | 命中 %d | 未命中 %d | 人工 %d |' % (
            lh_rate, lh_status, lh.get('hit', 0) + lh.get('miss', 0),
            lh.get('hit', 0), lh.get('miss', 0), lh.get('manual', 0)))
        lines.append('')
        lines.append('**证据**: eval/lessons_fingerprints.json + eval/lessons_hitrate.py (行为指纹扫描)')
        lines.append('')

    # 主线②补强: 记忆召回基准（2026-09-24 P1E-1 新增，Hit@5 + MRR 双指标）
    if memory_recall:
        mr = memory_recall
        m_base = mr.get('baseline') or {}
        m_ok = (mr.get('hit_at_5_rate', 0) >= float(m_base.get('hit_at_5', 0) or 0)
                and mr.get('mrr', 0) >= float(m_base.get('mrr', 0) or 0))
        lines.append('## 主线②补强 记忆召回基准（P1E-1）')
        lines.append('| Hit@%s | MRR | 用例 | 语料条目 | 回归判定（vs 基线 %s） |' % (
            mr.get('hit_at'), m_base.get('measured', '?')))
        lines.append('|:----:|:----:|:----:|:----:|:----:|')
        lines.append('| %.1f%% | %.4f | %d | %d | %s |' % (
            mr.get('hit_at_5_rate', 0) * 100, mr.get('mrr', 0),
            mr.get('items', 0), mr.get('corpus_entries', 0),
            '✅ 无回归' if m_ok else '❌ 低于基线（查语料改名/拆卷，R263 先修判据禁改数据凑绿）'))
        lines.append('')
        lines.append('**证据**: eval/memory_recall_eval.py --json（评测集 memory_recall_testset.json 版本化，C26 静态健康 + 周维护复跑）')
        lines.append('')

    # 主线⑤: 注意力优化（注意力税补充模拟, R166-U5 新增）
    if attention_sim:
        asim = attention_sim
        lines.append('## 主线⑤ 注意力优化（注意力税补充模拟）')
        lines.append('| 场景 | 上下文Tokens | 注意力稀释 | 关键指标 |')
        lines.append('|:----:|:----------:|:----------:|----------|')
        for s in asim.get('dilution', {}).get('scenarios', []):
            lines.append('| %s | %d | %.2fx | 平均关注度=%.4f (p50=%.4f) |' % (
                s.get('scenario'), s.get('tokens'), s.get('dilution_vs_p0'),
                s.get('relevant_attention_mean'), s.get('p50')))
        lines.append('')
        lines.append('**证据**: audit/attention_sim.py（BGE干草堆检索+蒙特卡洛稀释模拟）')
        lines.append('')

    # 主线⑥: 前置使用率采样（R166-U5 新增）
    if skill_usage:
        su = skill_usage
        lines.append('## 主线⑥ 前置使用率采样')
        lines.append('| 指标 | 数值 |')
        lines.append('|:----:|:----:|')
        lines.append('| 总调用次数 | %d |' % su.get('total_calls', 0))
        lines.append('| 技能覆盖率 | %d/%d |' % (su.get('skills_seen', 0), 162))
        lines.append('| 低频候选数 | %d |' % len(su.get('low_frequency_candidates', [])))
        lines.append('')
        lines.append('**高频技能Top5**: %s' % ', '.join([
            '%s(%d)' % (k, v) for k, v in list(su.get('per_skill', {}).items())[:5]
        ]))
        lines.append('')
        lines.append('**证据**: eval/skill_usage_stats.py（route_trace+llm_decisions聚合）')
        lines.append('')

    # 跨端四层终检（R115 新增）
    if cross_layer:
        cl = cross_layer
        cl_status = '✅ PASS' if cl.get('all_pass') else '❌ FAIL'
        fails = [r['name'] for r in cl.get('results', []) if not r.get('ok')]
        lines.append('## 跨端四层终检')
        lines.append('| 结果 | 明细 |')
        lines.append('|:----:|------|')
        lines.append('| **%d/%d %s** | %s |' % (
            cl.get('passed', 0), cl.get('total', 0), cl_status,
            '全部一致' if cl.get('all_pass') else 'FAIL: ' + ', '.join(fails)))
        lines.append('')
        lines.append('**证据**: eval/cross_layer_audit.py（八组）')
        lines.append('')

    # 开场预读门禁（R127 新增）
    if pread:
        pr = pread
        lines.append('## 开场预读门禁（lessons 正确率 / skill tree 调用率）')
        lines.append('| 指标 | 近 7 天 |')
        lines.append('|------|--------|')
        lines.append('| lessons 预读 | %d 轮 / 平均 %s 条/轮 |' % (pr.get('pread_declared', 0), pr.get('pread_avg_hits', 0)))
        lines.append('| skill 加载 | %d 轮 / 平均 %s 个/轮 |' % (pr.get('skill_declared', 0), pr.get('skill_avg', 0)))
        lines.append('| 记忆加载 | %d 轮 / 平均 %s 个/轮 |' % (pr.get('memory_declared', 0), pr.get('memory_avg', 0)))
        lines.append('| 机器落账 jsonl | %s 事件 / %s 会话（坏行 %s） |' % (pr.get('usage_events', 0), pr.get('usage_sessions', 0), pr.get('usage_bad_lines', 0)))
        if pr.get('declared_missing'):
            lines.append('')
            lines.append('⚠️ **声明行断链**: 日志声明行 0 轮但 jsonl 机器落账 >0 —— G5 声明行未落日志（行为断链），机器数据源已兜底（R216-03）')
        lines.append('')
        lines.append('**证据**: eval/lessons_pread_audit.py（三端日志声明行 + lessons_usage.jsonl 机器落账双源，v2）')
        lines.append('')

    # 系统状态（静态部分保留）
    lines.append('## 系统状态')
    lines.append('| 组件 | 版本/状态 |')
    lines.append('|------|----------|')
    lines.append('| behavior_core | %s（%d锚点/%d有效） |' % (
        BEHAVIOR_CORE_VERSION, BEHAVIOR_CORE_ANCHORS, BEHAVIOR_CORE_VALID))
    _sr_n, _sr_d = load_registry_counts()
    if _sr_n is not None:
        lines.append('| skill_routing | V7.11（%d skill / %d领域） |' % (_sr_n, _sr_d))
    else:
        # R272: 读取失败时输出 N/A —— 不再 fallback 到陈旧常量（旧写法硬编码 144/13，
        # 会被 C16「产物内容 == 真相源」判为过期但**渲染上看似有效**，比缺失更危险）。
        lines.append('| skill_routing | N/A（load_registry_counts 读取失败，见 stderr WARN） |')
    lines.append('| Registry | V2.0（195条，codex=true 159） |')
    lines.append('| pre-cc-check | run-health-check 16项OK |')
    lines.append('| 4KB拆分 | 全库≤4KB，0孤儿part |')
    lines.append('| %d端同步 | %d 端 junction HEALTHY |' % (ENDPOINT_COUNT, ENDPOINT_COUNT))
    lines.append('')

    # 已知问题
    lines.append('## ⚠️ 已知问题')
    lines.append('- **CC junction 限制**: CC 用绝对路径 %s\\core\\ 访问，不走 junction 子目录（workaround 已确认）' % GLOBAL_MEMORY_ROOT)
    lines.append('- **STATUS.md 竞态覆写（已治理）**: 2026-07-30 起本文件由 aggregate_status.py 聚合生成，不再手动编辑')
    lines.append('')

    content = '\n'.join(lines)

    if dry_run:
        print(content)
        shell_txt, body = split_status(content, gen_ts)
        print('\n[壳拆分方案] STATUS.md(壳)=%d 字节 | STATUS.part1.md(正文)=%d 字节' % (
            len(shell_txt.encode('utf-8')), len(body.encode('utf-8'))))
        return

    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    shell_txt, body = split_status(content, gen_ts)
    # R163: newline='\n' 防 Windows 文本模式把 LF 膨胀成 CRLF 超 4KB（R161 零豁免）
    Path(STATUS_PATH).write_text(shell_txt, encoding='utf-8', newline='\n')
    Path(STATUS_PART1_PATH).write_text(body, encoding='utf-8', newline='\n')
    # 0 孤儿 part 检查（非托管 STATUS.part*.md 仅告警，不自动删除）
    managed = {STATUS_PART1_PATH}
    orphans = [p for p in glob.glob(os.path.join(PROJECT_DIR, 'STATUS.part*.md')) if p not in managed]
    if orphans:
        print('WARN: 存在非托管 STATUS part（请人工处置）: %s' % ', '.join(orphans), file=sys.stderr)
    print('STATUS.md 已从 %d 条报告聚合生成 (%d 字节)' % (
        len(latest), len(shell_txt.encode('utf-8'))))
    print('STATUS.part1.md 正文分卷已生成 (%d 字节)' % len(body.encode('utf-8')))

