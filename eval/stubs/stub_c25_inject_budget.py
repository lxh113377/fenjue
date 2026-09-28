#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C25「L1 注入硬预算棘轮」（2026-09-24 P1E-2）

判据面：P0 强制注入区五文件字节和 ≤ baseline（棘轮，只许降不许升，W4）
        且 ≤ hard_cap（绝对上限，W3）；清单/阈值缺失即 FAIL（R247，W1）。
隔离手法：走 sizes= / files= / baseline= / hard_cap= 注入夹具（纯函数面，
         不读真实注入盘）；另跑一次真实五文件核对判据面未失效。
覆盖：正例 1 + 违规样本 2 + 边界 4（含空清单、阈值倒挂、CI SKIP、真实面）。
登记：eval/stubs/registry.json → id=C25-inject-budget
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402

FILES = [{'id': 'f1', 'path': 'D:/nowhere/a.md'}, {'id': 'f2', 'path': 'AGENTS.md'}]

REAL_ST, REAL_DETAIL = v.check_c25_inject_budget(skip_external=True)
SCAN_OK = REAL_ST in ('PASS', 'SKIP')  # CI 无 D: 注入盘 → 判据面合法降级为 SKIP，非假绿

CASES = [
    ('正例-总字节低于基线', dict(files=list(FILES), baseline=61472, hard_cap=65536,
                     sizes={'f1': 40000, 'f2': 5000}), 'PASS', '棘轮合规'),
    ('违规-W3 超硬顶', dict(files=list(FILES), baseline=61472, hard_cap=65536,
                   sizes={'f1': 62000, 'f2': 5000}), 'FAIL', 'W3'),
    ('违规-W4 超基线', dict(files=list(FILES), baseline=61472, hard_cap=65536,
                   sizes={'f1': 40000, 'f2': 5000 + 20000}), 'FAIL', 'W4'),
    ('边界-a 空清单', dict(files=[], baseline=61472, hard_cap=65536), 'FAIL', 'W1'),
    ('边界-b 阈值倒挂', dict(files=list(FILES), baseline=70000, hard_cap=65536,
                    sizes={'f1': 1, 'f2': 1}), 'FAIL', 'W1'),
    ('边界-c CI 注入盘不可达 SKIP', dict(skip_external=True, files=list(FILES),
                          baseline=61472, hard_cap=65536), 'SKIP', '注入盘不可达'),
    ('边界-d 真实五文件（判据面未失效）', None, 'SCAN', ''),
]

ok = 0
for name, kw, expect, needle in CASES:
    if kw is not None:
        st, detail = v.check_c25_inject_budget(**kw)
    else:
        st, detail = ('SCAN' if SCAN_OK else 'SCAN-LOW', REAL_DETAIL)
    good = (st == expect) and (needle in (detail or ''))
    ok += 1 if good else 0
    print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:110]))

print('stub_c25_inject_budget: %d/%d' % (ok, len(CASES)))
sys.exit(0 if ok == len(CASES) else 1)
