#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C21「提交授权纪律防回滚」（2026-09-23 用户立规：自动提交无需确认）

判据面：活文档（workspace 根级壳 + AGENTS 分卷 + 项目绑定表）不得重现
       「提交需授权/确认」类纪律；含历史标记词的行豁免（历史留痕）。
隔离手法：走 `watched=` 注入夹具文件（%TEMP%），不扫真实活文档；跑后清理。
覆盖：四种违规句式 + 历史行豁免 + 空扫描面 fail-closed（R247）。
登记：eval/stubs/registry.json → id=C21-commit-auth
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402

TMP = tempfile.mkdtemp(prefix='fenjue_stub_c21_')


def mk(name, lines):
    p = os.path.join(TMP, name)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    return p


OK = mk('ok.md', ['# 规范', '- 收尾：commit + push（无需确认）', '- 每关一存'])
BAD_AUTH = mk('bad_auth.md', ['- 提交需显式授权后才能 push'])
BAD_AUTO = mk('bad_auto.md', ['- 禁止自动提交，须人工确认'])
BAD_BEFORE = mk('bad_before.md', ['- 提交前请确认变更范围'])
BAD_WAIT = mk('bad_wait.md', ['- 完成后等待用户确认再提交'])
HIST = mk('hist.md', ['- 原为「提交需授权」，现已废除（历史记录行）'])
EMPTY = mk('empty.md', [])
MISSING = os.path.join(TMP, 'not_there.md')

CASES = [
    ('正例 无授权纪律表述', [OK], 'PASS', ''),
    ('违规样本-a 「提交需授权」', [BAD_AUTH], 'FAIL', '命中提交授权表述'),
    ('违规样本-b 「禁止自动提交」', [BAD_AUTO], 'FAIL', '命中提交授权表述'),
    ('违规样本-c 「提交前请确认」', [BAD_BEFORE], 'FAIL', '命中提交授权表述'),
    ('违规样本-d 「等待确认再提交」', [BAD_WAIT], 'FAIL', '命中提交授权表述'),
    ('边界-a 历史记录行（含「已废除」标记）→ 必须豁免', [OK, HIST], 'PASS', ''),
    ('边界-b 空文件（有受检面但无内容）→ PASS', [EMPTY], 'PASS', ''),
    ('边界-c 扫描面为空（0 文件存在）→ 不得静默 PASS（R247）', [MISSING], 'FAIL', '扫描面为空'),
]

ok = 0
try:
    for name, files, expect, needle in CASES:
        st, detail = v.check_c21_no_commit_authorization_rule(watched=files)
        good = (st == expect) and (needle in (detail or ''))
        ok += 1 if good else 0
        print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:120]))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print('stub_c21_commit_auth: %d/%d' % (ok, len(CASES)))
sys.exit(0 if ok == len(CASES) else 1)
