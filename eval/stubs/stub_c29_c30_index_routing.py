#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：verify C29（index.md 与派生评分产物对账）+ C30（路由静态表目标存活与空洞棘轮）

登记：eval/stubs/registry.json → id=C29-C30-index-routing（2026-09-24 GitHub 对标轮）

判据面：
  C29 = 根 index.md 渲染的端点/注册表/门禁范围/评分卡口径 == 真相源当场实测；
        且 reports/recheck_scorecard.json.overall == STATUS.md 机器实测综合（补 C14 只验 mtime 盲区）。
  C30 = CONTEXT_SKILL_MAP / direct_map 的目标必须存在于注册表活跃集；空标签=覆盖空洞，
        数只许降不许升（基线 eval/routing_holes_baseline.json）。

关键教训（本桩存在的理由，R238）：**接线必须被测**。C30 首版在 checks 注册表里被写成
`_check_fn(...)(skip_external)`，skip_external(False) 落到第一个形参 map_ 上 ⇒
`(map_ or {})` 退化成 {} ⇒ 门禁扫 0 条映射仍判 PASS（真·假通过）。
纯函数面单测当时全绿，只有走「注册表真实调用路径」的集成断言才拦得下 —— 故本桩含
CASES_INT（层 b 集成面 + 对照组），且集成面必须观察到 scanned>0。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PROJ, 'eval'))
import verify_truth_consistency as v  # noqa: E402

TRUTH = {'endpoints': 8, 'active_track': 'track_200', 'total': 200, 'pass_line': 170}

# 注册表条数取当场实测（禁写死：写死会让本桩在「正常新增一个技能」时假红）
_NSK = len(v.load_registry_uni().get('skills', {}))
_GATE_N = max(int(x) for x in re.findall(r"\('C(\d+)'",
                                         open(os.path.join(PROJ, 'eval',
                                              'verify_truth_consistency.py'),
                                              encoding='utf-8').read()))

OK_INDEX = """# 焚诀 — 项目总索引
> 多agent统一记忆+技能路由系统 | 八端(wb / tr / cx / hm / zc / oc / qw / qd) | 六大主线
> 门禁: eval/verify_truth_consistency.py C1~C{G}
| 端点数 | 8（wb / tr / cx / hm / zc / oc / qw / qd） |
| 评分卡 | track_200 TOTAL=200 PASS=170（85%） |
| 机器实测综合 | 182.5/200 (91.2%) |
- `skill/registry/unified-skills-index.json` — 注册表（{N} 条，build_registry.py 生成）
""".format(G=_GATE_N, N=_NSK)
BAD_EP = OK_INDEX.replace('| 端点数 | 8', '| 端点数 | 6')
BAD_HEAD = OK_INDEX.replace('八端(wb', '六端(wb')
BAD_TRACK = OK_INDEX.replace('track_200 TOTAL=200 PASS=170', 'track_150 TOTAL=150 PASS=120')
BAD_GATE = OK_INDEX.replace('C1~C%d' % _GATE_N, 'C1~C%d' % (_GATE_N - 6))
BAD_REG = OK_INDEX.replace('注册表（%d 条' % _NSK, '注册表（%d 条' % (_NSK - 16))
NO_ROWS = '# 索引\n什么都没有\n'
STATUS_OK = '机器实测综合: 182.5/200 (91.2%)\n'
SC_OK = {'overall': 182.5}
SC_DRIFT = {'overall': 175.1}
SC_NOLINE = {}

_N_PAIRS = len(v.load_json(os.path.join(PROJ,'eval','direct_map.json')))
LIVE = ['debugging-fixing', 'A-skill-manager', 'cross-platform-agent-sync', 'A-prompt-better']
MAP_OK = {'报错': ['debugging-fixing'], '路由': [], '提升': []}
MAP_DEAD = {'安装': ['skill-install'], '报错': ['debugging-fixing']}
MAP_NEWHOLE = {'报错': ['debugging-fixing'], '新空洞': []}
MAP_EMPTY = {}
PAIRS_OK = [[r'^修.?bug$', 'debugging-fixing'], [r'^不路由$', 'NONE']]
PAIRS_DEAD = [[r'^装个skill$', 'skill-install']]
BASE_OK = {'empty_tags': ['路由', '提升']}

