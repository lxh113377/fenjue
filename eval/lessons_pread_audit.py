#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lessons_pread_audit.py — 开场 lessons 预读门禁统计（主线4 开-收闭环，P1-2 落地）
==============================================================================
扫描各端记忆日志中的开场声明行（execution_guide.txt 约定格式），统计复杂任务
预读覆盖率与 skill 加载数，与收尾 lessons_hitrate.py 形成「开场预读 ↔ 收尾用上」闭环。

声明行格式（写入当日日志）：
  lessons预读: 命中N条 (领域: xxx)
  skill加载: N个 (清单: a, b, c)

用法:
  python eval/lessons_pread_audit.py            # 近 7 天统计
  python eval/lessons_pread_audit.py --days 1   # 仅今日
  python eval/lessons_pread_audit.py --json     # JSON 输出

退出码: 0 = 正常（含无数据）；1 = 声明格式解析异常
"""
import datetime
import glob
import json
import os
import re
import sys

from config import GLOBAL_MEMORY, PROJECT_DIR

LOGDIRS = [
    os.path.join(GLOBAL_MEMORY, 'memory'),
    r'<USER_HOME>\.Codex\memory',  # P1-6 基线放行：外部平台(Codex)遗留路径，非焚诀布局
    os.path.join(PROJECT_DIR, '.workbuddy', 'memory'),
]

RE_PREAD = re.compile(r'lessons预读:\s*命中(\d+)条\s*\(领域:\s*([^)]+)\)')
RE_SKILL = re.compile(r'skill加载:\s*(\d+)个\s*\(清单:\s*([^)]+)\)')
RE_MEM = re.compile(r'记忆加载:\s*命中(\d+)个\s*\(文件:\s*([^)]+)\)')

USAGE_JSONL = os.path.join(GLOBAL_MEMORY, 'meta', 'lessons_usage.jsonl')


def scan_usage(path=None, cutoff=None):
    """R216-03: 机器落账数据源（record_lessons_usage.py 追加的 lessons_usage.jsonl）。

    断链实证（2026-09-06）：声明行 08-03 后未再落日志（行为断链），但 jsonl
    机器落账一直在积累——审计不读它，「0 轮」就是管道假阴性而非真实行为。
    容错：跳过 '#' 注释头；坏行计数不中断；date 缺失/过期行跳过。
    返回 (rows, bad_lines, source_ok)。
    """
    path = path or USAGE_JSONL
    rows, bad_lines = [], 0
    if not os.path.exists(path):
        return rows, bad_lines, False
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            try:
                rec = json.loads(ln)
            except Exception:
                bad_lines += 1
                continue
            if not isinstance(rec, dict) or not rec.get('date'):
                continue
            if cutoff and rec['date'] < cutoff:
                continue
            rows.append(rec)
    return rows, bad_lines, True


def scan(days):
    cutoff = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    rows = []
    for d in LOGDIRS:
        for f in glob.glob(os.path.join(d, '*.md')):
            base = os.path.basename(f)
            m = re.match(r'(\d{4}-\d{2}-\d{2})', base)
            if not m or m.group(1) < cutoff:
                continue
            with open(f, encoding='utf-8', errors='replace') as _f:
                txt = _f.read()
            for pm in RE_PREAD.finditer(txt):
                rows.append({'date': m.group(1), 'file': os.path.basename(f),
                             'kind': 'pread', 'n': int(pm.group(1)),
                             'domain': pm.group(2).strip()})
            for sm in RE_SKILL.finditer(txt):
                rows.append({'date': m.group(1), 'file': os.path.basename(f),
                             'kind': 'skill', 'n': int(sm.group(1)),
                             'list': sm.group(2).strip()})
            for mm in RE_MEM.finditer(txt):
                rows.append({'date': m.group(1), 'file': os.path.basename(f),
                             'kind': 'memory', 'n': int(mm.group(1)),
                             'list': mm.group(2).strip()})
    return rows


def main():
    days = 7
    if '--days' in sys.argv:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    rows = scan(days)
    # 三端日志是同一会话镜像 → 按 (日期, 类型, 条数, 内容) 去重，口径为「轮次」
    seen = set()
    dedup = []
    for r in rows:
        key = (r['date'], r['kind'], r['n'], r.get('domain') or r.get('list'))
        if key not in seen:
            seen.add(key)
            dedup.append(r)
    rows = dedup
    pread = [r for r in rows if r['kind'] == 'pread']
    skills = [r for r in rows if r['kind'] == 'skill']
    mems = [r for r in rows if r['kind'] == 'memory']
    n_pread = sum(r['n'] for r in pread)
    n_skill = sum(r['n'] for r in skills)
    # R216-03: 机器落账数据源（jsonl）——声明行断链时的真实行为兜底
    cutoff = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    usage_rows, usage_bad, usage_ok = scan_usage(cutoff=cutoff)
    usage_sessions = {r.get('session', '') for r in usage_rows if r.get('session')}
    declared_missing = (len(pread) == 0 and len(usage_rows) > 0)
    out = {
        'schema': 'fenjue-lessons-pread-audit-v2',
        'days': days,
        'pread_declared': len(pread),
        'pread_hits_total': n_pread,
        'pread_avg_hits': round(n_pread / len(pread), 1) if pread else 0,
        'skill_declared': len(skills),
        'skill_loaded_total': n_skill,
        'skill_avg': round(n_skill / len(skills), 1) if skills else 0,
        'memory_declared': len(mems),
        'memory_hits_total': sum(r['n'] for r in mems),
        'memory_avg': round(sum(r['n'] for r in mems) / len(mems), 1) if mems else 0,
        'usage_events': len(usage_rows),
        'usage_sessions': len(usage_sessions),
        'usage_loaded_events': len([r for r in usage_rows if r.get('loaded')]),
        'usage_used_events': len([r for r in usage_rows if r.get('used')]),
        'usage_bad_lines': usage_bad,
        'usage_source_ok': usage_ok,
        'declared_missing': declared_missing,
        'rows': rows,
    }
    if '--json' in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f'开场预读门禁统计（近 {days} 天，三端日志 + 机器落账双源）')
        print(f'  lessons预读声明: {len(pread)} 轮 | 命中总条数: {n_pread} | 平均: {out["pread_avg_hits"]} 条/轮')
        print(f'  skill加载声明: {len(skills)} 轮 | 加载总数: {n_skill} | 平均: {out["skill_avg"]} 个/轮')
        print(f'  记忆加载声明: {len(mems)} 轮 | 命中总数: {out["memory_hits_total"]} | 平均: {out["memory_avg"]} 个/轮')
        print(f'  机器落账 jsonl: {len(usage_rows)} 事件 / {len(usage_sessions)} 会话 | 坏行: {usage_bad} | 源存在: {usage_ok}')
        if declared_missing:
            print('  ⚠️ 断链告警: 声明行 0 轮但 jsonl 有落账 —— G5 声明行未落日志（行为断链），机器数据源已兜底')
        print('  与收尾 lessons_hitrate 构成开-收闭环（收尾用上率见 lessons_hitrate.py）')
        for r in rows[-10:]:
            print(f'    {r["date"]} [{r["kind"]}] n={r["n"]} {r.get("domain", r.get("list", ""))}')
    sys.exit(0)


if __name__ == '__main__':
    main()
