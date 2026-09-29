# -*- coding: utf-8 -*-
"""verify_checks.governance_layer — 检查函数族（P1-16 拆包，2026-09-23）。

状态/助手经 `_root.<name>` 晚绑定（ctx 单例 = verify_truth_consistency），
monkeypatch(vtc, <state>/<check>) 契约不变。
"""
import glob
import json
import os
import re
import subprocess
import sys

import verify_truth_consistency as _root  # noqa: E402  # ctx 单例


def check_c17_consumer_consistency(skip_external=False):
    """R276：同一实体名的排除清单必须在所有消费方处一致。

    D-48（轮七）：16 个消费方里多数住在 GM `scripts/`（Windows 字面量路径），CI 上此前
    **没有** SKIP 分支 ⇒ 恒以「消费方文件不存在」判红，把「这台机器没有 GM 盘」报成「清单不一致」。
    """
    _root._ensure_eval_path()
    try:
        import consistency_consumers as cc
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'门禁脚本不可用（禁止以 SKIP 绕过）: {e}')
    if not _root.external_root_reachable(cc.GM_SCRIPTS):
        if skip_external:
            return ('SKIP', '消费方所在盘不可达（CI 环境，C17 保持本地；C20 同口径）: %s'
                    % cc.GM_SCRIPTS)
        return ('FAIL', 'W0 消费方根不存在: %s（判据面无从核验）' % cc.GM_SCRIPTS)
    try:
        failures, _notes = cc.check_entities()
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'check_entities 异常: {e}')
    n_c = sum(len(s['consumers']) for s in cc.ENTITIES.values())
    if not cc.ENTITIES or n_c == 0:
        # R247：判据面为空时不得静默 PASS（ENTITIES 被清空 → 0 处不一致 ≠ 通过）
        return ('FAIL', f'判据面为空（{len(cc.ENTITIES)} 实体 / {n_c} 消费方）'
                        f'—— 无处可比不得判过（R247）')
    if failures:
        return ('FAIL', f'{len(failures)} 处不一致: ' + ' | '.join(failures[:3]))
    return ('PASS', f'{len(cc.ENTITIES)} 实体 / {n_c} 消费方核验全部一致')


def check_c18_cross_writer_contract(skip_external=False):
    """R277：多写入方产物（域 JSON）各写入方的写法必须符合统一契约。

    D-48（轮七）：写入方扫描面 `SCAN_DIRS` 含 GM `scripts/`，CI 上取不到任何写入方，
    原样判「未发现任何写入方（判据面失效）」⇒ 恒红。外盘不可达与判据面被清空是两件事，
    前者降级并点名，后者照旧判红（R247 反逃生门）。
    """
    _root._ensure_eval_path()
    try:
        import cross_writer_idempotence as cwi
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'门禁脚本不可用（禁止以 SKIP 绕过）: {e}')
    if not _root.external_root_reachable(cwi.GM_SCRIPTS):
        if skip_external:
            return ('SKIP', '写入方扫描面不可达（CI 环境，C18 保持本地；C20 同口径）: %s'
                    % cwi.GM_SCRIPTS)
        return ('FAIL', 'W0 写入方根不存在: %s（判据面无从核验）' % cwi.GM_SCRIPTS)
    try:
        failures, _notes = cwi.check_static()
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'check_static 异常: {e}')
    if not cwi.CONTRACTS:
        # R247：契约表为空 = 判据面失效，不得静默 PASS
        return ('FAIL', 'CONTRACTS 为空（判据面失效，R247）—— 无处可比不得判过')
    if failures:
        return ('FAIL', f'{len(failures)} 项不合契约: ' + ' | '.join(failures[:3]))
    return ('PASS', f'{len(cwi.CONTRACTS)} 契约产物 / {len(cwi.KNOWN_WRITERS)} 登记写入方均合规')


