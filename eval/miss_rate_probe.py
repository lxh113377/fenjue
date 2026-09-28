#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
miss_rate_probe.py — 漏检率探针（R166-U3）
============================================
输入 = 已知缺陷 query 集（codex_audit_scores.json 的 pending + blindspots + 曾 confirmed）
输出 = 每条判定结果 + miss_count / total / miss_rate / recall

背景：旧系统只统计误报（CC 复核一致率 66.7%、误报率 90%），从不统计漏检，
无法回答"路由到底漏掉了多少真实缺陷"。本探针把已知缺陷当"该被系统发现的真值"，
实测路由器是否给出正确应答（命中期望技能，或对无技能项显式返回 NONE）。

用法:
  python miss_rate_probe.py            # 文本输出
  python miss_rate_probe.py --json     # JSON 输出
"""
import json
import os
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIT_PATH = os.path.join(EVAL_DIR, 'codex_audit_scores.json')
JUDGMENTS_PATH = os.path.join(EVAL_DIR, 'codex_blind_judgments.json')


def load_audit():
    with open(AUDIT_PATH, encoding='utf-8') as f:
        return json.load(f)


def load_judgments():
    with open(JUDGMENTS_PATH, encoding='utf-8') as f:
        return json.load(f)


def build_probe_set():
    """已知缺陷 query 集：pending(8 真 + 1 refuted) + blindspots(2) + 曾 confirmed(2)。
    期望口径 = 当前定案（R158/R164）：有可用技能的指向该技能；无专用技能的期望显式 NONE。"""
    audit = load_audit()
    judgments = load_judgments()
    jmap = {e['id']: e for e in judgments.get('entries', [])}

    # 曾 confirmed（R164 修复后对齐，用于回归验证"漏检已闭合"；R201 frontend-design 已删→frontend-skill）
    prev_confirmed = [
        ('cc-6', 'frontend-skill'),
        ('hermes-2', 'ui-ux-pro-max'),
    ]

    # pending 的定案期望（含 refuted）
    pending_expect = {
        'oc-4': None,            # R158 定案：显式 NONE
        'oc-5': 'chart-visualization',   # R158 直连决策
        'oc-10': 'video-whisper-transcribe',  # R164 入口=转写（可用级）
        'cc-3': None,            # 缺记忆树配置向导：期望显式 NONE
        'cc-8': 'canvas-design', # R158 多步内容创作决策
        'cc-10': 'A-get-memory', # R158 修复项
        'hermes-3': None,        # 缺思维导图专用技能：期望显式 NONE
        'hermes-8': None,        # 缺海报专用技能：期望显式 NONE
        'hermes-4': 'tencent-cos-skill__skillhub',  # refuted：对象存储技能存在
    }
    probe = []
    for item in audit.get('red_team', {}).get('pending', []):
        pid = item.get('id')
        exp = pending_expect.get(pid, 'UNKNOWN')
        probe.append({
            'id': pid,
            'kind': 'refuted' if item.get('status') == 'refuted' else 'pending',
            'query': item.get('query', ''),
            'expected': exp,
            'acceptance': 'explicit NONE' if exp is None else f'route hit {exp}',
            'note': item.get('weakness') or item.get('note') or '',
        })

    for item in audit.get('red_team', {}).get('blindspots', []):
        probe.append({
            'id': 'blindspot:' + item.get('query', '')[:12],
            'kind': 'blindspot',
            'query': item.get('query', ''),
            'expected': 'A-get-memory' if '习惯' in item.get('query', '') else None,
            'acceptance': '',
            'note': item.get('note', ''),
        })

    for pid, exp in prev_confirmed:
        e = jmap.get(pid)
        if not e:
            continue
        probe.append({
            'id': pid,
            'kind': 'prev_confirmed',
            'query': e.get('query', ''),
            'expected': exp,
            'acceptance': f'route hit {exp}',
            'note': e.get('reason', ''),
        })
    return probe


def run_router(query):
    """进程内路由（与 frozen_blind_eval 同源：unified_router.route）"""
    try:
        os.environ['TRANSFORMERS_VERBOSITY'] = 'error'
        os.environ['FENJUE_ROUTE_TRACE'] = '0'
        sys.path.insert(0, EVAL_DIR)
        import unified_router
        r = unified_router.route(query)
        return r.get('top1')
    except Exception as e:  # pragma: no cover - 环境异常保护
        return 'ROUTER_ERROR:' + str(e)[:60]


def is_hit(top1, expected):
    if expected is None:
        return top1 in (None, 'NONE', '')
    return top1 == expected


def probe():
    rows = []
    for p in build_probe_set():
        top1 = run_router(p['query'])
        hit = is_hit(top1, p['expected'])
        rows.append({**p, 'router_top1': top1, 'hit': bool(hit)})
    total = len(rows)
    miss = sum(1 for r in rows if not r['hit'])
    return {
        'schema': 'fenjue-miss-rate-probe-v1',
        'ts': '2026-08-03',
        'total': total,
        'miss_count': miss,
        'miss_rate': round(miss / total * 100, 1) if total else 0.0,
        'recall': round((total - miss) / total * 100, 1) if total else 0.0,
        'rows': rows,
        'note': '漏检率与误报率同报：CC 复核误报率 90%（9/10 分歧判为 codex_ok），漏检率=本探针 miss/total',
    }


if __name__ == '__main__':
    as_json = '--json' in sys.argv
    r = probe()
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0)
    print('=' * 72)
    print(f"漏检率探针: 总 {r['total']} 条 | miss {r['miss_count']} | 漏检率 {r['miss_rate']}% | recall {r['recall']}%")
    print('=' * 72)
    for row in r['rows']:
        mark = '✅' if row['hit'] else '❌'
        exp = row['expected'] if row['expected'] is not None else 'NONE'
        print(f"{mark} [{row['kind']}] {row['id']} | {row['query'][:32]}")
        print(f"    期望: {exp} | 实路由: {row['router_top1']}")
    print('=' * 72)
    print(r['note'])