CASES = [
    # ---- C29 ----
    ('C29 正例 全对', dict(index_text=OK_INDEX, scorecard=SC_OK, status_text=STATUS_OK,
                          gate_max=_GATE_N, truth=TRUTH), 'PASS', '对账一致'),
    ('C29 违规-a 端点数过期', dict(index_text=BAD_EP, scorecard=SC_OK, status_text=STATUS_OK,
                              gate_max=_GATE_N, truth=TRUTH), 'FAIL', '端点数过期'),
    ('C29 违规-b 头部中文端数打脸', dict(index_text=BAD_HEAD, scorecard=SC_OK,
                                    status_text=STATUS_OK, gate_max=_GATE_N, truth=TRUTH),
     'FAIL', '头部端数标签与真相源矛盾'),
    ('C29 违规-c 评分卡 track 错配', dict(index_text=BAD_TRACK, scorecard=SC_OK,
                                    status_text=STATUS_OK, gate_max=_GATE_N, truth=TRUTH),
     'FAIL', '评分卡口径错配'),
    ('C29 违规-d 门禁范围过期', dict(index_text=BAD_GATE, scorecard=SC_OK, status_text=STATUS_OK,
                               gate_max=_GATE_N, truth=TRUTH), 'FAIL', '门禁范围过期'),
    ('C29 违规-e 注册表条数过期', dict(index_text=BAD_REG, scorecard=SC_OK, status_text=STATUS_OK,
                                gate_max=_GATE_N, truth=TRUTH), 'FAIL', '注册表条数过期'),
    ('C29 违规-f 产物与 STATUS 脱节', dict(index_text=OK_INDEX, scorecard=SC_DRIFT,
                                     status_text=STATUS_OK, gate_max=_GATE_N, truth=TRUTH),
     'FAIL', '评分产物与 STATUS 脱节'),
    ('C29 边界 漂移 0.2 在容差内（主线⑥由 route_trace 驱动，天生非确定）',
     dict(index_text=OK_INDEX, scorecard={'overall': 182.5},
          status_text='机器实测综合: 182.3/200 (91.2%)\n', gate_max=_GATE_N, truth=TRUTH),
     'PASS', '对账一致'),
    ('C29 违规-g 产物缺 overall（零命中）', dict(index_text=OK_INDEX, scorecard=SC_NOLINE,
                                        status_text=STATUS_OK, gate_max=_GATE_N, truth=TRUTH),
     'FAIL', '无 overall'),
    ('C29 违规-h index 无任何可比行（R247）', dict(index_text=NO_ROWS, scorecard=SC_OK,
                                             status_text=STATUS_OK, gate_max=_GATE_N, truth=TRUTH),
     'FAIL', '零命中'),
    ('C29 违规-i STATUS 无总分行（基准不可得）', dict(index_text=OK_INDEX, scorecard=SC_OK,
                                          status_text='什么都没有\n', gate_max=_GATE_N, truth=TRUTH),
     'FAIL', 'STATUS.md 未解析'),
    # ---- C30 ----
    ('C30 正例 目标全存活 + 空洞==基线', dict(map_=MAP_OK, direct_pairs=PAIRS_OK,
                                       baseline=BASE_OK), 'PASS', '死 0'),
    ('C30 违规-a 退役目标仍在映射表', dict(map_=MAP_DEAD, direct_pairs=PAIRS_OK,
                                      baseline=BASE_OK), 'FAIL', 'skill-install'),
    ('C30 违规-b direct_map 指向死技能', dict(map_=MAP_OK, direct_pairs=PAIRS_DEAD,
                                        baseline=BASE_OK), 'FAIL', 'direct_map'),
    ('C30 违规-c 新增空洞未登记', dict(map_=MAP_NEWHOLE, direct_pairs=PAIRS_OK,
                                 baseline=BASE_OK), 'FAIL', '新增覆盖空洞'),
    ('C30 违规-d 两面皆空（判据面为空）', dict(map_=MAP_EMPTY, direct_pairs=[],
                                      baseline=BASE_OK), 'FAIL', '0 条目标'),
    ('C30 违规-e 基线缺 empty_tags', dict(map_=MAP_OK, direct_pairs=PAIRS_OK,
                                    baseline={}), 'FAIL', '缺 empty_tags'),
    ('C30 边界-a 空洞少于基线（棘轮下降合法）', dict(map_={'报错': LIVE}, direct_pairs=PAIRS_OK,
                                          baseline=BASE_OK), 'PASS', '死 0'),
    ('C30 边界-b NONE 哨兵不算死目标', dict(map_={'报错': LIVE}, direct_pairs=[['x', 'NONE']],
                                     baseline={'empty_tags': []}), 'PASS', '死 0'),
]


