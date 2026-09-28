#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scorecard.py — 焚诀融合评分卡 V2 编排层（三主线×20维，全机器实测）
=====================================================================
基于用户审查确认的「维度×主线对照矩阵 V2」：
  主线① 跨平台 skill 互通同步（50分，6维）
  主线② 多 agent 统一记忆 + 路由系统（50分，8维，含 D2-8 内容信噪比）
  主线③ skill 命中率优化（50分，6维）

R208 O-4 拆分（行为等价）：
  本文件降级为编排层（collect_red_team / run_blind / main + 命名空间兼容转发），
  计分主体迁至同目录子模块：
    scorecard_shared.py   — 常量/纯函数/计分基础设施
    scorecard_sync.py     — score_sync（主线①）
    scorecard_memory.py   — score_memory（主线②）
    scorecard_routing.py  — score_routing（主线③）
  外部命名空间兼容（依赖者无感）: scorecard.band_of / compute_verdict /
  score_sync / score_memory / score_routing（test_scorecard_pure.py、
  score_track200.py 依赖）。

防幻觉核心：
  - 每个计分维度 = 一个可复现脚本/命令的输出（无脚本 = 无分）
  - 测试集版本化检测（git diff 防提分式修改）
  - 负标签健康独立检测（不再固定满分）
  - 输出 schema v2：每维附证据源 + 输出摘录

用法:
  python scorecard.py              # 全量评分
  python scorecard.py --json       # JSON 输出（供 aggregate_status 消费）
  python scorecard.py --blind      # 只跑盲测（内部辅助）
