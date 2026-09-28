#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：gate_stub_runner「覆盖检查」判据本身（`compute_uncovered`，2026-09-23 补全）

为什么需要它：这条判据**是门禁的门禁**。原实现只比 `base_checks` 豁免表、完全不看桩，
导致「新增判据永远无法通过（只能塞进明令禁止的豁免表）」——判据与 registry `_note`
声明的语义不同构（R263 同族）。修好后必须自带三要素桩，否则等于用"更宽松的判据"换绿灯。
桩为纯函数注入（不跑子进程、不读写 registry 真文件），毫秒级。
登记：eval/stubs/registry.json → id=STUB-RUNNER-coverage
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import gate_stub_runner as gsr  # noqa: E402

BASE = dict(live_checks={'C1', 'C17', 'C18', 'C19'}, live_types={'contains_any'},
            base_checks={'C1'}, base_types={'contains_any'})


def run(stubs, **over):
    kw = dict(BASE)
    kw.update(over)
    return gsr.compute_uncovered(kw['live_checks'], kw['live_types'],
                                 kw['base_checks'], kw['base_types'], stubs)


CASES = [
    ('正例 新判据均有 covers 声明 → 无未登记、无幽灵',
     [{'covers': ['C17', 'C18', 'C19']}], ([], ['C17', 'C18', 'C19'], []), {}),
    ('正例-b 全为豁免表内判据 + 无桩 → 仍不报未登记（豁免无需 covers）',
     [], ([], [], []), {'live_checks': {'C1'}, 'live_types': {'contains_any'}}),
    ('违规样本-a 只覆盖一部分 → 未覆盖者必须报出（不得因"有桩"就整体放行）',
     [{'covers': ['C17']}], (['C18', 'C19'], ['C17'], []), {}),
    ('违规样本-b 幽灵覆盖：桩声明了不存在的判据 → 必须报出（防假覆盖骗绿灯）',
     [{'covers': ['C17', 'C18', 'C19', 'C99']}], ([], ['C17', 'C18', 'C19', 'C99'], ['C99']), {}),
    ('边界-a 无任何桩 → 全部新判据报未登记',
     [], (['C17', 'C18', 'C19'], [], []), {}),
    ('边界-b covers 缺失/空/None/非字符串 → 不覆盖任何判据（不得静默全通过）',
     [{'id': 'x'}, {'covers': []}, {'covers': None}, {'covers': ['', '  ', 42]}],
     (['C17', 'C18', 'C19'], [], []), {}),
]

ok = 0
for name, stubs, expect, over in CASES:
    got = run(stubs, **over)
    good = (tuple(got) == expect)
    ok += 1 if good else 0
    print('[%s] %s -> %s' % ('PASS' if good else 'FAIL', name, got if not good else 'as expected'))

print('stub_runner_coverage: %d/%d' % (ok, len(CASES)))
sys.exit(0 if ok == len(CASES) else 1)
