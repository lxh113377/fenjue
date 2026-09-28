# -*- coding: utf-8 -*-
"""verify_checks.workspace_layer — 检查函数族（P1-16 拆包，2026-09-23）。

状态/助手经 `_root.<name>` 晚绑定（ctx 单例 = verify_truth_consistency），
monkeypatch(vtc, <state>/<check>) 契约不变。
"""
import glob
import json
import os
import re
import subprocess
import sys

import verify_truth_consistency as _root  # noqa: E402  # ctx 单例


def check_c8_no_bak_in_workspace():
    """C8(补充): 活 workspace 物理盘零 _bak_* 目录。"""
    issues = []
    for entry in os.listdir(_root.PROJECT_DIR):
        if entry.startswith('_bak_'):
            issues.append(entry)
    if issues:
        return ('FAIL', f'物理盘残留 _bak_*: {issues}')
    return ('PASS', '活 workspace 无 _bak_* 目录')


def check_c9_no_stale_artifacts():
    """C9(补充): 活目录无 Temp/ 与已知重复/备份残留。"""
    issues = []
    temp_dir = os.path.join(_root.PROJECT_DIR, 'Temp')
    if os.path.isdir(temp_dir):
        issues.append('Temp/ 目录仍存在（应迁出或删除）')
    for rel in ('eval/scorecard_v1_backup.py', 'eval/semantic_overlap_audit.py',
                'eval/skill_hitrate_eval.py'):
        if os.path.exists(os.path.join(_root.PROJECT_DIR, rel)):
            issues.append(rel + ' 仍存在（重复/备份残留）')
    if issues:
        return ('FAIL', '; '.join(issues))
    return ('PASS', '无 Temp/ 与重复/备份残留')


def check_c22_junction_exclude(links=None, ignore_text=None, ignored=None):
    """C22: junction / 符号链接必须被 git 显式排除（P2-3 worktree 试点产出）。

    links / ignore_text / ignored 仅供测试注入（同 C16 的 files= 模式），默认真实扫描面。
    """
    repo = _root.PROJECT_DIR
    if links is None:
        links = _root._c22_scan_links(repo)
    if ignore_text is None:
        gi = os.path.join(repo, '.gitignore')
        ignore_text = ''
        if os.path.exists(gi):
            with open(gi, encoding='utf-8', errors='ignore') as f:
                ignore_text = f.read()
    rules = _root._c22_parse_section(ignore_text)
    if not rules:
        return ('FAIL', 'W1 .gitignore 无「%s」声明段（判据面失效：规则被删即静默放行，R247）'
                % _root.C22_SECTION_ANCHOR)
    if not links:
        return ('SKIP', '本环境无 junction/symlink（无风险面）；声明段 %d 条规则在位' % len(rules))
    names = [n for n, _k in links]
    if ignored is None:
        ignored = _root._c22_git_ignored(repo, names)
    declared = set(r.strip().strip('/') for r in rules)
    issues = []
    for name, kind in links:
        if name not in declared:
            issues.append('W3 %s(%s) 无显式声明规则' % (name, kind))
        flag = ignored.get(name)
        if flag is None:
            issues.append('W2 %s(%s) 无法验证（git check-ignore 不可用）→ 不得当通过' % (name, kind))
        elif not flag:
            issues.append('W2 %s(%s) 未被 git 忽略（内容会被纳入版本控制）' % (name, kind))
    if issues:
        return ('FAIL', '; '.join(issues))
    return ('PASS', '%d 个链接全部排除（声明段 %d 条规则）' % (len(links), len(rules)))

