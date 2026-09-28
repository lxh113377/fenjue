# -*- coding: utf-8 -*-
"""verify_checks.status_layer — 检查函数族（P1-16 拆包，2026-09-23）。

状态/助手经 `_root.<name>` 晚绑定（ctx 单例 = verify_truth_consistency），
monkeypatch(vtc, <state>/<check>) 契约不变。
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

import verify_truth_consistency as _root  # noqa: E402  # ctx 单例


def check_c14_artifact_freshness(skip_external=False):
    """C14(补充): 关键决策产物时效（防「旧快照当现状」）。

    STATUS/评分卡/盲测产物是所有对外决策的依据。停更后展示的「绿」是历史快照的绿，
    而非当下的绿——2026-09-06 实测：STATUS 停更 20 天，期间评分卡口径由 track_150
    (149.5/150 达标) 切到 track_200 (150.1/200 未达标)，旧快照完全掩盖了口径切换。
    """
    now = time.time()
    stale = []
    missing = []
    for rel in _root.C14_WATCH:
        path = os.path.join(_root.PROJECT_DIR, rel)
        if not os.path.exists(path):
            missing.append(rel)
            continue
        age_days = (now - os.path.getmtime(path)) / 86400.0
        if age_days > _root.C14_FRESHNESS_DAYS:
            stale.append('%s(%d 天)' % (rel, int(age_days)))
    if missing:
        # D-45：CI 产物与 gitignored 快照在**非主工作树/CI** 上根本不存在（worktree 实测）。
        # 只在 skip_external 环境下把"缺件"降为 SKIP；停更（有件但过期）照旧判红，本机永远判红。
        if skip_external:
            return ('SKIP', '关键产物不在本环境（CI 产物/gitignored 快照）: %s'
                            % ', '.join(missing))
        return ('FAIL', '关键产物缺失: %s' % ', '.join(missing))
    if stale:
        return ('FAIL', '超过 %d 天未刷新: %s' % (_root.C14_FRESHNESS_DAYS, '; '.join(stale)))
    return ('PASS', '%d 项关键产物均 ≤%d 天' % (len(_root.C14_WATCH), _root.C14_FRESHNESS_DAYS))


def check_c15_dataflow_assumption(today=None):
    """C15(补充): G8 数据流假设锚定面校验（防「规则存在 ≠ 被执行」，R215）。

    锚定面 v1 = 焚诀 workspace 当日日志（.workbuddy/memory/YYYY-MM-DD.md）：
    - 日志含「数据流假设」锚点词 -> PASS（G8 陈述已留痕）
    - 日志无锚点但含代码修改痕迹（commit hash / rule_editor）-> FAIL
    - 日志无代码修改痕迹 -> PASS（G8 不触发）
    - 当日日志不存在 -> SKIP（无锚定面）
    补救：补记日志锚点词（代码修改类会话收尾必须留「数据流假设」字样）。
    """
    import datetime as _dt
    day = today or _dt.date.today().isoformat()
    log_path = os.path.join(_root.PROJECT_DIR, '.workbuddy', 'memory', day + '.md')
    if not os.path.exists(log_path):
        return ('SKIP', '当日日志不存在: %s.md（无锚定面）' % day)
    with open(log_path, encoding='utf-8') as f:
        text = f.read()
    if _root.C15_ANCHOR in text:
        return ('PASS', '当日日志含「%s」锚点（G8 已留痕）' % _root.C15_ANCHOR)
    if _root.C15_CODE_MARK_RE.search(text):
        return ('FAIL', '当日日志记录了代码修改但无「%s」锚点——G8 陈述未留痕，'
                        '补记锚点词或补做陈述后再提交' % _root.C15_ANCHOR)
    return ('PASS', '当日日志无代码修改标记，G8 不触发')


def check_c16_artifact_content_consistency(files=None, current_files=None,
                                           skip_external=False):
    """C16: STATUS 家族渲染的关键数字 == 真相源当场实测（补 C14 只验 mtime 的盲区）。

    对齐项：① skill 数（注册表实测）② skill_routing 行 skill 数 ③ behavior_core 版本/锚点/有效
    ④ 端点同步数 ⑤ 机器实测综合（壳与正文两处须一致）== 六线分之和（算术一致，容差 0.15）。
    判据自证：任一比对项在产物中「零命中」-> FAIL（不得把空输入当通过，R247）。
    files 参数仅供测试注入（默认真实产物）。
    """
    if files is None:
        files = [os.path.join(_root.PROJECT_DIR, r) for r in _root.C16_WATCH]
    if current_files is None:
        current_files = [os.path.join(_root.PROJECT_DIR, r.replace('/', os.sep))
                         for r in _root.C16_CURRENT_WATCH]
    issues = []
    texts = []
    for p in files:
        if not os.path.exists(p):
            issues.append('产物缺失: %s' % os.path.basename(p))
            continue
        with open(p, encoding='utf-8') as f:
            texts.append((os.path.basename(p), f.read()))
    if issues:
        return ('FAIL', '; '.join(issues))
    if not texts:
        return ('FAIL', 'C16 未拿到任何产物文本（输入为空，判据不可信）')

    # —— 真相源当场实测（无基准 = 不得判过）——
    try:
        uni = _root.load_registry_uni()  # P1-2: 单次加载缓存（原 5 处重复 json.load）
        true_skills = len(uni.get('skills', {}))
    except Exception as e:
        return ('FAIL', '注册表读取失败（无比对基准）: %s' % e)
    if true_skills <= 0:
        return ('FAIL', '注册表 skills 为空（比对基准无效）')
    true_ep = len(_root.ENDPOINTS)
    true_bc = (int(re.sub(r'\D', '', _root.BEHAVIOR_CORE_VERSION) or 0),
               _root.BEHAVIOR_CORE_ANCHORS, _root.BEHAVIOR_CORE_VALID)

    # ①+② skill 数：产物内须唯一，且 == 注册表实测
    got_skills = {}
    for fname, text in texts:
        for m in _root.C16_SKILLS_RE.finditer(text):
            got_skills.setdefault(int(m.group(1)), set()).add(fname + ':skills')
        for m in _root.C16_SKILLROUTING_RE.finditer(text):
            got_skills.setdefault(int(m.group(1)), set()).add(fname + ':skill_routing')
    if not got_skills:
        issues.append('产物未解析到 skill 数（零命中，输入不可信）')
    else:
        if len(got_skills) > 1:
            issues.append('产物内 skill 数自相矛盾: %s' % sorted(got_skills))
        for val in sorted(got_skills):
            if val != true_skills:
                issues.append('skill 数过期: 产物=%d vs 注册表实测=%d' % (val, true_skills))

    # ③ behavior_core 版本/锚点/有效数
    bc = set()
    for _fname, text in texts:
        for m in _root.C16_BC_RE.finditer(text):
            bc.add((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    if not bc:
        issues.append('产物未解析到 behavior_core 版本行（零命中）')
    else:
        if len(bc) > 1:
            issues.append('产物内 behavior_core 版本行自相矛盾: %s' % sorted(bc))
        for got in sorted(bc):
            if got != true_bc:
                issues.append('behavior_core 过期: 产物=V%d（%d锚点/%d有效） vs truth_constants=V%d（%d锚点/%d有效）'
                              % (got + true_bc))

    # ④ 端点同步数
    eps = set()
    for _fname, text in texts:
        for m in _root.C16_ENDPOINT_RE.finditer(text):
            eps.add(int(m.group(1)))
    if not eps:
        issues.append('产物未解析到「N端同步」行（零命中）')
    else:
        if len(eps) > 1:
            issues.append('产物内端数自相矛盾: %s' % sorted(eps))
        for v in sorted(eps):
            if v != true_ep:
                issues.append('端数过期: 产物=%d vs _root.ENDPOINTS=%d' % (v, true_ep))

    # ⑤ 机器实测综合：壳与正文一致，且**逐文件**各自 == 自身六线之和
    # 注：壳与正文都含「当前轮次」摘要行，故必须按文件分别求和——
    # 跨文件累加会把六线分算两遍（2026-09-22 隔离桩实测：167.2 vs 334.4 假失败）。
    totals = {}
    per_file_sums = {}
    for fname, text in texts:
        for m in _root.C16_TOTAL_RE.finditer(text):
            totals.setdefault(float(m.group(1)), set()).add(fname)
        vals = [float(m.group(1)) for m in _root.C16_LINE_RE.finditer(text)]
        if vals:
            per_file_sums[fname] = sum(vals)
    if not totals:
        issues.append('产物未解析到「机器实测综合: X/」行（零命中）')
    else:
        if len(totals) > 1:
            issues.append('壳/正文总分不一致: %s' % {k: sorted(v) for k, v in totals.items()})
        if not per_file_sums:
            issues.append('未解析到六线明细分（零命中，算术核对不可信）')
        else:
            tot = sorted(totals)[0]
            for fname, s in sorted(per_file_sums.items()):
                if abs(tot - s) > _root.C16_ARITH_TOL:
                    issues.append('总分与六线之和不等（%s）: %.1f vs %.1f' % (fname, tot, s))

    # ⑥ 记忆文档「当前口径」段一致性（建议 #9：R242 陈述一致性 + R241 历史留痕豁免）
    # 只扫带锚点的「当前口径」行；口径沿革/已完成条目段不扫（否则历史留痕会被误判为过期）。
    cur_rows = []
    for cp in current_files:
        if not os.path.exists(cp):
            continue
        try:
            with open(cp, encoding='utf-8') as f:
                for ln, line in enumerate(f, 1):
                    if _root.C16_CURRENT_ANCHOR in line:
                        cur_rows.append((os.path.basename(cp), ln, line))
        except Exception as e:
            issues.append('记忆文档读取失败 %s: %s' % (os.path.basename(cp), e))
    if not cur_rows:
        issues.append('未解析到「%s」行（零命中，判据面失效，R247）' % _root.C16_CURRENT_ANCHOR)
    else:
        _st = sorted(totals)[0] if totals else None
        for rel, ln, line in cur_rows:
            for m in _root.C16_CUR_SKILL_RE.finditer(line):
                v = int(m.group(1))
                if v != true_skills:
                    issues.append('%s:%d 当前口径 skill 数过期: %d vs 实测 %d'
                                  % (rel, ln, v, true_skills))
            if _st is None:
                continue
            for m in _root.C16_CUR_TOTAL_RE.finditer(line):
                v = float(m.group(1))
                if abs(v - _st) > _root.C16_ARITH_TOL:
                    issues.append('%s:%d 当前口径总分过期: %.1f vs 实测 %.1f'
                                  % (rel, ln, v, _st))

    # ⑦ 域数一致性（2026-09-22 补漏 S2）：C16 原只比 skill 数/端数/behavior_core/总分，
    # 域数从这漏出去 —— 「13 域 vs 14 域」正是因此长期潜伏（错值出自过期快照）。
    true_domains = None
    if os.path.isdir(_root.SKILL_CONTENT):
        try:
            _df = [f for f in os.listdir(_root.SKILL_CONTENT)
                   if f.endswith('.json') and f not in ('skill_ids.json', 'index_manifest.json')]
            true_domains = len({f[:-5] for f in _df})
        except Exception as e:
            issues.append('skill_content 域桶读取失败: %s' % e)
    if true_domains is None:
        issues.append('域数基准不可得（skill_content 不可达）→ 判据不可信，标 FAIL（R247）')
    else:
        got_domains = []
        for fname, text in texts:
            for m in _root.C16_DOMAIN_RE.finditer(text):
                got_domains.append((fname, int(m.group(1))))
        for rel, ln, line in cur_rows:
            for m in _root.C16_DOMAIN_RE.finditer(line):
                got_domains.append(('%s:%d' % (rel, ln), int(m.group(1))))
        if not got_domains:
            issues.append('产物/记忆文档未解析到「N 域」（零命中，输入不可信，R247）')
        else:
            for where, v in got_domains:
                if v != true_domains:
                    issues.append('%s 域数过期: %d vs 域桶实测 %d' % (where, v, true_domains))

    if issues and skip_external:
        # D-45：`memory/` 等 junction 在 worktree / 无外盘环境里不存在 ⇒ 判据面为空是**环境**
        # 问题而非内容漂移。只在 skip_external 且所有 issue 都属于"面不可达/零命中/读取失败"
        # 时降级；只要有一条真漂移（过期/不一致），上面已 return FAIL，不会被这段吞掉。
        if all(('零命中' in i or '不可达' in i or '读取失败' in i) for i in issues):
            return ('SKIP', '判据面在本环境不可达（junction/外盘缺失，非内容漂移）: %s'
                            % '; '.join(issues[:2]))

    if issues:
        return ('FAIL', '; '.join(issues))
    _sums = '/'.join('%.1f' % v for _f, v in sorted(per_file_sums.items()))
    return ('PASS', '产物内容与真相源一致（skill=%d / 端=%d / behavior_core=V%d（%d锚点/%d有效） / 总分=%.1f=六线之和[%s]）'
            % (true_skills, true_ep, true_bc[0], true_bc[1], true_bc[2], sorted(totals)[0], _sums))


def check_c29_index_reconciliation(index_text=None, scorecard=None, status_text=None,
                                   gate_max=None, truth=None):
    """C29: 根 index.md 与派生评分产物对账（2026-09-24 GitHub 对标轮，P0-14）。

    堵住两个实测盲区（均为「门禁看起来绿、产物其实在说谎」）：
      ① index.md 长期不在 C14/C16 看护面 —— 实测同文件内并存「头部八端 vs 表内端点数 6」
         「注册表 151 条 vs 实测 167」「C1~C24 vs 实注 28」「track_150…track_200 待 owner
         确认 vs active_track=track_200」四处自相矛盾（根因：generate_index 恒渲染 track_150）。
      ② reports/recheck_scorecard.json 只被 C14 按 **mtime** 看护，内容可与 STATUS 相差 7.4 分
         （实测 175.1 vs STATUS 182.5，均在 7 天窗口内 ⇒ C14 放行）—— R268 同族。
    判据（R247 零命中不得当通过）：每个比对面解析不到 = FAIL，不得静默 PASS。
    参数全部可注入（隔离桩用），默认真实产物面。
    """
    issues = []
    if index_text is None:
        p = os.path.join(_root.PROJECT_DIR, _root.C29_INDEX_REL)
        if not os.path.exists(p):
            return ('FAIL', 'index.md 缺失（生成器未跑: python eval/generate_index.py）')
        with open(p, encoding='utf-8') as f:
            index_text = f.read()
    if status_text is None:
        with open(os.path.join(_root.PROJECT_DIR, 'STATUS.md'), encoding='utf-8') as f:
            status_text = f.read()
    if truth is None:
        truth = {'endpoints': len(_root.ENDPOINTS),
                 'active_track': _root.SCORECARD_ACTIVE_TRACK,
                 'total': _root.SCORECARD_ACTIVE_TOTAL,
                 'pass_line': _root.SCORECARD_ACTIVE_PASS_LINE}
    if gate_max is None:
        gate_max = _root.derive_max_gate_id()
        if not gate_max:
            return ('FAIL', '无法从 verify 解析门禁编号（判据基准不可得，R247）')

    # ① 端点数：表内值 == 真相源，且与头部中文端数不得互相打脸
    row = _root.C29_EP_ROW_RE.search(index_text)
    if not row:
        issues.append('index.md 未解析到「| 端点数 | N」行（零命中）')
    elif row.group(1) != str(truth['endpoints']):
        issues.append('index.md 端点数过期: %s vs ENDPOINTS=%d' % (row.group(1), truth['endpoints']))
    _cn2n = {'三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8}
    head = _root.C29_EP_CN_HEAD_RE.search(index_text)
    if head is not None:
        head_n = _cn2n.get(head.group(1))
        if head_n is not None and head_n != truth['endpoints']:
            issues.append('index.md 头部端数标签与真相源矛盾: 头部=%s端 vs ENDPOINTS=%d'
                          % (head.group(1), truth['endpoints']))
    elif not _root.C29_EP_ROW_RE.search(index_text):
        issues.append('index.md 未解析到任何端数声明（零命中）')

    # ② 注册表条数 == 实测
    uni_ok = True
    try:
        true_skills = len(_root.load_registry_uni().get('skills', {}))
    except Exception as e:
        issues.append('注册表读取失败（无比对基准）: %s' % e)
        true_skills = None
    if true_skills is not None:
        reg = _root.C29_REGISTRY_RE.search(index_text)
        if not reg:
            issues.append('index.md 未解析到「注册表（N 条」行（零命中）')
        elif int(reg.group(1)) != true_skills:
            issues.append('index.md 注册表条数过期: %s vs 实测 %d' % (reg.group(1), true_skills))

    # ③ 门禁范围 == verify 实际注册的最大编号
    gates = {int(m.group(1)) for m in _root.C29_GATE_RE.finditer(index_text)}
    if not gates:
        issues.append('index.md 未解析到「C1~CN」门禁范围（零命中）')
    elif gates != {gate_max}:
        issues.append('index.md 门禁范围过期: %s vs verify 实注 C1~C%d'
                      % (sorted(gates), gate_max))

    # ④ 评分卡行：track 标签 + TOTAL + PASS 三项必须等于 active 口径
    trk = _root.C29_TRACK_RE.search(index_text)
    if not trk:
        issues.append('index.md 未解析到「| 评分卡 | track_N TOTAL=… PASS=…」行（零命中）')
    else:
        got = (trk.group(1), int(trk.group(2)), int(trk.group(3)))
        want = (truth['active_track'], int(truth['total']), int(truth['pass_line']))
        if got != want:
            issues.append('index.md 评分卡口径错配: %s vs active=%s' % (got, want))

    # ⑤ 派生评分产物 JSON.overall == STATUS 机器实测综合（补 C14 只验 mtime 的盲区）
    st = _root.C16_TOTAL_RE.search(status_text)
    if not st:
        issues.append('STATUS.md 未解析到「机器实测综合: X/」行（零命中，比对基准不可得）')
    else:
        status_total = float(st.group(1))
        if scorecard is None:
            sp = os.path.join(_root.PROJECT_DIR, _root.C29_SCORECARD_REL)
            if not os.path.exists(sp):
                issues.append('评分产物缺失: %s（跑 eval/score_track200.py --json 重生成）'
                              % _root.C29_SCORECARD_REL)
                scorecard = None
            else:
                try:
                    with open(sp, encoding='utf-8') as f:
                        scorecard = json.load(f)
                except Exception as e:
                    issues.append('评分产物解析失败: %s' % e)
                    scorecard = None
        if scorecard is not None:
            if 'overall' not in scorecard:
                issues.append('评分产物无 overall 字段（零命中）')
            elif abs(float(scorecard['overall']) - status_total) > _root.C29_SCORE_TOL:
                issues.append('评分产物与 STATUS 脱节: json.overall=%s vs STATUS=%s'
                              '（R268 同族：mtime 新鲜≠内容正确，重生成后再提交）'
                              % (scorecard['overall'], status_total))

    if issues:
        return ('FAIL', '; '.join(issues))
    return ('PASS', 'index.md 与评分产物对账一致（端点=%d / 注册表=%s / 门禁=C1~C%d / '
                    '评分卡=%s TOTAL=%s / 产物 overall==STATUS）'
            % (truth['endpoints'], true_skills, gate_max,
               truth['active_track'], truth['total']))


def check_c21_no_commit_authorization_rule(watched=None):
    """C21: 活文档不得含有"git 提交需授权/确认"类纪律（2026-09-23 用户立规：自动提交无需确认；防加回）。

    扫描面与 C5 同（活 workspace 根级壳 + AGENTS 分卷 + 项目绑定表），不扫 deliverables/archive/reports（历史留痕）。
    watched 参数仅供测试注入（默认真实扫描面），同 C16 的 files= 模式。
    """
    if watched is None:
        watched = [
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md'),
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md.part1.md'),
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md.part2.md'),
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md.part3.md'),
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md.part4.md'),
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md.part5.md'),
        os.path.join(_root.PROJECT_DIR, 'memory', 'AGENTS.md'),
        os.path.join(_root.PROJECT_DIR, 'memory', 'AGENTS.part1.md'),
        os.path.join(_root.PROJECT_DIR, 'memory', 'AGENTS.part2.md'),
    ]
    patterns = [
        re.compile(r'提交需(显式)?授权'),
        re.compile(r'授权后.{0,6}提交'),
        re.compile(r'确认后.{0,6}提交'),
        re.compile(r'提交前.{0,6}(确认|授权)'),
        re.compile(r'等待.{0,8}确认.{0,8}提交'),
        re.compile(r'禁止自动提交'),
        re.compile(r'不得自动提交'),
    ]
    historical_markers = ('现已', '已卸载', '已下线', '原为', '历史', '过时', '废除')
    issues = []
    scanned = 0
    for fpath in watched:
        if not os.path.exists(fpath):
            continue
        scanned += 1
        with open(fpath, encoding='utf-8', errors='ignore') as f:
            for line_no, line in enumerate(f, 1):
                if any(m in line for m in historical_markers):
                    continue  # 历史记录行（含"废除"声明行），跳过
                for pat in patterns:
                    if pat.search(line):
                        issues.append('%s:%d 命中提交授权表述' % (os.path.basename(fpath), line_no))
                        break
    if issues:
        return ('FAIL', '; '.join(issues))
    if scanned == 0:
        # R247：扫描面为空 = 判据不可信，不得静默 PASS（2026-09-23 补，与 C17/C18 同口径）
        return ('FAIL', '扫描面为空（0 个受检文件存在）→ 判据不可信，不得静默 PASS（R247）')
    return ('PASS', '活文档无提交授权纪律（扫描 %d 文件）' % scanned)

