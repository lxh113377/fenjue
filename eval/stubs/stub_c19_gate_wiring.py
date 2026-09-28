#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C19「门禁接入点真实落地」（R278 静态层）

被包装对象：`check_gate_wiring` 的检查主体（经 verify wrapper `check_c19_gate_wiring` → `_cgw_run`）
隔离手法：在 %TEMP% 造一整套**假世界**（两仓 hook + 版本化副本 + CI + 周维护 checklist + verify 头部），
        替换 cgw 模块级路径常量；不触真实 hook / 真实仓（也避免 verify→C19→hook→verify 递归）。
覆盖：W1/W2 hook 存在性与调用/拦截语义、W3 副本、W4 CI、W7 周维护、**W6 声明↔自检登记覆盖**。
登记：eval/stubs/registry.json → id=C19-gate-wiring
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v      # noqa: E402
import check_gate_wiring as cgw           # noqa: E402

TMP = tempfile.mkdtemp(prefix='fenjue_stub_c19_')
FJ = os.path.join(TMP, 'fj')
GM = os.path.join(TMP, 'gm')
FJ_HOOK = os.path.join(FJ, '.git', 'hooks', 'pre-commit')
GM_HOOK = os.path.join(GM, '.git', 'hooks', 'pre-commit')
FJ_COPY = os.path.join(FJ, 'eval', 'hooks', 'pre-commit')
GM_COPY = os.path.join(GM, 'scripts', 'hooks', 'pre-commit')
CI_YML = os.path.join(FJ, '.github', 'workflows', 'ci.yml')
WEEKLY = os.path.join(FJ, 'skill', 'checklist', 'weekly_maintenance')
VFILE = os.path.join(TMP, 'verify_head.py')

GOOD_HOOK = '#!/bin/sh\npython eval/verify_truth_consistency.py || exit 1\n'
GOOD_VERIFY = (
    '#!/usr/bin/env python3\n"""verify\n\n接入点:\n'
    '- pre-commit hook（焚诀仓 / GM 仓 .git/hooks）\n'
    '- CI（.github/workflows/ci.yml）\n'
    '- 周维护 Step 0（skill/checklist/weekly_maintenance*.md）\n"""\n'
)


def wr(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def world(fj_hook=GOOD_HOOK, gm_hook=GOOD_HOOK, fj_copy=GOOD_HOOK, gm_copy=GOOD_HOOK,
          ci='run: python eval/verify_truth_consistency.py\n', weekly='Step 0: verify_truth_consistency.py\n',
          verify=GOOD_VERIFY):
    for p, t in ((FJ_HOOK, fj_hook), (GM_HOOK, gm_hook), (FJ_COPY, fj_copy), (GM_COPY, gm_copy),
                 (CI_YML, ci), (WEEKLY + '.part1.md', weekly), (VFILE, verify)):
        if t is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            wr(p, t)


CASES = [
    ('正例 全部接入点落地 + 声明均有对应自检', {}, 'PASS', ''),
    ('违规样本-a hook 存在但未调用 verify',
     {'fj_hook': '#!/bin/sh\necho lint\n'}, 'FAIL', '未调用 verify'),
    ('违规样本-b hook 调用 verify 但无 exit 1 拦截语义',
     {'fj_hook': '#!/bin/sh\npython eval/verify_truth_consistency.py\n'}, 'FAIL', 'exit 1'),
    ('违规样本-c 声明了无对应自检的接入点（W6）',
     {'verify': GOOD_VERIFY.replace('"""\n', '- 每日 03:00 自动同步任务\n"""\n', 1)}, 'FAIL', '无对应自检'),
    ('边界-a hook 缺失', {'fj_hook': None}, 'FAIL', 'hook 不存在'),
    ('边界-b 版本化副本缺失（换机即失守）', {'fj_copy': None}, 'FAIL', '副本'),
    ('边界-c 周维护 checklist 缺失', {'weekly': None}, 'FAIL', '周维护'),
    ('边界-d verify 头部无「接入点:」声明块 → 判据面失效（R247）',
     {'verify': '#!/usr/bin/env python3\n"""verify（无声明块）"""\n'}, 'FAIL', '未解析到'),
]

ok = 0
_sv = (cgw.FJ_HOOK, cgw.GM_HOOK, cgw.FJ_COPY, cgw.GM_COPY, cgw.CI_YML, cgw.WEEKLY_GLOB_PREFIX, cgw.VERIFY)
try:
    cgw.FJ_HOOK, cgw.GM_HOOK = FJ_HOOK, GM_HOOK
    cgw.FJ_COPY, cgw.GM_COPY = FJ_COPY, GM_COPY
    cgw.CI_YML, cgw.WEEKLY_GLOB_PREFIX, cgw.VERIFY = CI_YML, WEEKLY, VFILE
    for name, mutate, expect, needle in CASES:
        world()
        world(**mutate)
        st, detail = v.check_c19_gate_wiring()
        good = (st == expect) and (needle in (detail or ''))
        ok += 1 if good else 0
        print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:140]))
finally:
    (cgw.FJ_HOOK, cgw.GM_HOOK, cgw.FJ_COPY, cgw.GM_COPY,
     cgw.CI_YML, cgw.WEEKLY_GLOB_PREFIX, cgw.VERIFY) = _sv
    shutil.rmtree(TMP, ignore_errors=True)

print('stub_c19_gate_wiring: %d/%d' % (ok, len(CASES)))
sys.exit(0 if ok == len(CASES) else 1)
