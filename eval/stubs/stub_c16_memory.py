#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C16 ⑥ 记忆文档「当前口径」段一致性 + ⑦ 域数一致性（R241 历史段豁免）

判据面：只扫带「当前口径」锚点的行，比对其中 skill 数 / 域数 / 总分 == 真相源；
       口径沿革/已完成条目段不扫（否则历史留痕会被误判为过期）。
夹具：**合成产物 + 合成记忆文档**（不依赖真实 STATUS.md），期望值全部当场从真相源推导
     （注册表 skill 数 / skill_content 域桶 / truth_constants behavior_core / 端数），
     禁用过期字面量（R263：原版硬编码 181.6，活体升到 183.9 后正例即失败）。
登记：eval/stubs/registry.json → id=C16-memory-current
"""
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402

TMP = tempfile.mkdtemp(prefix='fenjue_stub_c16mem_')

# —— 真相源当场推导（无基准即不得判过，R247）——
_true_skills = len(v.load_json(os.path.join(v.REGISTRY, 'unified-skills-index.json')).get('skills', {}))
_domain_files = [f for f in os.listdir(v.SKILL_CONTENT)
                 if f.endswith('.json') and f not in ('skill_ids.json', 'index_manifest.json')]
_true_domains = len({f[:-5] for f in _domain_files})
_true_ep = len(v.ENDPOINTS)
_true_bc = (int(re.sub(r'\D', '', v.BEHAVIOR_CORE_VERSION) or 0),
            v.BEHAVIOR_CORE_ANCHORS, v.BEHAVIOR_CORE_VALID)
# 总分基准：取真实产物「机器实测综合」行——桩不重算评分卡，只复用真相源渲染值
_real = [os.path.join(PROJ, r) for r in v.C16_WATCH]
_totals = [float(m.group(1)) for p in _real if os.path.exists(p)
           for m in v.C16_TOTAL_RE.finditer(open(p, encoding='utf-8').read())]
_true_total = sorted(set(_totals))[0] if _totals else 0.0
if not (_true_skills and _true_domains and _true_total):
    print('基准不可得（skills=%s domains=%s total=%s）→ 桩不可信，判 0/1'
          % (_true_skills, _true_domains, _true_total))
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1)


def mk(name, body):
    q = os.path.join(TMP, name)
    Path(q).write_text(body, encoding='utf-8', newline='\n')
    return q


def artifact(skills=None, domains=None, ep=None, bc=None, total=None, sum_total=None):
    """合成 STATUS 家族产物：六线分之和 == total（容差内）。"""
    skills = _true_skills if skills is None else skills
    domains = _true_domains if domains is None else domains
    ep = _true_ep if ep is None else ep
    bc = _true_bc if bc is None else bc
    total = _true_total if total is None else total
    st = total if sum_total is None else sum_total
    five = [30.0] * 5
    lines = ''.join('  - 线%d = %.1f/33\n' % (i + 1, x) for i, x in enumerate(five))
    lines += '  - 线6 = %.1f/33\n' % round(st - sum(five), 1)
    return mk('artifact_%s.md' % abs(hash((skills, domains, ep, bc, total, sum_total))),
              '# STATUS（合成）\n\n'
              '| behavior_core | V%d（%d锚点/%d有效） |\n\n'
              '- 注册表实测：%d skills\n- 域桶：%d 域\n- 端矩阵：%d端同步\n'
              '- 机器实测综合: %.1f/200\n%s'
              % (bc[0], bc[1], bc[2], skills, domains, ep, total, lines))


def memory(skills=None, domains=None, total=None, with_anchor=True, note=''):
    skills = _true_skills if skills is None else skills
    domains = _true_domains if domains is None else domains
    total = _true_total if total is None else total
    if not with_anchor:
        return mk('mem_noanchor.md', '# 无锚点文档\n\n- 与口径无关的内容\n')
    body = ('# 记忆\n\n- **当前口径（2026-09-23 实测）**：三方一致 **%d skill / %d 域**；'
            '六线评分卡 **%.1f/200**\n' % (skills, domains, total))
    if note:
        body += note + '\n'
    return mk('mem_%s_%s_%s.md' % (skills, domains, total), body)


# 历史沿革段（含过期数字，但无「当前口径」锚点 → 必须豁免不判）
HISTORY = '> 口径沿革 135 → 160 → 156 → 120 → 151（历史留痕段，应豁免不判）\n'

CASES = [
    ('正例 口径一致 + 含历史沿革段(应豁免)',
     artifact(), [memory(note=HISTORY)], 'PASS', ''),
    ('违规样本-a 当前口径 skill 数过期',
     artifact(), [memory(skills=_true_skills + 7)], 'FAIL', '当前口径 skill 数过期'),
    ('违规样本-b 当前口径域数过期',
     artifact(), [memory(domains=_true_domains + 1)], 'FAIL', '域数过期'),
    ('违规样本-c 产物总分与六线之和不符',
     artifact(total=_true_total, sum_total=_true_total + 9.9), [memory()], 'FAIL', '总分与六线之和不等'),
    ('边界-a 记忆文档无「当前口径」锚点行',
     artifact(), [memory(with_anchor=False)], 'FAIL', '未解析到'),
    ('边界-b 产物缺失（输入为空）',
     os.path.join(TMP, 'missing_artifact.md'), [memory()], 'FAIL', '产物缺失'),
]

ok = 0
for name, af, cfs, expect, needle in CASES:
    st, detail = v.check_c16_artifact_content_consistency(files=[af], current_files=cfs)
    good = (st == expect) and (needle in (detail or ''))
    ok += 1 if good else 0
    print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:150]))

shutil.rmtree(TMP, ignore_errors=True)
print('stub_c16_memory: %d/%d' % (ok, len(CASES)))
sys.exit(0 if ok == len(CASES) else 1)
