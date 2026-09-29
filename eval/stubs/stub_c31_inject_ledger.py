#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C31「L1 注入预算归因台账」（2026-09-24 对标轮四 7-E）

判据面：台账非空（空=未初始化即红）+ truth_constants 基线必须等于台账末条 applied 的
        baseline_after（禁裸改）+ applied 必须署名给因 + 硬顶不得超立规天花板 65536 +
        pending/低余量必须在明细可见。
隔离手法：走 `ledger_path=` / `baseline=` / `hard_cap=` / `measured_total=` 注入夹具
        （纯函数面，不读真实注入盘与真实台账）；另跑一次真实台账面核对判据面未失效。
覆盖：正例 1 + 违规 4（空面/裸改/无归因/超天花板）+ 边界 3（待裁决可见、低余量告警、
        临时文件真实落盘往返）+ **差分对照组 1**（同一夹具只翻一个字段即由 PASS 变 FAIL，
        防「违规样本其实是干净数据」——R271/批1 同族假通过）。
登记：eval/stubs/registry.json → id=C31-inject-ledger
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402
import inject_ledger as il  # noqa: E402

BASE = 61472
CAP = 65536


def rec(**kw):
    base = {"ts": "2026-09-24T09:31:00", "actor_repo": "fenjue", "actor_commit": "6167c7b",
            "cause": "P1E-2 C25 立规：五文件实测 61472B 作棘轮基线（对标 OpenClaw/Anthropic）",
            "scope": "baseline_init", "delta_bytes": 0, "baseline_before": BASE,
            "baseline_after": BASE, "hard_cap": CAP, "decision": "applied"}
    base.update(kw)
    return base


GOOD = [rec()]
REAL_ST, REAL_DETAIL = v.check_c31_inject_ledger(skip_external=True)
SCAN_OK = REAL_ST in ('PASS', 'SKIP')


def chk(records, **kw):
    kw.setdefault('baseline', BASE)
    kw.setdefault('hard_cap', CAP)
    kw.setdefault('measured_total', BASE)
    return il.validate(records, ledger_path='fixture://', **kw)


CASES = [
    ('正例-基线经台账移动', GOOD, 'PASS', 'applied=1'),
    ('违规-空台账未初始化', [], 'FAIL', '未初始化'),
    ('违规-基线被裸改', [rec(baseline_after=50000)], 'FAIL', '裸改'),
    ('违规-applied 无署名', [rec(actor_commit='')], 'FAIL', 'actor_commit'),
    ('违规-硬顶超天花板', [rec(hard_cap=70000)], 'FAIL', '天花板'),
    ('边界-待裁决必须可见', GOOD + [rec(decision='pending', actor_repo='global_skills',
                            actor_commit='22990da', scope='growth_event', delta_bytes=3000,
                            baseline_after=0,
                            cause='注入区被外仓发布顶破 +3000B，待瘦身或 owner 经台账重标')],
     'PASS', '待裁决 1'),
    ('边界-余量低于5%告警', GOOD, 'PASS', '⚠', dict(measured_total=64472)),
]

ok = 0
for case in CASES:
    name, records, expect, needle = case[0], case[1], case[2], case[3]
    extra = case[4] if len(case) > 4 else {}
    st, detail = chk(records, **extra)
    good = (st == expect) and (needle in (detail or ''))
    ok += 1 if good else 0
    print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:100]))

# 差分对照组：与正例只差一个字段，判据必须翻转（否则说明夹具根本没进入判据分支=空转）
st_same, _d1 = chk(GOOD)
st_flip, _d2 = chk(GOOD, baseline=BASE + 1)
diff_ok = (st_same == 'PASS' and st_flip == 'FAIL')
ok += 1 if diff_ok else 0
print('[%s] 差分-基线+1 必须翻转 -> %s/%s' % ('PASS' if diff_ok else 'FAIL', st_same, st_flip))

# 真实落盘往返：证明 load/append 不只是内存把戏
tmpf = os.path.join(tempfile.gettempdir(), 'fenjue_stub_c31_%d.jsonl' % os.getpid())
try:
    il.append_entry(tmpf, rec())
    rt = (len(il.load(tmpf)) == 1 and il.load(tmpf)[0]['baseline_after'] == BASE)
    junk = open(tmpf, 'a', encoding='utf-8')
    junk.write('坏行 not json\n\n')
    junk.close()
    rt = rt and len(il.load(tmpf)) == 1  # 坏行不得污染判据面（R219d 族）
finally:
    if os.path.exists(tmpf):
        os.remove(tmpf)
ok += 1 if rt else 0
print('[%s] 边界-临时台账落盘往返 + 坏行容错' % ('PASS' if rt else 'FAIL'))

print('[%s] 真实台账面（判据面未失效）-> %s | %s'
      % ('PASS' if SCAN_OK else 'FAIL', REAL_ST, (REAL_DETAIL or '')[:80]))
ok += 1 if SCAN_OK else 0

print('stub_c31_inject_ledger: %d/%d' % (ok, len(CASES) + 3))
sys.exit(0 if ok == len(CASES) + 3 else 1)
