#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C23「技能文档落点声明合规」（2026-09-23 P2-6）

判据面：技能文档（.md）中声明的产物落点必须 ① 真实存在 ② 被 noise 认可
       （不得是 `_bak` 这类经 junction 会被 noise 二级扫描判 VIOL 的落点）。
隔离手法：走 `decls=` / `baseline=` 注入夹具（纯函数面，不扫真实技能库）；
         另跑一次真实扫描核对判据面未失效。
覆盖：正例 2 + 违规样本 4 + 边界 4（含历史文件/历史标记行豁免、相对路径跳过、
     声明数==基线边界、真实扫描面 ≥ 基线）。
登记：eval/stubs/registry.json → id=C23-landing
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402

S = chr(92)
OK_REL = ('A-x/SKILL.md', 10, '_trash', '_trash%s<标签>_<ts>%s' % (S, S),
          '备份到 `_trash%s<标签>_<ts>%s`' % (S, S))
OK_ABS = ('A-x/SKILL.md', 11, '_trash', 'D:%sglobal_memory%s_trash%st%s' % (S, S, S, S),
          '备份到 `D:%sglobal_memory%s_trash%st%s`' % (S, S, S, S))
GONE = ('A-x/SKILL.md', 12, '_trash', 'D:%s__c23_no_such_root__%sx%s' % (S, S, S),
        '备份到 `D:%s__c23_no_such_root__%sx%s`' % (S, S, S))
BAK = ('A-x/SKILL.md', 13, '_bak', '_bak%s<标签>_<ts>%s' % (S, S),
       '备份到 `_bak%s<标签>_<ts>%s`' % (S, S))
ODD = ('A-x/SKILL.md', 14, 'foo_backup', 'foo_backup%sx%s' % (S, S),
       '备份到 `foo_backup%sx%s`' % (S, S))
HISTF = ('A-x/references/version-history.md', 15, '_bak', '_bak%sx%s' % (S, S),
         '备份到 `_bak%sx%s`' % (S, S))
HISTM = ('A-x/SKILL.md', 16, '_bak', '_bak%sx%s' % (S, S),
         '原为 备份到 `_bak%sx%s`，现已统一 _trash' % (S, S))
TMPREL = ('A-x/SKILL.md', 17, '_temp', '_temp%sx%s' % (S, S),
          '备份到 `_temp%sx%s`' % (S, S))

SCAN_N = len(v._c23_scan())
SCAN_OK = SCAN_N >= v.C23_BASELINE_DECLS

CASES = [
    ('正例-a 相对落点 _trash（被认可）', dict(decls=[OK_REL], baseline=1), 'PASS', ''),
    ('正例-b 绝对落点真实存在', dict(decls=[OK_ABS], baseline=1), 'PASS', ''),
    ('违规-a W1 声明面收缩（低于基线）', dict(decls=[OK_REL], baseline=5), 'FAIL', 'W1'),
    ('违规-b W2 绝对落点不存在', dict(decls=[GONE], baseline=1), 'FAIL', 'W2'),
    ('违规-c W3 落点 _bak 命中 noise VIOL 面', dict(decls=[BAK], baseline=1), 'FAIL', 'W3'),
    ('违规-d W3 落点命中 noise VIOL 模式', dict(decls=[ODD], baseline=1), 'FAIL', 'W3'),
    ('边界-a 历史文件豁免（version-history）', dict(decls=[HISTF], baseline=1), 'PASS', ''),
    ('边界-b 历史标记行豁免（原为/现已）', dict(decls=[HISTM], baseline=1), 'PASS', ''),
    ('边界-c 相对路径跳过存在性校验', dict(decls=[TMPREL], baseline=1), 'PASS', ''),
    ('边界-d 声明数 == 基线（不高不低）', dict(decls=[OK_REL, OK_ABS], baseline=2), 'PASS', ''),
    ('边界-e 真实扫描面 >= 基线（判据面未失效）', None, 'SCAN', ''),
]

ok = 0
for name, kw, expect, needle in CASES:
    if kw is not None:
        st, detail = v.check_c23_skill_doc_landing(**kw)
    else:
        st, detail = ('SCAN' if SCAN_OK else 'SCAN-LOW', '声明 %d / 基线 %d' % (SCAN_N, v.C23_BASELINE_DECLS))
    good = (st == expect) and (needle in (detail or ''))
    ok += 1 if good else 0
    print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:110]))

print('stub_c23_landing: %d/%d' % (ok, len(CASES)))
sys.exit(0 if ok == len(CASES) else 1)
