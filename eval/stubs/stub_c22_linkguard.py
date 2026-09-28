#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C22「junction / 符号链接排除守护」（2026-09-23 P2-3 worktree 试点产出）

判据面：仓库内 junction / symlink 必须被 git 显式排除 —— 否则其指向的外部内容
       会被 git 当作普通目录纳入版本控制（实测：git status 出现 A jdir/secret.txt，
       git ls-files 含 jdir/secret.txt）。
隔离手法：links= / ignore_text= / ignored= 三路注入（纯函数面，不碰真实仓库）；
         另在 %TEMP% 建真实 junction 验证扫描器本身。清理时**先 os.rmdir 删链接**
         再 rmtree（防 rmtree 跟随 junction 递归删外部内容）。
覆盖：正例 2 + 违规样本 5 + 边界 3（含「无法验证不得当通过」「无链接 SKIP」「解析器不串段」）。
登记：eval/stubs/registry.json → id=C22-linkguard
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402

SEC_OK = ('# === 符号链接（指向 <MEMORY_ROOT>，不重复跟踪）===\n'
          '/memory\n/memory_content\n/prompts\n')
SEC_WITH_EXTRA = SEC_OK + '/extra_link\n'
SEC_NO_ANCHOR = '# === 其他段 ===\n*.pyc\n__pycache__/\n'
SEC_EMPTY_BODY = '# === 符号链接（指向 <MEMORY_ROOT>）===\n# === 下一段 ===\n*.pyc\n'
SEC_PARTIAL = '# === 符号链接（指向 <MEMORY_ROOT>）===\n/memory\n/memory_content\n'

LINKS3 = [('memory', 'junction'), ('memory_content', 'junction'), ('prompts', 'junction')]
ALL_TRUE = {n: True for n, _k in LINKS3}
ALL_NONE = {n: None for n, _k in LINKS3}

# ---- 边界-c：真实 junction 扫描（%TEMP%）----
REAL = tempfile.mkdtemp(prefix='fenjue_stub_c22_real_')
TARGET = tempfile.mkdtemp(prefix='fenjue_stub_c22_tgt_')
JLINK = os.path.join(REAL, 'jdir')
with open(os.path.join(TARGET, 'secret.txt'), 'w', encoding='utf-8') as f:
    f.write('external\n')
try:
    subprocess.run(['cmd', '/c', 'mklink', '/J', JLINK, TARGET], shell=False,
                   capture_output=True, text=True, encoding='utf-8', errors='replace',
                   timeout=30)  # P1-6: 关 shell 解释面（mklink 是 cmd 内建，走 cmd /c）+ 兜底 timeout
except Exception:
    pass
REAL_FOUND = v._c22_scan_links(REAL) if os.path.isdir(JLINK) else []
SCANNER_OK = ('jdir', 'junction') in REAL_FOUND

# 解析器边界：只取锚点段，后续段规则不得混入
PARSED = v._c22_parse_section(SEC_OK + '\n# === 其他段 ===\n*.pyc\n')

CASES = [
    ('正例-a 3 链接全声明且全被忽略', dict(links=LINKS3, ignore_text=SEC_OK, ignored=ALL_TRUE),
     'PASS', ''),
    ('正例-b 声明段含多余规则（规则多于链接）', dict(links=LINKS3, ignore_text=SEC_WITH_EXTRA, ignored=ALL_TRUE),
     'PASS', ''),
    ('违规-a W1 无「符号链接」声明段', dict(links=LINKS3, ignore_text=SEC_NO_ANCHOR, ignored=ALL_TRUE),
     'FAIL', 'W1'),
    ('违规-b W1 锚点在但段内无规则', dict(links=LINKS3, ignore_text=SEC_EMPTY_BODY, ignored=ALL_TRUE),
     'FAIL', 'W1'),
    ('违规-c W2 某链接未被 git 忽略', dict(links=LINKS3, ignore_text=SEC_OK,
                                      ignored={'memory': True, 'memory_content': False, 'prompts': True}),
     'FAIL', 'W2'),
    ('违规-d W2 无法验证（git 不可用）不得当通过', dict(links=LINKS3, ignore_text=SEC_OK, ignored=ALL_NONE),
     'FAIL', '无法验证'),
    ('违规-e W3 链接无显式声明（靠别处规则）', dict(links=LINKS3, ignore_text=SEC_PARTIAL, ignored=ALL_TRUE),
     'FAIL', 'W3'),
    ('边界-a 无链接 -> SKIP（该环境无风险面）', dict(links=[], ignore_text=SEC_OK, ignored={}),
     'SKIP', '无风险面'),
    ('边界-b 解析器只取锚点段（不串段）', None, 'PARSED', '/prompts'),
    ('边界-c 真实 junction 可被扫描到', None, 'SCANNER', ''),
]

ok = 0
try:
    for name, kw, expect, needle in CASES:
        if kw is not None:
            st, detail = v.check_c22_junction_exclude(**kw)
        elif expect == 'PARSED':
            st, detail = ('PARSED', ','.join(PARSED))
        else:
            st, detail = ('SCANNER' if SCANNER_OK else 'NO-SCAN', ','.join('%s:%s' % t for t in REAL_FOUND))
        good = (st == expect) and (needle in (detail or ''))
        ok += 1 if good else 0
        print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:110]))
finally:
    if os.path.isdir(JLINK):
        try:
            os.rmdir(JLINK)   # 只删链接本身；rmtree 会跟随 junction 删到外部目标
        except OSError:
            pass
    shutil.rmtree(REAL, ignore_errors=True)
    shutil.rmtree(TARGET, ignore_errors=True)

print('stub_c22_linkguard: %d/%d' % (ok, len(CASES)))
sys.exit(0 if ok == len(CASES) else 1)
