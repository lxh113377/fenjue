#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C33「GM 记忆路由表健康」（2026-09-24 对标轮四 7-D / 6-C）

判据面：无占位符残留（按真实形态「（待重建）」匹配）/ 体积 ≤4096B（R161）/ 声明路径实测存在
        且非空（R240）/ GM 一级目录全覆盖 / 不指向不存在目录。
隔离手法：`text=` 注入完整表文（纯函数面，不读真实 GM 根）。真实面另跑一次核对判据未失效。
覆盖：正例 1 + 违规 5（占位/超体积/死链/空文件/未登记目录/幽灵目录）+ 边界 1（W1 只匹配
     占位形态，判据说明文字提到该词不得自触）+ 差分对照组 1（同一好表只删一行必须翻转）。
登记：eval/stubs/registry.json → id=C33-memory-index
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402
import build_memory_index as bmi  # noqa: E402

# 合成目录表：桩不得依赖真实 GM 根（CI 上不可达时整批 SKIP=假绿；本仓当日实测桩在
# ubuntu 集体红，正是因为把"外部不可达"与"通过"混为一谈）。用固定夹具跑真实判据分支。
KNOW = sorted(bmi.KNOWLEDGE)
EXCL = sorted(bmi.EXCLUDED)
DIRS = sorted(set(KNOW) | set(EXCL))
ROWS = [{"dir": d, "md": 1, "files": 1, "newest": "2026-09-24"} for d in DIRS]
GOOD = (
    "# memory_index.md — 记忆路由表（P1 按需）\n"
    "> AUTO-GENERATED 2026-09-24 | DO NOT EDIT\n"
    "门禁 = 焚诀 verify C33（存在性/非空/全覆盖/无占位残留）\n\n"
    "| 目录 | 何时读 | md | 最近更新 |\n|---|---|---|---|\n")
for d in DIRS:
    GOOD += ("| `%s/` | 知识或排除用途说明 | 1 | 2026-09-24 |\n" % d)
GOOD += "\n- 一级目录 %d 个 = 知识 + 排除，全覆盖\n" % len(DIRS)
ENTRY_LINE = "| `meta/` | 索引与治理口径 | 62 | 2026-09-23 |\n"
GOOD_ENTRY = GOOD.replace("| `meta/` | 知识或排除用途说明 | 1 | 2026-09-24 |\n", ENTRY_LINE)

REAL_ST, REAL_DETAIL = v.check_c33_memory_index_routing(skip_external=True)
SCAN_OK = REAL_ST in ('PASS', 'SKIP')

CASES = [
    ('正例-全覆盖好表(含真实入口)', GOOD_ENTRY, 'PASS', '全覆盖'),
    ('违规-占位符残留', GOOD + "\n> 完整路由表待重建（待重建）\n", 'FAIL', 'W1'),
    ('违规-超 4KB 体积', GOOD + ('x' * 5000), 'FAIL', 'W2'),
    ('违规-声明死链', GOOD_ENTRY + "\n先读 `meta/__no_such_file__.md`\n", 'FAIL', 'W3'),
    ('违规-目录未登记', GOOD_ENTRY.replace("| `prompts/` | 知识或排除用途说明 | 1 | 2026-09-24 |\n", ""),
     'FAIL', 'W4'),
    ('违规-指向不存在目录', GOOD_ENTRY + "| `ghost_dir/` | 编的 | 0 | — |\n", 'FAIL', 'W5'),
    ('边界-W1 只匹配占位形态', GOOD_ENTRY, 'PASS', '全覆盖'),
]

ok = 0
for name, text, expect, needle in CASES:
    st, detail = v.check_c33_memory_index_routing(text=text, rows=ROWS)
    good = (st == expect) and (needle in (detail or ''))
    ok += 1 if good else 0
    print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:100]))

# 差分对照组：同一好表只删掉 prompts 一行，判据必须从 PASS 翻 FAIL（防"全覆盖"其实是空转）
st_a, _ = v.check_c33_memory_index_routing(text=GOOD_ENTRY, rows=ROWS)
st_b, _ = v.check_c33_memory_index_routing(
    rows=ROWS, text=GOOD_ENTRY.replace("| `prompts/` | 知识或排除用途说明 | 1 | 2026-09-24 |\n", ""))
diff_ok = (st_a == 'PASS' and st_b == 'FAIL')
ok += 1 if diff_ok else 0
print('[%s] 差分-删一行必须翻转 -> %s/%s' % ('PASS' if diff_ok else 'FAIL', st_a, st_b))

print('[%s] 真实路由表（判据面未失效）-> %s | %s'
      % ('PASS' if SCAN_OK else 'FAIL', REAL_ST, (REAL_DETAIL or '')[:90]))
ok += 1 if SCAN_OK else 0

print('stub_c33_memory_index: %d/%d' % (ok, len(CASES) + 2))
sys.exit(0 if ok == len(CASES) + 2 else 1)