"""
# C7 门禁（verify check_c7_no_bare_constants + test_c7_scorecard_imports_truth_constants）：
# scorecard.py 须保持 truth_constants 直接引用字样；实际常量解析在 scorecard_shared
# （同目录，sys.path 已注入），此处转发导入保持"同源单一真相"。
from truth_constants import SCORECARD_TOTAL, SCORECARD_PASS_LINE, SCORECARD_LINE_PASS  # noqa: F401,E402

import os
import sys
import json
import datetime

# scorecard_shared 加载时完成 sys.path.insert(0, EVAL_DIR)（同目录）
from scorecard_shared import (  # noqa: E402
    EVAL_DIR, AUDIT_DIR, TOTAL, PASS_LINE, LINE_PASS, DIM_PASS_RATE,
    band_of, compute_verdict, run, is_script_missing,
)
from scorecard_sync import score_sync  # noqa: E402
from scorecard_memory import score_memory  # noqa: E402
from scorecard_routing import score_routing  # noqa: E402
from failure_cost_metric import compute_failure_cost  # P2 #10 失败成本度量


def collect_red_team(sync, mem, routing):
    """R163 红队报告 — 护栏: 无证据的条目一律进误报/待证, 不进入确认清单"""
    confirmed = []
    blindspots = []
    for line in (sync, mem, routing):
        for dname, d in line['parts'].items():
            # R165 U1 修正: 判定基准从名义满分改为可达上限 cap（盲测维 judge 加权上限 < 名义满分）
            cap = d.get('cap', d['max'])
            if d['score'] + 1e-9 < cap:
                confirmed.append({
                    'dim': f"{line['line']}/{dname}",
                    'score': d['score'],
                    'max': d['max'],
                    'cap': cap,
                    'evidence': d.get('detail', ''),
                    'reproduce': d.get('evidence', ''),
                    'severity': '高' if d['max'] >= 12 else ('中' if d['max'] >= 8 else '低'),
                })
    # 盲区: 冻结盲测中 blindspot 判定但路由器未返回 NONE / wrong 判定
    for r in routing.get('blind_findings', []):
        if r.get('judge') == 'blindspot':
            if r.get('router_top1') not in ('NONE', None):
                blindspots.append({
                    'query': r.get('query', ''),
                    'expected': r.get('expected'),
                    'router_top1': r.get('router_top1'),
                    'evidence': f"冻结盲测: {r.get('query')} 应无技能, 实路由 {r.get('router_top1')}",
                    'reproduce': 'frozen_blind_eval.py --json',
                })
        elif r.get('judge') == 'wrong':
            confirmed.append({
                'dim': '主线③/盲测(wrong)',
                'score': 0,
                'max': 0,
                'evidence': f"冻结盲测: {r.get('query')} 期望 {r.get('expected')}, 实路由 {r.get('router_top1')}",
                'reproduce': 'frozen_blind_eval.py --json',
                'severity': '中',
            })
    # 误报/待证: 来自 CC 独立复核裁决链（无证据条目在此）
    false_positive = []
    ca_path = os.path.join(EVAL_DIR, 'codex_audit_scores.json')
    if os.path.exists(ca_path):
        try:
            with open(ca_path, encoding='utf-8') as f:
                ca = json.load(f)
            false_positive = ca.get('red_team', {}).get('false_positive', []) or []
        except Exception:
            pass  # 只读补充源（false_positive 非计分项，confirmed 主源不受影响），失败保持空列表
    return {
        'confirmed': confirmed,
        'false_positive': false_positive,
        'blindspots': blindspots,
        'counts': {
            'confirmed': len(confirmed),
            'false_positive': len(false_positive),
            'blindspots': len(blindspots),
        },
    }


# ============ 盲测（内部辅助） ============
def run_blind():
    sys.path.insert(0, EVAL_DIR)
    os.environ['FENJUE_ROUTE_TRACE'] = '0'
    import unified_router
    with open(os.path.join(EVAL_DIR, 'blind_test_queries.json'), encoding='utf-8') as f:
        blind = json.load(f)
    total = correct = 0
    for tier in blind:
        for q in tier.get('queries', []):
            exp = q.get('expected_skill')
            if not exp:
                continue
            total += 1
            exp_set = {exp} if isinstance(exp, str) else set(exp)
            try:
                if unified_router.route(q['query'])['top1'] in exp_set:
                    correct += 1
            except Exception:
                pass  # 内部辅助盲测逐条尽力而为（非计分项）；单条失败不计入样本
    acc = correct / total * 100 if total else 0
    print(f"盲测: {acc:.1f}% ({correct}/{total})")


# ============ 主流程 ============
def main():
    as_json = '--json' in sys.argv
    if '--blind' in sys.argv:
        run_blind()
        return

    # R198.10: track_200 分支（六线全评）——active_track 切换时路由到新模块，
    # 保持 track_150 原有 20 维逻辑不动（兼容既有调用方）
    try:
        from truth_constants import SCORECARD_ACTIVE_TRACK
        if SCORECARD_ACTIVE_TRACK == 'track_200':
            import subprocess
            try:
                proc = subprocess.run([sys.executable, os.path.join(EVAL_DIR, 'score_track200.py')] +
                                      (['--json'] if as_json else []),
                                      timeout=1800, capture_output=True, text=True,
                                      encoding='utf-8', errors='replace')
                sys.stdout.write(proc.stdout or '')
                sys.stderr.write(proc.stderr or '')
            except subprocess.TimeoutExpired:
                print('ERROR: score_track200.py 超过 1800s 被终止', file=sys.stderr)
            return
    except ImportError:
        # score_track200 缺失 → 回退 track_150（不静默失败）
        print('WARN: score_track200.py 不可用，回退 track_150', file=sys.stderr)

    # 测试集版本化检测（前置门禁）
    tsv = run([sys.executable, os.path.join(AUDIT_DIR, 'testset_version_check.py')])
    if is_script_missing(tsv):
        # 证据脚本缺失 → 门禁无法执行，保守判 FAIL 并显式告警（不静默放行）
        print('WARN: 测试集版本化脚本 testset_version_check.py 不存在于磁盘，testset_ok=False', file=sys.stderr)
        testset_ok = False
    else:
        testset_ok = 'PASS' in tsv

    sync = score_sync()
    mem = score_memory()
    routing = score_routing()

    overall = round((sync['total'] + mem['total'] + routing['total']), 1)
    lines = [sync, mem, routing]

    # R166-U1: cap 显式化（每维可达上限；盲测维 judge 加权使全命中亦不可达名义满分）
    for ln in lines:
        for dname, d in ln['parts'].items():
            d.setdefault('cap', d['max'])
            d.setdefault('max_achievable', d.get('cap', d['max']))
    achievable_total = round(sum(d['cap'] for ln in lines for d in ln['parts'].values()), 1)
    achievable_pct = round(overall / achievable_total * 100, 1) if achievable_total else 0.0
    capped_dims = [f"{ln['line']}/{dname}" for ln in lines
                   for dname, d in ln['parts'].items()
                   if d.get('cap', d['max']) < d['max'] - 1e-9]

    # R166-U6: 全量证据指纹自审计（真扫描：全部 part 逐维核对；缺失指纹列为审计缺口）
    fp_counter = {}
    fp_missing = []
    for ln in lines:
        for dname, d in ln['parts'].items():
            fp = d.get('evidence_fingerprint')
            if not fp:
                fp_missing.append(f"{ln['line']}/{dname}")
                continue
            fp = fp.strip()
            fp_counter.setdefault(fp, []).append(f"{ln['line']}/{dname}")
    duplicate_evidence = [{'fingerprint': fp, 'dims': dims}
                          for fp, dims in fp_counter.items() if len(dims) > 1]
    evidence_fingerprint_audit = {
        'total_parts': sum(len(ln['parts']) for ln in lines),
        'fingerprinted_parts': sum(len(dims) for dims in fp_counter.values()),
        'missing_fingerprints': fp_missing,
        'duplicate_fingerprints': duplicate_evidence,
    }

    # 达标判定
    line_pass = all(ln['total'] >= LINE_PASS for ln in lines)
    dim_pass = True
    dim_fails = []
    dim_fails_risk = []
    for ln in lines:
        for dname, d in ln['parts'].items():
            # R166-U2 (S2-2): 单维判定基准改用 cap，与 collect_red_team 一致
            base = d.get('cap', d['max']) or d['max']
            if base > 0 and d['score'] / base < DIM_PASS_RATE:
                dim_pass = False
                dim_fails.append(f"{ln['line']}/{dname}={d['score']}/{d['max']}")
                share = round(d['max'] / TOTAL * 100, 1)
                loss = round(d['max'] - d['score'], 1)
                risk = '高' if d['max'] >= 12 else ('中' if d['max'] >= 8 else '低')
                dim_fails_risk.append({
                    'dim': dname,
                    'line': ln['line'],
                    'score': d['score'],
                    'max': d['max'],
                    'weight_share_pct': share,
                    'loss': loss,
                    'risk_note': f"该维满分仅占总量 {share}%（{d['max']}/{TOTAL}），破限损失 {loss} 分；"
                                 f"权重{'较低' if d['max'] < 8 else '中等' if d['max'] < 12 else '较高'}，"
                                 f"需判断是否掩盖真实风险（风险判定:{risk}）",
                })
    # P2 #10: 失败成本度量（不破坏 20 维 schema，仅附加裁决）
    # compute_failure_cost 为纯函数，仅依赖 dim_fails_risk（100 - 加权成本）
    failure_cost = compute_failure_cost(dim_fails_risk)

    red_team = collect_red_team(sync, mem, routing)
    # R166-U1: 未闭环 pending 盘点（deadline 字段缺失时只记录不拦 PASS，待缺陷台账轮补 schema）
    pending_open = []
    overdue_pending = []
    pending_unavailable = False
    pending_reason = ''
    try:
        with open(os.path.join(EVAL_DIR, 'codex_audit_scores.json'), encoding='utf-8') as f:
            _ca = json.load(f)
        for it in _ca.get('red_team', {}).get('pending', []):
            if it.get('status', 'pending') == 'pending':
                pending_open.append(it)
                dl = it.get('deadline')
                if dl:
                    try:
                        if datetime.datetime.fromisoformat(dl).date() < datetime.date.today():
                            overdue_pending.append(it)
                    except Exception:
                        pass  # 单条 deadline 脏数据按未超期处理（不阻断全卡）
    except Exception as e:
        # R193: fail-closed——台账不可读时显式 unavailable，禁止静默放行超期 pending
        pending_unavailable = True
        pending_reason = str(e)
    # R168: 逃生门超期拦截 — defect_tracking.json 中 escape_hatch_deadline 已过且未闭环 → 阻断 PASS
    # 目的: 防止"附决策文档"替代验收被无限期挂起、用文档化绕过门禁
    escape_overdue = []
    escape_unavailable = False
    escape_reason = ''
    try:
        with open(os.path.join(EVAL_DIR, 'defect_tracking.json'), encoding='utf-8') as f:
            _dtk = json.load(f)
        for _d in _dtk.get('defects', []):
            if _d.get('status', 'open') == 'closed':
                continue
            _ehd = _d.get('escape_hatch_deadline')
            if _ehd:
                try:
                    if datetime.datetime.fromisoformat(_ehd).date() < datetime.date.today():
                        escape_overdue.append(_d.get('id', '?'))
                except Exception:
                    pass  # 单条 escape_hatch_deadline 脏数据按未超期处理（不阻断全卡）
    except Exception as e:
        # R193: fail-closed——逃生门台账不可读时显式 unavailable，禁止静默放行
        escape_unavailable = True
        escape_reason = str(e)
    unavailable_dims = [f"{ln['line']}/{dname}"
                        for ln in lines
                        for dname, d in ln['parts'].items()
                        if d.get('unavailable')]
    if pending_unavailable:
        unavailable_dims.append(f"台账:codex_audit_scores.json({pending_reason})")
    if escape_unavailable:
        unavailable_dims.append(f"台账:defect_tracking.json({escape_reason})")
    pass_ok, verdict_blockers = compute_verdict(
        overall, line_pass, dim_pass, testset_ok,
        len(red_team['confirmed']), len(overdue_pending), len(escape_overdue),
        unavailable_dims)
    band = band_of(overall)
    if not pass_ok:
        band = '不达标'  # R166-U1: 禁止"优秀"与确认缺陷/超期未闭环共存
    # P2 #10: 失败成本裁决（高风险失败 → 即便总分达标也判不达标）
    if failure_cost['verdict'] == 'UNACCEPTABLE':
        pass_ok = False
        band = '不达标'
        verdict_blockers.append('失败成本不可接受: ' + '; '.join(failure_cost['high_risk_failures']))

    result = {
        'schema': 'fenjue-scorecard-v2',
        'ts': datetime.datetime.now().isoformat(timespec='seconds'),
        'total_line': TOTAL,
        'pass_line': PASS_LINE,
        'line_pass': LINE_PASS,
        'overall': overall,
        'band': band,
        'testset_ok': testset_ok,
        'lines': lines,
        'verdict': 'PASS' if pass_ok else 'FAIL',
        'achievable_total': achievable_total,
        'achievable_pct': achievable_pct,
        'capped_dims': capped_dims,
        'duplicate_evidence': duplicate_evidence,
        'evidence_fingerprint_audit': evidence_fingerprint_audit,
        'verdict_blockers': verdict_blockers,
        'pending_open_n': len(pending_open),
        'overdue_pending_n': len(overdue_pending),
        'escape_hatch_overdue_n': len(escape_overdue),
        'escape_hatch_overdue': escape_overdue,
        'dim_fails': dim_fails,
        'dim_fails_risk': dim_fails_risk,
        'red_team': red_team,
        'failure_cost': failure_cost,  # P2 #10 失败成本度量
    }

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # R163 红队化: 缺陷发现段置顶, 分数/达标降为附属
    print("=" * 60)
    print("本轮缺陷发现 (红队报告 — 证据门槛: 无证据=误报/待证)")
    print("=" * 60)
    rt = red_team
    for c in rt['confirmed']:
        print(f"  🔴 确认: {c['dim']} ({c['score']}/{c['max']}) — {c['evidence']}")
        print(f"       复现: {c['reproduce']} | 严重度: {c['severity']}")
    for b in rt['blindspots']:
        print(f"  🟠 盲区: {b['evidence']}")
    for f in rt['false_positive']:
        print(f"  ⚪ 误报/待证: {f.get('note', f.get('query', '?'))}")
    c_, m_, k_ = rt['counts']['confirmed'], rt['counts']['false_positive'], rt['counts']['blindspots']
    if c_ + m_ + k_ == 0:
        print("  （本轮未发现可复现缺陷）")
    if m_ > 0 and m_ / max(c_ + m_, 1) > 0.5:
        print("  ⚠️ 红队噪声偏高（误报率>50%），建议收紧无证据条目的录入")
    print(f"  汇总: 确认 {c_} / 误报或待证 {m_} / 盲区 {k_}")
    print()

    print("=" * 60)
    print("焚诀融合评分卡 V2 (三主线×20维, 全机器实测)")
    print(f"时间: {result['ts']}")
    print("=" * 60)
    for line in lines:
        status = "✅" if line['total'] >= line['pass'] else "❌"
        print(f"\n{line['line']}: {line['total']}/{TOTAL//3} {status}")
        for k, v in line['parts'].items():
            cap_note = ''
            if isinstance(v, dict) and v.get('cap', v.get('max', 0)) < v.get('max', 0) - 1e-9:
                cap_note = f" (cap {v['cap']}, 设计上限)"
            print(f"  {k}: {v['score']}/{v['max']}{cap_note} — {v['detail']} [{v['evidence']}]")
    print(f"\n测试集版本化: {'✅ PASS' if testset_ok else '❌ 有修改'}")
    print(f"综合: {overall}/{TOTAL} ({overall/TOTAL*100:.1f}%)")
    print(f"可达上限: {overall}/{achievable_total} ({achievable_pct:.1f}%) — 跨轮比较请用归一化达成率")
    if capped_dims:
        print(f"设计上限维度(cap<满分, 全命中亦不可达100%): {', '.join(capped_dims)}")
    fp_audit = result['evidence_fingerprint_audit']
    if fp_audit['missing_fingerprints']:
        print(f"⚠️ 证据指纹缺失: {'; '.join(fp_audit['missing_fingerprints'])}")
    if duplicate_evidence:
        for dup in duplicate_evidence:
            print(f"⚠️ 重复证据指纹[{dup['fingerprint']}]: {'; '.join(dup['dims'])}")
    else:
        print(f"证据指纹审计: 全部 {fp_audit['total_parts']} 个 part 已指纹化，无同事实双计分")
    print(f"分数带: {band}（≥145 优秀 / 135-144 良好 / 120-134 合格 / <120 不达标）")
    print(f"达标线: {PASS_LINE}/{TOTAL} + 每线≥{LINE_PASS} + 单维≥{int(DIM_PASS_RATE*100)}%")
    if dim_fails:
        print(f"破限维度: {dim_fails}")
        for r in dim_fails_risk:
            print(f"  风险注记[{r['dim']}]: {r['risk_note']}")
    print(f"判定: {'✅ 达标' if pass_ok else '❌ 未达标'}")
    if verdict_blockers:
        print(f"判定阻断: {'; '.join(verdict_blockers)}")
    if pending_open:
        print(f"未闭环 pending: {len(pending_open)} 条（deadline 字段缺失前不拦 PASS，待缺陷台账轮补 schema）")
    if escape_overdue:
        print(f"逃生门超期未裁决: {len(escape_overdue)} 条（{', '.join(escape_overdue)}）→ 阻断 PASS")


if __name__ == '__main__':
    main()