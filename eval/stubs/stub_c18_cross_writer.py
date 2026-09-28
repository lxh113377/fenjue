#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C18「多写入方产物契约一致」（R277 静态层）

被包装对象：`cross_writer_idempotence.check_static()`（经 verify wrapper `check_c18_cross_writer_contract`）
隔离手法：**每例一个独立夹具目录**（防跨例互相污染——首版把三支夹具放同目录导致正例被违规样本感染），
        替换模块级 `CONTRACTS` / `SCAN_DIRS` / `KNOWN_WRITERS`，不扫真实 eval/ 与 GM/scripts；跑后清理。
覆盖判据关键机理：v3「数据流精准」——写入点必须同行用路径变量或产物字面量才算写入方；
        并由 skip_if_line_has 排除非域文件行。
登记：eval/stubs/registry.json → id=C18-cross-writer
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v              # noqa: E402
import cross_writer_idempotence as cwi            # noqa: E402

TMP = tempfile.mkdtemp(prefix='fenjue_stub_c18_')


def newdir(name):
    d = os.path.join(TMP, name)
    os.makedirs(d, exist_ok=True)
    return d


def w(d, name, lines):
    with open(os.path.join(d, name), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


D_OK = newdir('ok')            # 写入点同行用路径变量 + 合规写法
D_BAD = newdir('bad')          # 未登记 + 命中违规特征
D_UNREL = newdir('unrelated')  # 提到产物但写入点与它无关（v2 误报族）
D_SKIP = newdir('skip')        # 写入行含 skip_if_line_has 令牌（非域文件）
D_EMPTY = newdir('empty')

w(D_OK, 'ok_writer.py', [
    "json_path = os.path.join(GM_ROOT, 'skill_content', 'x.json')",
    "with open(json_path, 'w') as f: json.dump(data, f, ensure_ascii=False, indent=2)",
])
w(D_BAD, 'bad_writer.ps1', [
    "$JsonPath = Join-Path $root 'skill_content\\x.json'",
    # 违规特征与写入调用必须**同一行**（check_static 只对写入点那一行跑 bad_patterns）
    "$data | ConvertTo-Json -Compress | Set-Content -LiteralPath $JsonPath",
])
w(D_UNREL, 'unrelated_writer.py', [
    "json_path = os.path.join(GM_ROOT, 'skill_content', 'x.json')   # 提到产物…",
    "with open('other.json', 'w') as f: json.dump(data, f, ensure_ascii=False, indent=2)   # …但写入点与它无关",
])
w(D_SKIP, 'skip_ids.py', [
    "with open(os.path.join(GM_ROOT, 'skill_content', 'skill_ids.json'), 'w') as f: json.dump(data, f, indent=2)",
])

CONTRACT = {
    'skill_content/{domain}.json': {
        'desc': '夹具契约', 'artifact_markers': ['skill_content'],
        'write_calls': [r'json\.dump\(', r'Set-Content', r'WriteAllText'],
        'skip_if_line_has': ['skill_ids.json', 'index_manifest.json'],
        'ok_patterns': {'python_indent2': r'json\.dump\([^)]*indent\s*=\s*2'},
        'bad_patterns': {'ps_compress_no_norm': r'ConvertTo-Json[^\n]*-Compress',
                         'ps_compress_2': r'ConvertTo-Json[^\n]*\-Compress'},
        'note': '夹具',
    }
}

CASES = [
    ('正例 已登记写入方（合规）',
     CONTRACT, [D_OK], ['ok_writer.py'], 'PASS', ''),
    ('违规样本-a 未登记写入方 + 命中违规特征',
     CONTRACT, [D_BAD], [], 'FAIL', '写法不合契约'),
    ('违规样本-b 写入点同行无路径变量/产物字面量 → 不算写入方（零命中，R247）',
     CONTRACT, [D_UNREL], [], 'FAIL', '未发现任何写入方'),
    ('边界-a 写入行命中 skip_if_line_has → 非域文件不计（零命中，R247）',
     CONTRACT, [D_SKIP], [], 'FAIL', '未发现任何写入方'),
    ('边界-b 扫描目录为空 → 判据面失效（R247）',
     CONTRACT, [D_EMPTY], [], 'FAIL', '未发现任何写入方'),
    ('边界-c 契约表为空 → 不得静默 PASS（R247）',
     {}, [D_OK], [], 'FAIL', 'CONTRACTS 为空'),
]

ok = 0
_sv = (cwi.CONTRACTS, cwi.SCAN_DIRS, cwi.KNOWN_WRITERS)
try:
    for name, contracts, dirs, known, expect, needle in CASES:
        cwi.CONTRACTS = contracts
        cwi.SCAN_DIRS = dirs
        cwi.KNOWN_WRITERS = {k: '夹具登记' for k in known}
        st, detail = v.check_c18_cross_writer_contract()
        good = (st == expect) and (needle in (detail or ''))
        ok += 1 if good else 0
        print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:140]))
finally:
    cwi.CONTRACTS, cwi.SCAN_DIRS, cwi.KNOWN_WRITERS = _sv
    shutil.rmtree(TMP, ignore_errors=True)

print('stub_c18_cross_writer: %d/%d' % (ok, len(CASES)))
sys.exit(0 if ok == len(CASES) else 1)
