#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C32「空基线已初始化台账」（2026-09-24 对标轮四 7-C / 6-B）

判据面：空面须持登记（scanned_units>0 且 ≤ 实扫面 / surface / at≤90 天 / 计数器型 next_due），
        非空面免登记；基线文件缺失即红；台账文件缺失即红（W0，禁手写空台账求绿）。
隔离手法：`state=` / `entries=` / `today=` 注入夹具（纯函数面，不读真实三面与真实台账）；
         另跑一次真实面核对判据面未失效。
覆盖：正例 2 + 违规 6（未登记/scanned=0/虚报超面/过期/坏日期/缺 next_due/缺 surface/文件缺失）
     + 边界 1（台账缺失 W0）+ 差分对照组 1（只翻一个字段必须翻转判定）。
登记：eval/stubs/registry.json → id=C32-empty-baseline
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402

TODAY = '2026-09-24'
STATE = [{'id': 't1', 'path': 'a.json', 'kind': 'dict', 'present': True, 'empty': True, 'units': 200}]
STATE_NONEMPTY = [{'id': 't1', 'path': 'a.json', 'kind': 'dict', 'present': True,
                   'empty': False, 'units': 200}]
ENTRY = {'t1': {'id': 't1', 'scanned_units': 200, 'surface': 'scan_dirs_py_files',
                'at': TODAY, 'note': '四面 ruff 实扫'}}

REAL_ST, REAL_DETAIL = v.check_c32_empty_baseline_ledger()
SCAN_OK = REAL_ST == 'PASS'

CASES = [
    ('正例-空面已登记', STATE, ENTRY, 'PASS', '全部登记在册'),
    ('正例-非空免登记', STATE_NONEMPTY, {}, 'PASS', '非空=1'),
    ('违规-空面未登记', STATE, {}, 'FAIL', '未登记'),
    ('违规-scanned 为 0', STATE, dict(ENTRY, t1=dict(ENTRY['t1'], scanned_units=0)), 'FAIL', '非正数'),
    ('违规-虚报超实扫面', STATE, dict(ENTRY, t1=dict(ENTRY['t1'], scanned_units=9999)),
     'FAIL', '超当前实扫面'),
    ('违规-登记过期', STATE, dict(ENTRY, t1=dict(ENTRY['t1'], at='2025-01-01')), 'FAIL', '过期'),
    ('违规-坏日期', STATE, dict(ENTRY, t1=dict(ENTRY['t1'], at='昨天')), 'FAIL', 'ISO'),
    ('违规-缺 next_due', [{'id': 't1', 'path': 'a.json', 'kind': 'counter', 'present': True,
                          'empty': True, 'units': 30}], ENTRY, 'FAIL', 'next_due'),
    ('违规-缺 surface', STATE, dict(ENTRY, t1=dict(ENTRY['t1'], surface='')), 'FAIL', 'surface'),
    ('违规-基线文件缺失', [{'id': 't1', 'path': 'gone.json', 'kind': 'dict', 'present': False,
                          'empty': True, 'units': 5}], ENTRY, 'FAIL', '缺失'),
    ('边界-台账文件不存在 W0', None, None, 'FAIL', 'W0'),
]

ok = 0
for name, state, entries, expect, needle in CASES:
    if name.startswith('边界'):
        st, detail = v.check_c32_empty_baseline_ledger(ledger_path=os.path.join(HERE, '_no_such_ledger.json'))
    else:
        st, detail = v.check_c32_empty_baseline_ledger(state=state, entries=entries, today=TODAY)
    good = (st == expect) and (needle in (detail or ''))
    ok += 1 if good else 0
    print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:100]))

# 差分对照组：同一夹具只把 at 从"今天"改到"未登记"，判定必须翻转（防违规样本其实是干净数据）
st_a, _ = v.check_c32_empty_baseline_ledger(state=STATE, entries=ENTRY, today=TODAY)
st_b, _ = v.check_c32_empty_baseline_ledger(state=STATE, entries={}, today=TODAY)
diff_ok = (st_a == 'PASS' and st_b == 'FAIL')
ok += 1 if diff_ok else 0
print('[%s] 差分-撤登记必须翻转 -> %s/%s' % ('PASS' if diff_ok else 'FAIL', st_a, st_b))

print('[%s] 真实三面（判据面未失效）-> %s | %s'
      % ('PASS' if SCAN_OK else 'FAIL', REAL_ST, (REAL_DETAIL or '')[:90]))
ok += 1 if SCAN_OK else 0

print('stub_c32_empty_baseline: %d/%d' % (ok, len(CASES) + 2))
sys.exit(0 if ok == len(CASES) + 2 else 1)
