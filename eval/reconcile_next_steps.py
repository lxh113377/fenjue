#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reconcile_next_steps.py — 待办池(07-next-steps) 与 git 提交的对账器（R213, M2 反向闭环）

背景
----
M2（R210-03 落地的 workflow_gate.check_git_atomicity）只管**正向**闭环：
    有代码改动 -> 必须 commit + 07 销账
缺**反向**闭环：
    有 commit -> 待办池里对应的推荐项必须销账

缺失反向闭环的实证（2026-09-06）：`[推荐:R210-02]` 在 07-next-steps 里仍是 `[ ]`，
但 `7f01264` 已完整实现（M2 check_git_atomicity + 9 用例 41 全绿）——已做未销账，
且与 R210-03 重复登记，导致待办池噪声与重复劳动。

三类输出
--------
- DONE_UNCHECKED   : git 中已有对应提交，但待办池仍是 [ ]（已做未销账）
- OPEN_NO_COMMIT   : 待办池 [ ] 且 git 无对应提交（真待办）
- CHECKED_NO_TRACE : 待办池 [x] 但 git 查无对应提交（已销账但无 git 可追溯证据）

用法
----
  python eval/reconcile_next_steps.py                  # 人类可读报告
  python eval/reconcile_next_steps.py --json           # JSON 输出
  python eval/reconcile_next_steps.py --gate           # 门禁模式：存在假销账 -> exit 1
  python eval/reconcile_next_steps.py --commits 500    # 扩大 git 回溯范围