def _scanned_of(detail):
    m = re.search(r'扫描 (\d+) 目标', detail or '')
    return int(m.group(1)) if m else -1


ok = 0
for name, kw, expect, needle in CASES:
    fn = v.check_c29_index_reconciliation if name.startswith('C29') else v.check_c30_routing_target_liveness
    try:
        st, detail = fn(**kw)
    except Exception as e:  # noqa: BLE001
        st, detail = ('EXC', repr(e))
    good = (st == expect) and (needle in (detail or ''))
    ok += 1 if good else 0
    print('[%s] %s -> %s | %s' % ('PASS' if good else 'FAIL', name, st, (detail or '')[:120]))

# ---- 层 b：集成面（走 checks 注册表的真实调用路径）+ 对照组 ----
print('--- 集成面（R238：接线必须被测）---')
src = open(os.path.join(PROJ, 'eval', 'verify_truth_consistency.py'), encoding='utf-8').read()
int_ok = 0
for cid, fname in (('C29', 'check_c29_index_reconciliation'),
                   ('C30', 'check_c30_routing_target_liveness')):
    m = re.search(r"\('%s',.*?_check_fn\('%s'\)(\([^)]*\))" % (cid, fname), src, re.S)
    call = (m.group(1) if m else 'NOMATCH')
    # 判据：注册面必须**无位置参**（有位置参 = 把 skip_external 之类喂进业务形参，实测致假通过）
    passed_empty_args = (call == '()')
    st, detail = getattr(v, fname)() if callable(getattr(v, fname, None)) else ('ERR', '')
    if cid == 'C30':
        wired = _scanned_of(detail) > _N_PAIRS     # 必须同时看到 direct_map 与映射表两面
    else:
        wired = '对账一致' in (detail or '')
    good = passed_empty_args and st == 'PASS' and wired
    int_ok += 1 if good else 0
    print('[%s] %s 注册调用面=%s 实跑=%s detail=%s' %
          ('PASS' if good else 'FAIL', cid, call or '?', st, (detail or '')[:90]))

# 对照组：故意按「带位置参」调用 C30，必须退化出与假通过相同的症状（证明该缺陷真实存在过）
try:
    _st, _d = v.check_c30_routing_target_liveness(False)   # == 当年 bug 的调用形态
    ctrl = (_st == 'PASS' and _scanned_of(_d) <= _N_PAIRS)
except Exception:  # noqa: BLE001
    ctrl = False
print('[%s] 对照组 位置参误接必致 scanned 掉到 direct-only（证明判据可被接线打穿）' %
      ('PASS' if ctrl else 'FAIL'))
int_ok += 1 if ctrl else 0

total = len(CASES) + 3
ok += int_ok
print('stub_c29_c30_index_routing: %d/%d' % (ok, total))
sys.exit(0 if ok == total else 1)
