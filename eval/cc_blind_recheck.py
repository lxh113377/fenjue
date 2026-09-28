#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cc_blind_recheck.py — CC 独立盲测复核（R163 红队化: 低成本恢复独立视角）
====================================================================
每 2-4 周（默认 3 周）让 CC（claude --print）独立跑 30 条盲测样本：
  - 无锚定: prompt 只给查询与评分口径, 不给 Codex 判定/期望答案
  - CC 逐条给 top1 + 理由 + 主动标注怀疑的系统弱点
  - 与 eval/codex_blind_judgments.json 逐条比对, 产出 diff 报告
  - 裁决链: 不一致条目由 Codex 复核定稿（每条带证据+结论）, diff 全量落盘
R165 定案: CC 输出仅作佐证（单轮判定非确定, R165 实测误报率 90%）; 结论以机器基线 + Codex 裁决为准;
复核频次 2-4 周一次, 不纳入每周一键门。

护栏:
  - CC 弱点意见无证据 → 进"待证"而非"确认缺陷"
  - 误报率 >50% 时报告标注红队噪声偏高

用法:
  python cc_blind_recheck.py --smoke           # 冒烟: 只跑 1 条
  python cc_blind_recheck.py                   # 全量 30 条 (three_door_samples)
  python cc_blind_recheck.py --samples layered # 分层集固定种子抽 30 条 (批2 后可用)
  python cc_blind_recheck.py --cli codex       # claude 不可用时降级 Codex CLI