"""
import argparse
import json
import os
import re
import subprocess
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
sys.path.insert(0, EVAL_DIR)

from config import GLOBAL_MEMORY  # noqa: E402

NEXT_STEPS_DIR = os.path.join(GLOBAL_MEMORY, 'memory')
NEXT_STEPS_GLOB = '07-next-steps*.md'

# [推荐:R210-02] / [推荐:R209-2①②] —— 允许 ID 内含中文序号后缀
RECO_RE = re.compile(r'\[推荐:([^\]\[]+)\]')
# 复选框状态：'- [x] ' 已销账 / '- [ ] ' 未销账
CHECK_RE = re.compile(r'^\s*[-*]\s*\[([ xX])\]\s*(.*)$')
# 基础 ID 归一化：R209-2①② -> R209-2（commit message 常省略中文序号）
BASE_ID_RE = re.compile(r'([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)')
# 条目文案里直接写死的 commit hash（如 "✅ f9cfbe9"）——比推荐 ID 更可靠的落地证据
HASH_RE = re.compile(r'\b[0-9a-f]{7,40}\b')
# 2026-09-25（对标轮六 D-47）：并发会话各自取"下一个号"必然重号——当晚我一条批次里
# 就插出 P0-32/P0-33 两组重复（另一会话顶部同用两号）。重号的害处不是难看，而是
# 提交信息/日志/判据用 ID 引用条目时**指向不唯一**，"已闭环"能各说各话。
P0_HEAD_RE = re.compile(r'^\s*[-*]\s*\[[ xX]\]\s*((?:P\d+|G\d+|Q\d+)-\d+)\b')


def collect_ids(paths=None):
    """扫描 07 全部分卷，按**行首**取条目 ID（正文里引用别人的 P0-NN 不算条目）。"""
    if paths is None:
        import glob as _glob
        paths = sorted(_glob.glob(os.path.join(NEXT_STEPS_DIR, NEXT_STEPS_GLOB)))
    out = []
    for path in paths:
        try:
            with open(path, encoding='utf-8-sig', errors='replace') as f:
                for lineno, line in enumerate(f, 1):
                    m = P0_HEAD_RE.match(line)
                    if m:
                        out.append({'id': m.group(1), 'file': os.path.basename(path),
                                    'line': lineno,
                                    'checked': bool(re.match(r'^\s*[-*]\s*\[[xX]\]', line))})
        except OSError:
            continue
    return out


def duplicate_ids(entries):
    """返回 {id: [(file, line, checked), ...]}，只含出现两次以上的 ID。"""
    groups = {}
    for e in entries:
        groups.setdefault(e['id'], []).append((e['file'], e['line'], e['checked']))
    return {k: v for k, v in groups.items() if len(v) > 1}


def contradictory_dups(dups):
    """同一 ID 既是 `[ ]` 又是 `[x]` ⇒ 状态自相矛盾，读者无法判断这条到底做完没有。

    这是重号里真正有害的一类（另一类同号同状态只是引用歧义，警告即可）：
    实测成因是闭环时**另起一行写 [x]**而没有更新原 [ ] 行，两条并存。
    """
    return {k: v for k, v in dups.items() if len({c for _f, _l, c in v}) > 1}


def collect_items(paths=None):
    """扫描 07-next-steps 全部分卷，返回 [{id, base_id, checked, file, line, text}]。"""
    if paths is None:
        import glob as _glob
        paths = sorted(_glob.glob(os.path.join(NEXT_STEPS_DIR, NEXT_STEPS_GLOB)))
    items = []
    for path in paths:
        try:
            with open(path, encoding='utf-8-sig', errors='replace') as f:
                lines = f.readlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            m = CHECK_RE.match(line)
            if not m:
                continue
            checked = m.group(1).lower() == 'x'
            body = m.group(2)
            rm = RECO_RE.search(body)
            if not rm:
                continue
            raw_id = rm.group(1).strip()
            bm = BASE_ID_RE.match(raw_id)
            items.append({
                'id': raw_id,
                'base_id': bm.group(1) if bm else raw_id,
                'checked': checked,
                'file': os.path.basename(path),
                'line': lineno,
                'text': body.strip()[:120],
            })
    return items


def git_log_text(commits=200, cwd=None):
    """取最近 N 条 commit 的 subject 文本（失败返回 None，由调用方降级）。"""
    cwd = cwd or PROJECT_DIR
    try:
        proc = subprocess.run(
            ['git', 'log', '--oneline', '-%d' % commits],
            cwd=cwd, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=30,
        )
    except Exception as e:
        print('WARN: git log 执行失败: %s' % e, file=sys.stderr)
        return None
    if proc.returncode != 0:
        print('WARN: git log 返回码 %d: %s' % (proc.returncode, (proc.stderr or '').strip()[:200]),
              file=sys.stderr)
        return None
    return proc.stdout


def verify_hashes(cands, cwd=None):
    """批量校验 commit hash 是否真实存在，返回存在的集合。

    待办池与 commit 是两套编号（推荐 ID R210-04 vs 报告编号 R210-G3），
    仅靠 ID 匹配会把「文案里已写明提交号」的条目误判为假销账（实测 10 条假阳性）。
    故以 git cat-file --batch-check 实测 hash 存在性为第二证据通道。
    """
    cands = sorted({c for c in cands if c})
    if not cands:
        return set()
    cwd = cwd or PROJECT_DIR
    try:
        proc = subprocess.run(
            ['git', 'cat-file', '--batch-check'],
            input='\n'.join(cands) + '\n',
            cwd=cwd, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=30,
        )
    except Exception as e:
        print('WARN: git cat-file 执行失败: %s' % e, file=sys.stderr)
        return set()
    if proc.returncode != 0:
        return set()
    # batch-check 逐行按输入顺序输出，且回显的是完整 40 位 sha（不是输入的短 hash）
    # ——按位置 zip 才能把「短 hash 候选」映射回存在性（直接收集输出会 0 命中）
    lines = (proc.stdout or '').splitlines()
    if len(lines) != len(cands):
        print('WARN: git cat-file 输出行数(%d) 与候选数(%d) 不一致，hash 证据降级'
              % (len(lines), len(cands)), file=sys.stderr)
        return set()
    exist = set()
    for cand, line in zip(cands, lines):
        parts = line.split()
        if len(parts) >= 2 and parts[1] == 'commit':
            exist.add(cand)
    return exist


def reconcile(items, log_text, exist_hashes=None):
    """按 ID / commit hash 双通道匹配，输出三类清单。

    log_text 为 None（git 不可用）时全部降级为 UNKNOWN_NO_GIT。
    证据优先级：推荐 ID 命中 > 条目内 hash 实测存在 > 无证据。
    """
    exist_hashes = exist_hashes or set()
    out = {'DONE_UNCHECKED': [], 'OPEN_NO_COMMIT': [], 'CHECKED_NO_TRACE': [], 'DONE_CHECKED': []}
    if log_text is None:
        out['UNKNOWN_NO_GIT'] = [i['id'] for i in items]
        return out
    for it in items:
        hash_hits = sorted(set(HASH_RE.findall(it.get('text', ''))) & exist_hashes)
        hit = it['base_id'] in log_text or bool(hash_hits)
        if hit:
            it = dict(it, evidence=('id' if it['base_id'] in log_text else 'hash'),
                      commits=hash_hits)
        if it['checked'] and hit:
            out['DONE_CHECKED'].append(it)
        elif it['checked'] and not hit:
            out['CHECKED_NO_TRACE'].append(it)
        elif not it['checked'] and hit:
            out['DONE_UNCHECKED'].append(it)
        else:
            out['OPEN_NO_COMMIT'].append(it)
    return out


def main():
    ap = argparse.ArgumentParser(description='待办池与 git 对账器（M2 反向闭环）')
    ap.add_argument('--json', action='store_true', help='JSON 输出')
    ap.add_argument('--gate', action='store_true',
                    help='门禁模式：存在 DONE_UNCHECKED(已做未销账) -> exit 1')
    ap.add_argument('--strict', action='store_true',
                    help='门禁增强：CHECKED_NO_TRACE(销账无 git 证据) 亦 -> exit 1')
    ap.add_argument('--commits', type=int, default=200, help='git 回溯条数（默认 200）')
    ap.add_argument('--dir', default=None, help='07-next-steps 所在目录（默认 GLOBAL_MEMORY/memory）')
    args = ap.parse_args()

    paths = None
    if args.dir:
        import glob as _glob
        paths = sorted(_glob.glob(os.path.join(args.dir, NEXT_STEPS_GLOB)))
    items = collect_items(paths)
    id_entries = collect_ids(paths)
    dup_ids = duplicate_ids(id_entries)
    dup_bad = contradictory_dups(dup_ids)
    log_text = git_log_text(args.commits)
    hash_cands = [h for it in items for h in HASH_RE.findall(it.get('text', ''))]
    exist_hashes = verify_hashes(hash_cands) if log_text is not None else set()
    res = reconcile(items, log_text, exist_hashes)

    payload = {
        'schema': 'fenjue-next-steps-reconcile-v1',
        'scanned_files': len(set(i['file'] for i in items)),
        'items': len(items),
        'git_available': log_text is not None,
        'commits_scanned': args.commits,
        'counts': {k: len(v) for k, v in res.items()},
        'ids_scanned': len(id_entries),
        'DUP_IDS': [{'id': k,
                     'at': ['%s:%d[%s]' % (f, ln, 'x' if c else ' ')
                            for f, ln, c in v]}
                    for k, v in sorted(dup_ids.items())],
        'DUP_CONTRADICTORY': sorted(dup_bad),
        'DONE_UNCHECKED': res['DONE_UNCHECKED'],
        'OPEN_NO_COMMIT': res['OPEN_NO_COMMIT'],
        'CHECKED_NO_TRACE': res['CHECKED_NO_TRACE'],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print('=' * 66)
        print('待办池 <-> git 对账 (M2 反向闭环)  扫描 %d 卷 / %d 条推荐项 / git %s'
              % (payload['scanned_files'], payload['items'],
                 '可用' if payload['git_available'] else '不可用(降级)'))
        print('=' * 66)
        for key, title in (('DONE_UNCHECKED', '已做未销账（有 commit，仍是 [ ]）'),
                           ('CHECKED_NO_TRACE', '已销账但无 git 证据（[x] 查无 commit）'),
                           ('OPEN_NO_COMMIT', '真待办（[ ] 且无 commit）')):
            lst = res[key]
            print('\n%s: %d 条' % (title, len(lst)))
            for it in lst[:20]:
                print('  [%s] %s (%s:%d) %s' % (
                    'x' if it['checked'] else ' ', it['id'], it['file'], it['line'], it['text'][:70]))
            if len(lst) > 20:
                print('  ... 另 %d 条（--json 查看全量）' % (len(lst) - 20))
        print('\n正常已销账(DONE_CHECKED): %d 条' % len(res['DONE_CHECKED']))
        print('\n行首 ID 共 %d 个；重复 %d 组（其中**状态自相矛盾** %d 组）'
              % (len(id_entries), len(dup_ids), len(dup_bad)))
        for k, v in sorted(dup_ids.items()):
            flag = '矛盾' if k in dup_bad else '同号'
            print('  [%s] %s 出现在 %s' % (flag, k,
                  ' , '.join('%s:%d[%s]' % (f, ln, 'x' if c else ' ') for f, ln, c in v)))

    if args.gate:
        # 同号同状态只是引用歧义（历史遗留，警告）；同 ID 一条 [ ] 一条 [x] 是账面失真，
        # 读者无法判断做完没有 —— 这一类必须拦（实测成因：闭环时另起一行写 [x] 而没改原行）。
        if dup_bad:
            return 1
        # 能修的必须修：已做未销账 -> 待办池失真，会导致重复劳动
        if res['DONE_UNCHECKED']:
            return 1
        # 历史条目缺 commit 约定导致的证据缺失属技术债，仅 --strict 阻断
        if args.strict and res['CHECKED_NO_TRACE']:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
