#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_disambiguation.py — 可读消歧表自生成器（BitFun SkillTree 借鉴 #2）

输入:
  <MEMORY_ROOT>\\skill_content\\{domain}.json   (desc + triggers)
  eval/route_trace.jsonl                            (needs_llm 历史证据，可选，加权)

输出:
  eval/disambiguation_pairs.json                    (路由注入用，llm_layer 读取)
  <MEMORY_ROOT>\\skill_content\\disambiguation_table.md (人工可读/审计)

用法:
  python skill/tools/generate_disambiguation.py
  生成后必须分卷（4KB 零豁免）: python skill/tools/split_md_4kb.py split <MEMORY_ROOT>\\skill_content\\disambiguation_table.md
"""
import json
import os
import re
import sys
import glob
from collections import Counter, defaultdict
from pathlib import Path

SKILL_CONTENT = r'<MEMORY_ROOT>\skill_content'
EVAL_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'eval'))
ROUTE_TRACE = os.path.join(EVAL_DIR, 'route_trace.jsonl')
OUT_JSON = os.path.join(EVAL_DIR, 'disambiguation_pairs.json')
OUT_MD = os.path.join(SKILL_CONTENT, 'disambiguation_table.md')

# R194: 人工维护消歧对（自动阈值覆盖不到，但路由实测需要）。
# 每周重生成时与自动对子合并去重——勿删，否则下次生成会丢这条规则。
MANUAL_PAIRS = [
    {
        'a': 'A-prompt-better',
        'b': 'A-ask-questions',
        'domain_a': 'memory',
        'domain_b': 'memory',
        'score': 2.0,
        'priority': 'high',
        'trigger_overlap': 0,
        'desc_jaccard': 0.3,
        'trace_weight': 0,
        'shared_triggers': [],
        'use_a_when': '优化/润色提示词、prompt 措辞改进',
        'use_b_when': '规划方案/项目计划/需求澄清（动手前对齐）',
    },
]


def norm(s):
    return re.sub(r"[\s，。、！？；：（）()\-_/\\]+", '', (s or '').lower())


def bigrams(s):
    t = norm(s)
    return {t[i:i + 2] for i in range(max(0, len(t) - 1))}


def jaccard(a, b):
    sa, sb = bigrams(a), bigrams(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def load_skills():
    skills = {}
    for p in glob.glob(os.path.join(SKILL_CONTENT, '*.json')):
        domain = os.path.basename(p)[:-5]
        if domain in ('skill_ids', 'domain_map'):
            continue
        try:
            data = json.loads(Path(p).read_text(encoding='utf-8'))
        except Exception:
            continue
        items = data.get('skills', data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            continue
        for s in items:
            if not isinstance(s, dict) or not s.get('name'):
                continue
            skills[s['name']] = {
                'name': s['name'],
                'domain': domain,
                'desc': s.get('desc', '') or s.get('description', ''),
                'triggers': [norm(x) for x in (s.get('triggers') or [])],
            }
    return skills


def load_trace_weights():
    """历史 needs_llm=true 的 Top-3 候选共现 → 给对应对子加权。"""
    weights = defaultdict(int)
    if not os.path.exists(ROUTE_TRACE):
        return weights
    try:
        with Path(ROUTE_TRACE).open(encoding='utf-8') as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if not row.get('needs_llm'):
                    continue
                cands = [c.get('name') for c in (row.get('candidates') or [])[:3] if c.get('name')]
                for a in cands:
                    for b in cands:
                        if a != b:
                            weights[(a, b)] += 1
                            weights[(b, a)] += 1
    except Exception:
        pass  # trace 读取失败 → 返回空权重（消歧候选退化为空，可接受；R207 P2-1 留痕）
    return weights


def diff_triggers(sk, other):
    other_set = set(other['triggers'])
    return [t for t in sk['triggers'] if t not in other_set][:3]


def fmt_use(sk, other):
    d = diff_triggers(sk, other)
    if d:
        return ' / '.join(d)
    return '(无独立触发词，按描述语义判断)'


def main():
    skills = load_skills()
    names = sorted(skills)
    weights = load_trace_weights()

    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a = skills[names[i]]
            b = skills[names[j]]
            shared = set(a['triggers']) & set(b['triggers'])
            trig_overlap = len(shared)
            dj = jaccard(a['desc'], b['desc'])
            same_dom = a['domain'] == b['domain']
            score = trig_overlap * 2.0 + dj
            if weights.get((a['name'], b['name'])):
                score += 0.5
            if not (trig_overlap >= 1 or (same_dom and dj >= 0.28) or dj >= 0.38):
                continue
            pairs.append({
                'a': a['name'],
                'b': b['name'],
                'domain_a': a['domain'],
                'domain_b': b['domain'],
                'score': round(score, 3),
                'priority': 'high' if (trig_overlap >= 1 or weights.get((a['name'], b['name']))) else ('medium' if same_dom else 'low'),
                'trigger_overlap': trig_overlap,
                'desc_jaccard': round(dj, 3),
                'trace_weight': weights.get((a['name'], b['name']), 0),
                'shared_triggers': sorted(shared)[:3],
                'use_a_when': fmt_use(a, b),
                'use_b_when': fmt_use(b, a),
            })

    pairs.sort(key=lambda x: -x['score'])
    # 去冗余：每个 skill 至多出现在前 6 个对子
    seen = Counter()
    kept = []
    for p in pairs:
        if seen[p['a']] >= 6 or seen[p['b']] >= 6:
            continue
        seen[p['a']] += 1
        seen[p['b']] += 1
        kept.append(p)

    # 合并人工对子（去重 + 排序，不受每技能 6 对上限约束）
    manual_keys = {frozenset((p['a'], p['b'])) for p in MANUAL_PAIRS}
    kept = [p for p in kept if frozenset((p['a'], p['b'])) not in manual_keys]
    kept.extend(MANUAL_PAIRS)
    kept.sort(key=lambda x: -x['score'])

    Path(OUT_JSON).write_text(
        json.dumps(kept, ensure_ascii=False, indent=2), encoding='utf-8')

    ts = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = [
        '# 可读消歧表（autogen — 勿手改，由 generate_disambiguation.py 生成）',
        '',
        f'> 生成时间: {ts} | 技能对: {len(kept)} | 来源: skill_content/*.json + route_trace.jsonl(needs_llm 加权)',
        '> 用途: unified_router needs_llm=true 时，llm_layer 将命中行注入 LLM 决策提示词，降低冷推理依赖、提高可审计性。',
        '> 优先级: high=共享触发词或历史 needs_llm 共现（真实歧义）| medium=同域高相似 | low=跨域高相似。',
        '',
        '| 优先级 | 技能 A | 技能 B | 域 | 重叠触发词 | 何时用 A | 何时用 B |',
        '|---|---|---|---|---|---|---|',
    ]
    for p in kept:
        dom = p['domain_a'] if p['domain_a'] == p['domain_b'] else f"{p['domain_a']}/{p['domain_b']}"
        shared = '、'.join(p['shared_triggers']) if p['shared_triggers'] else '-'
        lines.append(f"| {p['priority']} | {p['a']} | {p['b']} | {dom} | {shared} | {p['use_a_when']} | {p['use_b_when']} |")
    Path(OUT_MD).write_text('\n'.join(lines) + '\n', encoding='utf-8')

    print(f'总对子: {len(pairs)} -> 保留: {len(kept)}')
    print(f'JSON: {OUT_JSON}')
    print(f'MD:   {OUT_MD}')
    print('\nTop 10:')
    for p in kept[:10]:
        print(f"  {p['a']} vs {p['b']} (score={p['score']}, trig={p['trigger_overlap']}, jac={p['desc_jaccard']})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