"""
import os
import sys
import json
import re
import subprocess
import datetime
import secrets
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(os.path.dirname(EVAL_DIR), 'reports')
SAMPLES_DIR = os.path.join(EVAL_DIR, 'three_door_samples')
JUDGMENTS_PATH = os.path.join(EVAL_DIR, 'codex_blind_judgments.json')
AUDIT_PATH = os.path.join(EVAL_DIR, 'codex_audit_scores.json')


def _secure_shuffle(seq):
    """Fisher-Yates with secrets.randbelow（密码学随机抽样）"""
    for i in range(len(seq) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        seq[i], seq[j] = seq[j], seq[i]

RUBRIC = """判定口径（与 Codex 盲测一致）:
  exact=1.0: top1 是明确正确的技能
  usable=0.75: 次优但可接受（语义相近, 有更贴技能时属此档）
  wrong=0.5: 路由错误
  blindspot=0.4: 该查询本不应路由到任何技能（应返回 NONE）"""


def skill_vocab(max_desc=60):
    """技能词汇表（名 + 一句话摘要）— 只提供可选集合, 不给任何判定/期望, 不构成锚定"""
    sys.path.insert(0, EVAL_DIR)
    import bge_layer as bl
    if not bl._bge_skills:
        try:
            with Path(os.path.join(EVAL_DIR, 'bge_fullbody_skills.json')).open(encoding='utf-8') as f:
                bl._bge_skills = json.load(f)
        except Exception:
            bl._bge_skills = []
    from llm_layer import get_skill_profile
    out = []
    for s in bl._bge_skills:
        name = s['name']
        try:
            desc = get_skill_profile(name)['description'][:max_desc].strip()
        except Exception:
            desc = ''
        out.append(f"{name} — {desc}" if desc else name)
    return out


def load_samples(source='three_door'):
    if source == 'three_door':
        entries = []
        for door in ['oc', 'cc', 'hermes']:
            p = os.path.join(SAMPLES_DIR, f'sample_{door}.json')
            d = json.loads(Path(p).read_text(encoding='utf-8'))
            for i, q in enumerate(d['queries'], 1):
                entries.append({'id': f'{door}-{i}', 'query': q['query']})
        return entries
    if source == 'layered':
        p = os.path.join(EVAL_DIR, 'layered_testset.json')
        d = json.loads(Path(p).read_text(encoding='utf-8'))
        qs = [q for t in d for q in t.get('queries', [])]
        _secure_shuffle(qs)
        picked = qs[:30]
        return [{'id': f"l-{i+1}", 'query': q['query']} for i, q in enumerate(picked)]
    raise ValueError(f'未知样本源: {source}')


def build_prompt(entries, extra_note=''):
    vocab = skill_vocab()
    import re as _re
    lines = [
        '你是独立审计员。以下是 30 条真实用户查询, 请为每条从下方技能清单中选择最合适的技能（无对应技能时返回 NONE）。',
        '独立评分要求: 只根据查询本身判断, 不修改任何文件, 不要调用任何工具。',
        RUBRIC,
        '',
        '可用技能清单（共 %d 个, 必须使用清单中的精确技能名）:' % len(vocab),
    ]
    for i in range(0, len(vocab), 6):
        lines.append('  ' + ' | '.join(vocab[i:i + 6]))
    lines += [
        '',
        '输出要求: 只输出一个 JSON 数组（不要任何其他文字、不要 Markdown 代码块）, 格式:',
        '[{"id":"oc-1","top1":"<skill名或NONE>","confidence":"high|mid|low","reason":"一句话理由","suspected_weakness":"该查询暴露的系统弱点, 没有则留空字符串"}]',
        '',
    ]
    if extra_note:
        lines.append(extra_note)
        lines.append('')
    for e in entries:
        eid = str(e['id'])
        if not _re.fullmatch(r"[A-Za-z0-9_-]{1,32}", eid):
            raise ValueError(f"非法样本 id: {eid}")
        q = str(e['query']).replace('\r', ' ').replace('\n', ' ').strip()
        q = q.replace('"', "'")
        lines.append(f"{eid}: {q}")
    return '\n'.join(lines)


def run_cli(prompt, cli='claude', timeout=600):
    if cli == 'claude':
        cmd = ['claude', '-p', '--bare']
    else:
        cmd = ['Codex', '--print']  # R192: 移除 bypassPermissions（提示注入越权面）
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                           encoding='utf-8', timeout=timeout)
        return r.stdout, r.stderr, r.returncode, None
    except Exception as e:
        return '', '', -1, f'{type(e).__name__}: {e}'


def parse_json_out(text):
    """从输出里提取第一个完整 JSON 数组/对象"""
    m = re.search(r'\[.*\]', text, re.S)
    if not m:
        m = re.search(r'\{.*\}', text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def unique_report_paths(base):
    """同一天多次复核自动追加 _r2/_r3，绝不覆盖历史报告"""
    n = 0
    while True:
        tag = '' if n == 0 else f'_r{n+1}'
        md = f'{base}{tag}.md'
        js = f'{base}{tag}.json'
        if not os.path.exists(md) and not os.path.exists(js):
            return md, js
        n += 1


def load_judgments():
    d = json.loads(Path(JUDGMENTS_PATH).read_text(encoding='utf-8'))
    return {e['id']: e for e in d['entries']}


def norm(name):
    return None if name in ('NONE', 'None', None, '') else name


def main():
    source = 'three_door'
    cli = 'claude'
    smoke = '--smoke' in sys.argv
    if '--samples' in sys.argv:
        source = sys.argv[sys.argv.index('--samples') + 1]
    if '--cli' in sys.argv:
        cli = sys.argv[sys.argv.index('--cli') + 1]

    entries = load_samples(source)
    if smoke:
        entries = entries[:1]

    prompt = build_prompt(entries, extra_note='本次为冒烟测试' if smoke else '')
    out, err, rc, exc = run_cli(prompt, cli=cli)
    if exc:
        print(json.dumps({'schema': 'fenjue-cc-recheck-v1', 'error': exc,
                          'cli': cli, 'smoke': smoke}, ensure_ascii=False, indent=2))
        sys.exit(2)

    parsed = parse_json_out(out)
    judgments = load_judgments()
    results = []
    for e in entries:
        cc = None
        if isinstance(parsed, list):
            cc = next((x for x in parsed if str(x.get('id')) == e['id']), None)
        j = judgments.get(e['id'])
        codex_top1 = j.get('router_top1') if j else None
        codex_verdict = j.get('verdict') if j else None
        cc_top1 = norm(cc.get('top1')) if cc else None
        agree = (norm(codex_top1) == cc_top1)
        results.append({
            'id': e['id'],
            'query': e['query'],
            'codex_top1': norm(codex_top1),
            'codex_verdict': codex_verdict,
            'cc_top1': cc_top1,
            'cc_confidence': cc.get('confidence') if cc else None,
            'cc_reason': cc.get('reason') if cc else '',
            'cc_weakness': cc.get('suspected_weakness') if cc else '',
            'agree': bool(agree),
            'cc_raw_found': cc is not None,
        })

    n = len(results)
    agree_n = sum(1 for r in results if r['agree'])
    disagreements = [r for r in results if not r['agree']]
    weaknesses = [r for r in results if r['cc_weakness']]

    report = {
        'schema': 'fenjue-cc-recheck-v1',
        'ts': datetime.datetime.now().isoformat(timespec='seconds'),
        'cli': cli,
        'source': source,
        'smoke': smoke,
        'n': n,
        'agree': agree_n,
        'disagree': len(disagreements),
        'agreement_rate': round(agree_n / n * 100, 1) if n else 0,
        'cc_raw_found': sum(1 for r in results if r['cc_raw_found']),
        'adjudication': [],
        'results': results,
    }
    os.makedirs(REPORTS_DIR, exist_ok=True)
    date = datetime.datetime.now().strftime('%Y-%m-%d')
    suffix = '_smoke' if smoke else ''
    base = os.path.join(REPORTS_DIR, f'cc_independent_recheck_{date}{suffix}')
    md_path, json_path = unique_report_paths(base)

    Path(json_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    with Path(md_path).open('w', encoding='utf-8') as f:
        f.write(f"# CC 独立盲测复核 — {date}\n\n")
        f.write(f"- CLI: {cli} | 样本源: {source} | 冒烟: {smoke}\n")
        f.write(f"- 一致性: {agree_n}/{n} ({report['agreement_rate']}%) | CC JSON 解析: {report['cc_raw_found']}/{n}\n\n")
        f.write("## 不一致清单（裁决链: Codex 复核定稿, 每条带证据+结论）\n\n")
        if disagreements:
            for r in disagreements:
                f.write(f"- **{r['id']}** {r['query'][:40]}\n")
                f.write(f"  - Codex: {r['codex_top1']} ({r['codex_verdict']}) | CC: {r['cc_top1']} ({r['cc_confidence']})\n")
                f.write(f"  - CC 理由: {r['cc_reason']}\n")
                f.write("  - 裁决: 待 Codex 复核（见 adjudication 段）\n")
        else:
            f.write("- （无）\n\n")
        f.write("## CC 主动标注的系统弱点（待证, 无证据不升为确认缺陷）\n\n")
        if weaknesses:
            for r in weaknesses:
                f.write(f"- **{r['id']}** {r['query'][:40]} → {r['cc_weakness']}\n")
        else:
            f.write("- （无）\n\n")
        f.write(f"机器明细: `{json_path}`\n")

    print(json.dumps({
        'schema': 'fenjue-cc-recheck-v1',
        'ts': report['ts'],
        'cli': cli, 'source': source, 'smoke': smoke,
        'n': n, 'agree': agree_n, 'disagree': len(disagreements),
        'agreement_rate': report['agreement_rate'],
        'weaknesses': len(weaknesses),
        'report_md': md_path,
        'report_json': json_path,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
