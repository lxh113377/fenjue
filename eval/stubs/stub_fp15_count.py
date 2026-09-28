#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：lessons_hitrate FP-15 count_matches_source（文档计数 == 注册表实测）

本桩同时守护两条教训：
  ① 判据必须消费**传入样本**（首版误写 read_text(...) 重读文件 → 4 组桩返回同一结论）
  ② 判据不得硬编码**症状字面量**（原 not_contains_any "总计：151" 与 build_indexes 注入行互斥 → 恒假失败）
登记：eval/stubs/registry.json → id=FP15-count-source
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import lessons_hitrate as lh  # noqa: E402
from config import GLOBAL_MEMORY  # noqa: E402

CHECK = {
    'type': 'count_matches_source',
    'index': os.path.join(GLOBAL_MEMORY, 'skill_routing.md'),
    'source': 'skill/registry/unified-skills-index.json',
    'pattern': r'\*\*总计：(\d+)\s*个 skill\s*/\s*(\d+)\s*个领域\*\*',
}

# 真实注册表条数（当场读，不写死）
_reg = lh.resolve_targets(['skill/registry/unified-skills-index.json'])
_true_n = None
if _reg:
    import json
    with open(_reg[0], encoding='utf-8') as f:
        _d = json.load(f)
    _sk = _d.get('skills', _d)
    _true_n = len(_sk)

# 桩自身的反漂移（2026-09-24 GitHub 对标轮实测修复）：
# 上面注释喊「当场读，不写死」，CASES 却把正例数字写死成 151 —— 上一提交「注册表 151→167
# 对齐」后本桩的正例立刻变假红（判据没错、数据没错，是**桩在说谎**）。
# 结论：**夹具里的期望值必须由同一份实测派生**，"过期值"用 true_n±偏移造，禁写绝对数。
assert _true_n, '注册表条数读取失败（桩判据面为空，不得继续）'
_WRONG_A = _true_n + 7
_WRONG_B = _true_n - 13 if _true_n > 20 else _true_n + 19
assert _WRONG_A != _true_n and _WRONG_B != _true_n

CASES = [
    ('正例 计数一致(实测派生)', '**总计：%d 个 skill / 13 个领域**' % _true_n, True),
    ('违规样本 计数过期 A', '**总计：%d 个 skill / 13 个领域**' % _WRONG_A, False),
    ('违规样本 计数过期 B', '**总计：%d 个 skill / 13 个领域**' % _WRONG_B, False),
    ('边界 零命中(无计数行)', '本文件无计数行', False),
]

ok = 0
for name, text, expect in CASES:
    r, ev = lh.run_check(CHECK, text, 'stub')
    good = (r == expect)
    ok += 1 if good else 0
    print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, r, ev))

print('stub_fp15_count: %d/%d (注册表实测 %s)' % (ok, len(CASES), _true_n))
sys.exit(0 if ok == len(CASES) else 1)
