#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C16 ⑦ 域数一致性（R272 新判据交付契约：正例 + 违规样本 + 边界）

判据面：C16 第 ⑦ 段 —— skill_content 域桶数 == 产物/记忆文档声明的域数。
登记：eval/stubs/registry.json → id=C16-domain
"""
import os
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402

REAL = [os.path.join(PROJ, 'STATUS.md'), os.path.join(PROJ, 'STATUS.part1.md')]
CUR = [os.path.join(PROJ, 'memory', '01-goal.md'),
       os.path.join(PROJ, 'memory', '07-next-steps.md')]
TMP = tempfile.mkdtemp(prefix='fenjue_stub_c16domain_')


def clone(paths, mutate, tag):
    out = []
    for p in paths:
        with open(p, encoding='utf-8') as f:
            t = f.read()
        q = os.path.join(TMP, '%s_%s' % (tag, os.path.basename(p)))
        with open(q, 'w', encoding='utf-8', newline='\n') as f:
            f.write(mutate(t))
        out.append(q)
    return out


# 2026-09-24 GitHub 对标轮修复：**夹具改写必须由实测派生，且必须断言自己改到了东西**。
# 原夹具把替换锚点写死成字面量（'151 skills' / '13 域'）。注册表 151→167 对齐后
# `t.replace('151 skills', ...)` 变成空操作 ⇒「违规样本」其实是一份**干净文档** ⇒
# C16 判 PASS ⇒ 桩自红（判据与数据都没错，是桩在说谎；R268「mtime 新鲜≠内容正确」的桩层同族）。
# 若不做 changed 断言，这类桩会在锚点漂移时**静默退化为永真/永假**，比没有桩更危险。
import re  # noqa: E402


MUT_HITS = {}   # tag -> 改写命中次数（跨文件累计）


def _must_change(pattern, repl, tag):
    """改写真实产物构造违规样本；命中数按 tag 累计，CASES 建完后统一断言非空。

    注：命中数**按 tag 跨文件累计**而非逐文件断言 —— REAL 里 STATUS.md 本就不含「N 域」行，
    逐文件断言会把合法场景误判为空转（2026-09-24 本桩首次实跑即实测到此）。"""
    rx = re.compile(pattern)

    def _m(t):
        new, n = rx.subn(repl, t)
        MUT_HITS[tag] = MUT_HITS.get(tag, 0) + n
        return new
    return _m


def drop_domain(t):
    new, n = re.subn(r'\d+(?= 域(?!表|数))', '', t)
    MUT_HITS['b3'] = MUT_HITS.get('b3', 0) + n
    return new


CASES = [
    ('正例 域数一致(实测)', REAL, CUR, 'PASS'),
    ('违规样本 域数过期 14',
     clone(REAL, _must_change(r'\b13(?= 域(?!表|数))', '14', 'b1'), 'b1'), CUR, 'FAIL'),
    # 模式对齐 C16_SKILLS_RE 的解析面（`N skills`），保证造出来的过期值必被扫到
    ('违规样本 skill 数过期 120',
     clone(REAL, _must_change(r'\b\d+(?= skills)', '120', 'b2'), 'b2'), CUR, 'FAIL'),
    ('边界 零命中(产物与记忆均无「N 域」)',
     clone(REAL, drop_domain, 'b3'), clone(CUR, drop_domain, 'b3c'), 'FAIL'),
]

_dead = sorted(t for t in ('b1', 'b2', 'b3') if not MUT_HITS.get(t))
if _dead:
    raise AssertionError('桩夹具改写空转（tag %s：真实产物中 0 命中）——锚点已漂移，'
                         '对应用例判据面为空，禁当有效样本' % _dead)

ok = 0
for name, files, cur, expect in CASES:
    st, detail = v.check_c16_artifact_content_consistency(files=files, current_files=cur)
    good = (st == expect)
    ok += 1 if good else 0
    print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:170]))

shutil.rmtree(TMP, ignore_errors=True)
print('stub_c16_domain: %d/%d' % (ok, len(CASES)))
sys.exit(0 if ok == len(CASES) else 1)
