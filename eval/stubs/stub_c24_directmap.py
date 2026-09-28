#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C24「direct 双写一致」（2026-09-23 P2-8/6）

判据面：direct_layer 内置 fallback 与 direct_map.json 必须条数一致（W1）
        + pattern 集合一致（W2）；任一面为空即 FAIL（R247）。
隔离手法：走 `fallback=` / `json_entries=` 注入夹具（纯函数面，不读真实双面）；
         另跑一次真实双面核对判据面未失效。
覆盖：正例 1 + 违规样本 2 + 边界 3（含空面、真实双面）。
登记：eval/stubs/registry.json → id=C24-directmap
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402

FB = [('a.*b', 'S-a'), ('c.*d', 'S-b')]
JS = [['a.*b', 'S-a'], ['c.*d', 'S-b']]
JS_SHORT = [['a.*b', 'S-a']]
JS_DIFF = [['a.*b', 'S-a'], ['e.*f', 'S-b']]

REAL_ST, REAL_DETAIL = v.check_c24_direct_map_consistency()
SCAN_OK = REAL_ST == 'PASS'

CASES = [
    ('正例-a 双面一致', dict(fallback=list(FB), json_entries=[list(e) for e in JS]), 'PASS', '双写一致'),
    ('违规-a W1 条数不一致', dict(fallback=list(FB), json_entries=[list(e) for e in JS_SHORT]), 'FAIL', 'W1'),
    ('违规-b W2 内容不一致', dict(fallback=list(FB), json_entries=[list(e) for e in JS_DIFF]), 'FAIL', 'W2'),
    ('边界-a fallback 空面', dict(fallback=[], json_entries=[list(e) for e in JS]), 'FAIL', 'W1'),
    ('边界-b json 空面', dict(fallback=list(FB), json_entries=[]), 'FAIL', 'W2'),
    ('边界-c 真实双面一致（判据面未失效）', None, 'SCAN', ''),
]

ok = 0
for name, kw, expect, needle in CASES:
    if kw is not None:
        st, detail = v.check_c24_direct_map_consistency(**kw)
    else:
        st, detail = ('SCAN' if SCAN_OK else 'SCAN-LOW', REAL_DETAIL)
    good = (st == expect) and (needle in (detail or ''))
    ok += 1 if good else 0
    print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:110]))

print('stub_c24_directmap: %d/%d' % (ok, len(CASES)))
sys.exit(0 if ok == len(CASES) else 1)