def check_c19_gate_wiring(skip_external=False):
    """R278：门禁接入点自检 —— 头部声明的每条接入点必须真实存在（防「声明 4 条实际 2 条」）。

    ⚠️ 本项**不实跑 hook**（hook 内含 verify 调用 ⇒ 会 verify→C19→hook→verify 无限递归），
    只做静态核验：存在性 + 内容断言（含 verify 调用 / exit 1 拦截语义）+ 副本存在。

    D-48（轮七）：W1/W2/W3 是**本机钩子接入面**（`.git/hooks` 不被 git 跟踪，干净签出上必然没有），
    CI 上把「这台机器从没装过钩子」报成「门禁未接入」= 恒红。现只在
    ①`--skip-external` ②运行在 CI（`CI` 环境变量）③**全部**失效项都属 W1~W3 三条本地接入面
    三个条件同时成立时降级为 SKIP 并逐条点名；只要掺着一条非接入面红项照旧判红（R247 反逃生门）。
    """
    _root._ensure_eval_path()
    try:
        import check_gate_wiring as cgw
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'门禁脚本不可用（禁止以 SKIP 绕过）: {e}')
    try:
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        reasons = []
        with redirect_stdout(buf):
            rc = _root._cgw_run(cgw, reasons)
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'check_gate_wiring 执行异常: {e}')
    if rc != 0:
        # 2026-09-23 修：原版取 stdout 里「- W」开头的行，但 _root._cgw_run 不打印任何东西
        # ⇒ bad 恒为空 ⇒ FAIL 详情恒为「见 stderr」（而 stderr 也没内容）。闸响了却指不出原因。
        local_face = [r for r in reasons if re.match(r'^W[123]\b', r)]
        if (skip_external and os.environ.get('CI')
                and reasons and len(local_face) == len(reasons)):
            return ('SKIP', 'CI 干净签出无本地钩子（W1~W3 属本机接入面，C19 保持本地拦截）: '
                            + ' | '.join(local_face[:3]))
        return ('FAIL', f'{len(reasons) or 1} 项接入点失效: '
                        + (' | '.join(reasons[:3]) or '（无明细）'))
    face = cgw.detect_face()
    if face == "subset":
        return ('PASS', '子集面接入点落地（版本化副本 + CI 门禁链 + pre-commit 声明；GM 两项 SKIP 未计入）')
    return ('PASS', 'W1~W7 接入点全部落地（两仓 hook + 副本 + CI + 周维护 + 声明覆盖）')


def check_c33_memory_index_routing(skip_external=False, text=None, rows=None):
    """C33（2026-09-24 对标轮四 7-D）：GM 记忆路由表健康 —— 恢复断掉的按需加载链。

    病灶（R3 D-11，本轮实测仍在）：八端启动契约都写「按 `meta/memory_index.md` 路由精准加载」，
    而该文件自 2026-09-21 R9 事故后是 9 行重建壳、内含 4 处「（待重建）」⇒ 按需加载链断了 3 天，
    直接压低主线②（统一记忆+路由）与主线⑤（注意力税）。表已改为生成物
    （焚诀 eval/build_memory_index.py），本闸判：① 无「待重建」残留；② 体积 ≤4096 B（R161）；
    ③ 表内声明的每个路径实测存在且非空（R240 机器化）；④ GM 一级目录全覆盖（新增目录必须
    归类为知识或排除，否则红）；⑤ 表内不指向不存在目录。text= 仅供桩注入夹具。
    """
    _root._ensure_eval_path()
    try:
        import build_memory_index as bmi
    except Exception as e:  # noqa: BLE001
        return ('FAIL', 'C33 生成器模块不可达: %s' % e)
    if not _root.external_root_reachable(bmi.ROOT):
        # rows= 注入时是纯夹具面（桩），根目录不在判据链上，不因外盘缺失而 SKIP
        # D-48（轮七）：判据从 `isdir` 换成「本平台语义下的绝对路径 + 是目录」——CI（POSIX）上
        # Windows 字面量是相对路径，工作树里的同名幽灵目录不得被认作「GM 可达」。
        if rows is not None:
            pass
        elif skip_external:
            return ('SKIP', 'GM 根不可达（CI 环境，C33 保持本地；C20/C25 同口径）: %s' % bmi.ROOT)
        else:
            return ('FAIL', 'W0 GM 根不存在: %s（判据面无从核验）' % bmi.ROOT)
    if text is None:
        if not os.path.exists(bmi.OUT):
            return ('FAIL', 'W0 路由表不存在: %s（跑 python eval/build_memory_index.py --apply）' % bmi.OUT)
        text = bmi.load_text(bmi.OUT)
    return bmi.check_text(text, rows=rows)


