#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C17「实体排除清单跨消费方一致」（R276）

被包装对象：`consistency_consumers.check_entities()`（经 verify wrapper `check_c17_consumer_consistency`）
隔离手法：夹具文件建在 %TEMP%，直接把模块级 `ENTITIES` 表替换为夹具表（消费方路径指向夹具），
        不触任何真实消费方文件；跑后清理。
覆盖三条分支（普通排除 / 锚点行 / 禁止范围）× 正例、违规样本、边界。
登记：eval/stubs/registry.json → id=C17-consumers
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v        # noqa: E402
import consistency_consumers as cc          # noqa: E402

TMP = tempfile.mkdtemp(prefix='fenjue_stub_c17_')
ENT = 'fixture-skill'


def w(name, text):
    p = os.path.join(TMP, name)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    return p


P_OK = w('excluded.py', "NON_DOMAIN_FILES = {'%s'}\n" % ENT)
P_MISS = w('not_excluded.py', "NON_DOMAIN_FILES = {'other-thing'}\n")
P_ANCHOR_OK = w('anchor_ok.py', "SKIP = {'skill_ids.json', '%s'}\n" % ENT)
P_ANCHOR_BAD = w('anchor_bad.py', "SKIP = {'skill_ids.json'}\n")
P_ANCHOR_NONE = w('anchor_none.py', "# 该文件没有任何排除语句\n")
P_SCOPE_BAD = w('scope_bad.py', "MATRIX = ['wb', '%s', 'zc']\n" % ENT)
P_SCOPE_OK = w('scope_ok.py', "MATRIX = ['wb', 'zc']\n")
P_SCOPE_NOMATCH = w('scope_nomatch.py', "# 无 MATRIX 行\n")
MISSING = os.path.join(TMP, 'does_not_exist.py')

ANCHOR_SPEC = dict(reason='夹具：锚点行判据', anchor='skill_ids.json',
                   anchor_line_re=r'SKIP\s*=')
SCOPE_SPEC = dict(reason='夹具：退役实体不得出现在矩阵内', forbidden_in=True,
                  forbidden_scope=r'MATRIX\s*=\s*\[(.*?)\]')

CASES = [
    ('正例-普通排除：实体名已在清单内',
     {ENT: {'reason': '夹具', 'consumers': [('fixture', P_OK)], 'note': 'n'}}, 'PASS', ''),
    ('违规样本-a：消费方未排除实体',
     {ENT: {'reason': '夹具', 'consumers': [('fixture', P_MISS)], 'note': 'n'}}, 'FAIL', '未排除'),
    ('正例-b 锚点行：锚点与实体同行排除',
     {ENT: dict(ANCHOR_SPEC, consumers=[('fixture', P_ANCHOR_OK)], note='n')}, 'PASS', ''),
    ('违规样本-b 锚点行：排除锚点却漏掉实体',
     {ENT: dict(ANCHOR_SPEC, consumers=[('fixture', P_ANCHOR_BAD)], note='n')}, 'FAIL', '却未排除'),
    ('边界-a 锚点零命中 → 判据面失效（R247）',
     {ENT: dict(ANCHOR_SPEC, consumers=[('fixture', P_ANCHOR_NONE)], note='n')}, 'FAIL', '判据面失效'),
    ('违规样本-c 退役实体出现在禁止范围内',
     {ENT: dict(SCOPE_SPEC, consumers=[('fixture', P_SCOPE_BAD)], note='n')}, 'FAIL', '禁止范围'),
    ('正例-c 禁止范围内无实体',
     {ENT: dict(SCOPE_SPEC, consumers=[('fixture', P_SCOPE_OK)], note='n')}, 'PASS', ''),
    ('边界-b forbidden_scope 零命中 → 判据失效',
     {ENT: dict(SCOPE_SPEC, consumers=[('fixture', P_SCOPE_NOMATCH)], note='n')}, 'FAIL', '判据失效'),
    ('边界-c 消费方文件不存在',
     {ENT: {'reason': '夹具', 'consumers': [('gitone', MISSING)], 'note': 'n'}}, 'FAIL', '文件不存在'),
    ('边界-d 实体表为空 → 不得静默 PASS（R247）', {}, 'FAIL', '判据面为空'),
]

ok = 0
_saved = cc.ENTITIES
try:
    for name, table, expect, needle in CASES:
        cc.ENTITIES = table
        st, detail = v.check_c17_consumer_consistency()
        good = (st == expect) and (needle in (detail or ''))
        ok += 1 if good else 0
        print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:140]))
finally:
    cc.ENTITIES = _saved
    shutil.rmtree(TMP, ignore_errors=True)

print('stub_c17_consumers: %d/%d' % (ok, len(CASES)))
sys.exit(0 if ok == len(CASES) else 1)