def check_c32_empty_baseline_ledger(skip_external=False, ledger_path=None, state=None,
                                    entries=None, today=None):
    """C32（2026-09-24 对标轮四 7-C / 6-B）：空基线「已初始化」台账 —— 杀 vacuous pass 整族。

    病灶（R3 D-10 实测，本轮复核三处仍在）：`style_ratchet_baseline={}` /
    `llm_failure_cases=[]` / `blindset_rotation active_version=0,history=[]` 都以"空"过关；
    而"扫过且干净"与"根本没扫/机制从没跑"在文件里长得一模一样。判据：空面必须持有登记，
    含 scanned_units>0 且 **不超过当前实扫面**（只查下界会放过虚报）、surface 口径、
    at ≤90 天（陈旧初始化不得长期吃老本）、计数器型另须 next_due；新增空面未登记即红。
    单一实现源 = eval/empty_baseline_ledger.judge（--init 采集器与门禁同一套判据）。
    state/entries/ledger_path/today 仅供桩与测试注入夹具。
    CI 口径（D-41）：`skip_external=True` 时**基线文件与数据源同时缺失**的面按不可达跳过
    （如 gitignored 的 llm_failure_cases.json/llm_decisions.jsonl）；源在而登记缺失照旧判红。
    """
    _root._ensure_eval_path()
    try:
        import empty_baseline_ledger as ebl
    except Exception as e:  # noqa: BLE001
        return ('FAIL', 'C32 台账模块不可达: %s' % e)
    path = ledger_path or ebl.LEDGER_PATH
    if state is None or entries is None:
        if state is None:
            state = ebl.collect_state()
        if entries is None:
            if not os.path.exists(path):
                return ('FAIL', 'W0 台账文件不存在: %s（跑 python eval/empty_baseline_ledger.py '
                                '--init 采集，禁止手写空台账求绿）' % path)
            entries = ebl.load_ledger(path)
    return ebl.judge(state, entries, today=today, skip_external=skip_external)


def check_c31_inject_ledger(skip_external=False, ledger_path=None, baseline=None,
                            hard_cap=None, measured_total=None):
    """C31（2026-09-24 对标轮四 7-E）：L1 注入预算**归因台账** —— 治「基线可被裸改」与「外仓增长不可归因」。

    实测根因（D-22/D-28）：注入面消费端在焚诀仓，**增长源在 global_skills 仓**，而该仓
    `.git/hooks` 只有 post-commit 无 pre-commit ⇒ 一次技能版本发布（V10.68.0/V10.69.0）
    在提交当时零校验，本地一字未动却从 28/28 变 29 PASS/1 FAIL 且无从归因。
    判据：① 台账非空（空=未初始化即红，R247）；② `truth_constants.baseline_bytes` 必须等于
    台账末条 applied 的 baseline_after（基线只能**经由台账**移动，禁裸改）；③ 每条 applied
    必须署名（actor_repo/actor_commit）+ 因由 ≥10 字；④ 硬顶不得高于立规天花板 65536；
    ⑤ pending 条目与 <5% 余量在明细中显式告警（阻塞可见，不被绿吞掉）。
    单一实现源 = eval/inject_ledger.validate（记账 CLI 与门禁同一套判据，禁双实现漂移）。
    ledger_path/baseline/hard_cap/measured_total 仅供桩与测试注入夹具。
    """
    _root._ensure_eval_path()
    try:
        import inject_ledger as il
    except Exception as e:  # noqa: BLE001
        return ('FAIL', 'C31 台账模块不可达: %s' % e)
    path = ledger_path or il.LEDGER_PATH
    if baseline is None:
        baseline = _root.INJECT_BUDGET_BASELINE
    if hard_cap is None:
        hard_cap = _root.INJECT_BUDGET_HARD_CAP
    if measured_total is None:
        total, missing = 0, []
        for f in _root.INJECT_BUDGET_FILES:
            entry = f['path']
            # 相对路径必须锚在治理仓根：判据面不得随 cwd 漂移（实测在 GM 仓提交时
            # 曾因 os.path.exists('AGENTS.md') 落在别处而假红「文件缺失」，拦住无辜提交）
            resolved = entry if os.path.isabs(entry) else os.path.join(_root.PROJECT_DIR, entry)
            if os.path.exists(resolved):
                total += os.path.getsize(resolved)
            else:
                missing.append(f['id'])
        if missing:
            if skip_external:
                return ('SKIP', '注入盘不可达（CI 环境，C31 保持本地；C20/C25 同口径）: '
                                + ', '.join(missing))
            return ('FAIL', 'W0 注入清单文件缺失: ' + ', '.join(missing))
        measured_total = total
    return il.validate(il.load(path), baseline=baseline, hard_cap=hard_cap,
                       ledger_path=path, measured_total=measured_total)


def check_c25_inject_budget(skip_external=False, files=None, baseline=None,
                            hard_cap=None, sizes=None):
    """C25（2026-09-24 P1E-2）：L1 注入硬预算棘轮 —— P0 强制注入区字节和只许降不许升。

    对标：OpenClaw MEMORY.md 硬预算 20k/文件 60k 总量；Anthropic 25k 硬截断。
    棘轮语义：
      W1 配置缺失 / 文件清单为空 / 阈值倒挂 -> FAIL（R247：无处可比不得判过）；
      W2 清单内文件缺失 -> FAIL（数据面缺失不得静默过）；
        CI 例外：skip_external=True 且仅 D: 注入盘不可达 -> SKIP（C20 同口径）；
      W3 总字节 > hard_cap -> FAIL（绝对上限，防基线被失控放宽）；
      W4 总字节 > baseline -> FAIL（棘轮防回弹 -> 精简或拆 references 侧车，
        确属必要增长须经 eval/inject_ledger.py --decision applied 留痕后再更新 baseline_bytes）。
    files/baseline/hard_cap/sizes 仅供测试注入（同 C24 的 fallback= 模式），
    默认读 truth_constants.inject_budget；sizes 形如 {id: 字节} 覆盖实测。
    """
    if files is None:
        files = _root.INJECT_BUDGET_FILES
    if baseline is None:
        baseline = _root.INJECT_BUDGET_BASELINE
    if hard_cap is None:
        hard_cap = _root.INJECT_BUDGET_HARD_CAP
    if not files:
        return ('FAIL', 'W1 注入预算文件清单为空（R247：判据面失效）')
    if not baseline or not hard_cap:
        return ('FAIL', 'W1 预算阈值缺失（baseline=%r hard_cap=%r）' % (baseline, hard_cap))
    if hard_cap < baseline:
        return ('FAIL', 'W1 硬顶 %d < 基线 %d（阈值倒挂，先修 inject_budget）'
                % (hard_cap, baseline))
    total, missing, external_missing = 0, [], []
    for f in files:
        fid, path = f['id'], f['path']
        if sizes is not None and fid in sizes:
            total += sizes[fid]
            continue
        p = path if os.path.isabs(path) else os.path.join(_root.PROJECT_DIR, path)
        if not os.path.exists(p):
            # D-48（轮七）：原判据只把「字面以 D: 开头」的路数到外盘桶，CI 上 `shell_zc`
            # （注入文件在用户目录下，非 D: 前缀）落进本仓桶 ⇒ 报成「清单内文件缺失」而绕过了
            # 注入盘降级。正确口径 = 盘符/UNC 字面量或解析后落在仓外（见 _root.path_outside_project）。
            (external_missing if _root.path_outside_project(path) else missing).append(fid)
            continue
        total += os.path.getsize(p)
    if missing:
        return ('FAIL', 'W2 清单内文件缺失: ' + ', '.join(missing))
    if external_missing:
        if skip_external:
            return ('SKIP', '注入盘不可达（CI 环境，C25 保持本地；C20 同口径）')
        return ('FAIL', 'W2 注入盘文件缺失: ' + ', '.join(external_missing))
    if total > hard_cap:
        return ('FAIL', 'W3 总字节 %d > 硬顶 %d（+%d）→ 立即瘦身，且禁止再上调基线'
                % (total, hard_cap, total - hard_cap))
    if total > baseline:
        return ('FAIL', 'W4 总字节 %d > 棘轮基线 %d（+%d）→ 精简或拆 references 侧车；'
                        '确属必要增长经 eval/inject_ledger.py --decision applied 留痕后移动'
                        '（棘轮防回弹，P1E-2）'
                % (total, baseline, total - baseline))
    return ('PASS', '注入区 %d B / 基线 %d B（余量 %d）/ 硬顶 %d B，%d 文件棘轮合规'
            % (total, baseline, baseline - total, hard_cap, len(files)))


def check_c24_direct_map_consistency(fallback=None, json_entries=None):
    """C24: direct_layer fallback 与 direct_map.json 双写一致（P2-8/6，2026-09-23）。

    fallback / json_entries 仅供测试注入（同 C23 的 decls= 模式），默认读真实双面。
    """
    if fallback is None:
        try:
            from save_direct_map import extract_fallback
            # P1-8（2026-09-23）：fallback 字面量已外置 direct_map_fallback_data.py，
            # 提取点跟随数据真身；旧布局（字面量仍在 direct_layer.py）保留兼容回退
            fb_path = os.path.join(_root.EVAL_DIR, 'direct_map_fallback_data.py')
            if not os.path.exists(fb_path):
                fb_path = os.path.join(_root.EVAL_DIR, 'direct_layer.py')
            fallback = extract_fallback(fb_path)
        except SystemExit as e:
            return ('FAIL', 'W1 fallback 提取失败: %s' % e)
        except Exception as e:
            return ('FAIL', 'W1 fallback 读取异常: %s' % e)
    if json_entries is None:
        try:
            with open(os.path.join(_root.EVAL_DIR, 'direct_map.json'), encoding='utf-8') as f:
                json_entries = json.load(f)
        except Exception as e:
            return ('FAIL', 'W2 direct_map.json 读取失败: %s' % e)
    if not fallback:
        return ('FAIL', 'W1 fallback 为空（R247：空面不得静默 PASS）')
    if not json_entries:
        return ('FAIL', 'W2 direct_map.json 为空（R247：空面不得静默 PASS）')
    if len(fallback) != len(json_entries):
        return ('FAIL', 'W1 条数不一致（fallback=%d json=%d）→ 跑 save_direct_map.py --force 同步'
                % (len(fallback), len(json_entries)))
    fb = sorted((p, s) for p, s in fallback)
    js = sorted((p, s) for p, s in (tuple(e) for e in json_entries))
    if fb != js:
        diff = ([p for p, s in fb if (p, s) not in js][:2]
                + ['json多余:%s' % p for p, s in js if (p, s) not in fb][:2])
        return ('FAIL', 'W2 内容不一致（差异=%s）→ 跑 save_direct_map.py --force 同步' % diff[:2])
    return ('PASS', 'direct 双写一致（fallback=json=%d 条）' % len(fb))



def check_c26_memory_recall_testset(skip_external=False, testset_path=None, root=None):
    """C26（2026-09-24 P1E-1）：记忆召回评测集静态健康 —— 存在性/结构/期望目标零死链/基线已登记。

    判据单一实现源：复用 memory_recall_eval.validate_testset（跑分器与门禁同一套判据，
    禁双实现漂移，呼应 P1-10）。评测「跑分」本身归周维护与 STATUS loader，verify 只做
    静态健康（防语料改名/拆卷/条目删除把基准悄悄打烂——R240 文档写了≠磁盘有同族）。
    testset_path/root 仅供桩/测试注入夹具；默认读 eval/memory_recall_testset.json 与
    GLOBAL_MEMORY。CI 例外：skip_external=True 且仅记忆根不可达 → SKIP（C20/C25 同口径）。
    """
    _root._ensure_eval_path()
    try:
        import memory_recall_eval as mre
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'评测脚本不可用（禁止以 SKIP 绕过）: {e}')
    ts_path = (testset_path if testset_path is not None
               else os.path.join(_root.EVAL_DIR, 'memory_recall_testset.json'))
    try:
        testset = mre.load_json(ts_path)
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'W1 评测集读取失败: {e}')
    if testset.get('schema') != 'fenjue-memory-recall-testset-v1':
        return ('FAIL', f"W1 评测集 schema 不识别: {testset.get('schema')!r}")
    mem_root = root if root is not None else _root.GLOBAL_MEMORY
    if not _root.external_root_reachable(mem_root):
        if skip_external:
            return ('SKIP', f'记忆根不可达（CI 环境，C26 保持本地）: {mem_root}')
        return ('FAIL', f'W1 记忆根不存在: {mem_root}（判据面无从核验）')
    errors, stats = mre.validate_testset(testset, mem_root)
    if errors:
        return ('FAIL', '；'.join(errors[:4]))
    return ('PASS', '召回评测集健康: %d 条用例 / 语料 %d 条目 / 期望目标零死链 / 基线已登记'
            % (stats['items'], stats['corpus_entries']))


def check_c27_skill_content_security(skip_external=False, root=None):
    """C27（2026-09-24 P2E-1）：技能内容安全扫描 —— 注入/密钥外传族零容忍。

    判据单一实现源：复用 skill_security_scan.run_scan（发布前检查与常态门禁同一套，
    禁双实现漂移）。dangerous 族为可见告警不阻断（2026-09-24 用户立规：禁以
    「治理文档引用违禁词=规则本体」作豁免——改以分流处置，全仓无豁免表）。
    root 仅供桩/测试注入夹具；CI 例外：skip_external=True 且仅技能盘不可达 → SKIP
    （C20/C25/C26 同口径）。
    """
    _root._ensure_eval_path()
    try:
        import skill_security_scan as sss
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'扫描器不可用（禁止以 SKIP 绕过）: {e}')
    sk_root = root if root is not None else sss.config.GLOBAL_SKILLS
    if not _root.external_root_reachable(sk_root):
        if skip_external:
            return ('SKIP', f'技能盘不可达（CI 环境，C27 保持本地）: {sk_root}')
        return ('FAIL', f'W1 技能盘不存在: {sk_root}（判据面无从核验）')
    res = sss.run_scan(root=sk_root)
    if not res['files']:
        return ('FAIL', 'W1 扫描面为 0 文件（R247：空面不得静默 PASS）')
    if res['violations']:
        det = '; '.join('%s/%s:L%d %s' % (v['skill'], v['file'], v['line'], v['pattern_id'])
                        for v in res['violations'][:3])
        return ('FAIL', '注入/外传零容忍：%d 条违规 [%s]' % (len(res['violations']), det))
    return ('PASS', '内容安全：文件 %d 违规 0（dangerous 告警 %d 条不阻断，发布前过目）'
            % (res['files'], len(res['warnings'])))


def check_c28_skill_publish_compliance(skip_external=False, root=None):
    """C28（2026-09-24 P2E-2）：技能发布合规 —— frontmatter 必填/description≤1024/字段白名单。

    判据单一实现源：复用 skill_publish_compliance.run_compliance。
    name 与目录名错位 = W1 告警不阻断（存量 5 例 notion-*/__skillhub 形态）。
    root 仅供桩/测试注入；CI 技能盘不可达 → SKIP（同 C27）。
    """
    _root._ensure_eval_path()
    try:
        import skill_publish_compliance as spc
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'校验器不可用（禁止以 SKIP 绕过）: {e}')
    sk_root = root if root is not None else spc.config.GLOBAL_SKILLS
    if not _root.external_root_reachable(sk_root):
        if skip_external:
            return ('SKIP', f'技能盘不可达（CI 环境，C28 保持本地）: {sk_root}')
        return ('FAIL', f'W1 技能盘不存在: {sk_root}（判据面无从核验）')
    res = spc.run_compliance(root=sk_root)
    if not res['skills']:
        return ('FAIL', 'W1 扫描面为 0 技能（R247：空面不得静默 PASS）')
    if res['violations']:
        det = '; '.join('%s[%s] %s' % (v['skill'], v['check'], v['detail'])
                        for v in res['violations'][:3])
        return ('FAIL', '发布合规 %d 条违规: %s' % (len(res['violations']), det))
    return ('PASS', '发布合规：技能 %d 违规 0（name 错位告警 %d 条不阻断）'
            % (res['skills'], len(res['warnings'])))
