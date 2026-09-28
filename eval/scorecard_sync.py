#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scorecard_sync.py — 焚诀评分卡主线① 跨平台 skill 互通同步（50分，6维）

R208 O-4 拆分：从 scorecard.py 单体搬移 score_sync() 原样保留（行为等价）。
共享基础设施自 scorecard_shared 导入；scorecard.py（编排层）import 本模块并 re-export。
"""
import os
import sys
import json
import re

from scorecard_shared import (  # noqa: E402
    JUNCTION_PATHS, PROJECT_DIR, AUDIT_DIR, SKILLS_DIR, LINE_PASS,
    load_func_checks, run, is_script_missing, missing_script_name, dead_script_part,
)
from config import PLUGIN_SKILLS_DIR  # P1-6 收口: OC 插件目录单源引用


# ============ 主线① 跨平台 skill 互通同步（50分） ============
def score_sync() -> dict:
    """6维: junction/注册表完整/准确/Watcher/同步脚本/三方diff"""
    parts: dict[str, dict] = {}
    func = load_func_checks()

    # D1-1 Junction 连通性 (12分): 四端 junction 检查
    junction_ok = 0
    junction_detail = []
    for jp in JUNCTION_PATHS:
        try:
            if os.path.exists(jp):
                if os.path.islink(jp) or os.path.realpath(jp) != os.path.abspath(jp):
                    junction_ok += 1
                    junction_detail.append(f"{os.path.basename(os.path.dirname(jp))}->{os.path.realpath(jp)}")
                else:
                    junction_detail.append(f"{os.path.basename(os.path.dirname(jp))}->?")
        except Exception:
            # 单端 junction 探测异常仅记入 detail（该端计 0，不静默吞整维）
            junction_detail.append(f"{os.path.basename(os.path.dirname(jp))}->ERR")
    parts['junction'] = {'score': round(junction_ok / len(JUNCTION_PATHS) * 12, 1),
                         'max': 12,
                         'detail': f'{junction_ok}/{len(JUNCTION_PATHS)} 端通: {"; ".join(junction_detail)}',
                         'evidence': 'junction 路径检查 (realpath!=abspath 判定)',
                         'evidence_fingerprint': 'junction:四端realpath连通'}

    # D1-2 注册表完整性 (10分): triple_diff 三方一致
    td_out = run([sys.executable, os.path.join(AUDIT_DIR, 'triple_diff.py')])
    m = re.search(r'三方一致: (\d+)', td_out)
    triple_ok = int(m.group(1)) if m else 0
    # R148 修复: 基准动态化(旧写死 134 导致新技能数下分数溢出, 主线① 曾 50.7/50 超满分)
    import glob as _glob
    from config import SKILL_CONTENT as _SKILL_CONTENT
    _base = 0
    _base_errors = []
    for _f in _glob.glob(os.path.join(_SKILL_CONTENT, '*.json')):
        if os.path.basename(_f) == 'skill_ids.json':
            continue
        try:
            with open(_f, encoding='utf-8') as _fh:
                _base += len(json.load(_fh).get('skills', []))
        except Exception as e:
            _base_errors.append(f"{os.path.basename(_f)}: {e}")
    if is_script_missing(td_out):
        # 证据脚本 triple_diff.py 缺失 → 隔离计分，不静默 0 分
        parts['registry'] = dead_script_part(10, missing_script_name(td_out))
    elif _base == 0 or _base_errors:
        parts['registry'] = {'score': 0, 'max': 10,
                             'detail': 'DATA UNAVAILABLE: skill_content 域 JSON 为空/不可读（_base=0，禁止魔法数兜底）'
                                       + (f'；读取失败: {_base_errors[:3]}' if _base_errors else ''),
                             'evidence': 'audit/triple_diff.py',
                             'evidence_fingerprint': 'triple_diff:三方一致数',
                             'unavailable': True}
    else:
        # R219(2026-09-08) 任务2: 注册表硬编码计数漂移检查 —— 「增删技能是否需手动改数」可机检化。
        # 漂移(声明计数 != 实际数据长度)每处 -1，下限 0；无漂移不影响三方一致得分。
        _hc_out = run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    'hardcoded_count_check.py')])
        _hc_drift = 0
        _hc_detail = ''
        if is_script_missing(_hc_out):
            _hc_detail = '（硬编码检查脚本缺失，本子项跳过不计罚）'
        else:
            try:
                _hc = json.loads(_hc_out)
                _hc_drift = int(_hc.get('drift_count', 0))
                if _hc_drift:
                    _hc_detail = f'硬编码计数漂移 {_hc_drift} 处: ' + '; '.join(
                        f"{x['file']}.{x['field']} {x['declared']}!={x['actual']}"
                        for x in _hc.get('drift', [])[:3])
            except Exception as _e:
                _hc_drift = 0
                _hc_detail = f'（硬编码检查输出解析失败: {_e}，不计罚）'
        _reg_score = round(min(triple_ok, _base) / _base * 10, 1) - _hc_drift
        parts['registry'] = {'score': max(0.0, _reg_score),
                             'max': 10,
                             'detail': f'三方一致 {triple_ok}/{_base}' + (f'；{_hc_detail}' if _hc_detail else ''),
                             'evidence': 'audit/triple_diff.py + eval/hardcoded_count_check.py',
                             'evidence_fingerprint': 'triple_diff:三方一致数'}

    # D1-3 注册表准确性 (8分): install_state 计数 vs 磁盘
    try:
        with open(os.path.join(PROJECT_DIR, 'skill', 'registry', 'cross_platform_map.json'),
                  encoding='utf-8') as f:
            reg = json.load(f)
        reg_skills = reg.get('skills', {})
        # R-fix(2026-08-16): hm 是退役端(sync-skills-bridge.ps1 $RetiredEndpoints 含 qw/hm/mv/td),
        # 旧口径 reg_hm=109 vs 磁盘=151 恒差 42 → accuracy 恒 0 分, 属测量口径 bug 非真实缺陷。
        # 改用活跃主端 oc(OpenClaw 全量安装)计数, 磁盘口径对齐 build_registry(global_skills + OC 插件目录)。
        reg_oc = sum(1 for v in reg_skills.values()
                     if isinstance(v, dict) and v.get('install_state', {}).get('oc'))
        from config import SYSTEM_DIRS as _sys_skill_dirs  # 单一真相源（原硬拷贝收口）
        _oc_plugin = PLUGIN_SKILLS_DIR
        _disk_bases = [SKILLS_DIR]
        if os.path.isdir(_oc_plugin):
            _disk_bases.append(_oc_plugin)
        # set 并集去重（与 triple_diff 同口径）：同名技能在 global_skills 与 OC 插件并存时只计一次
        # ⚠️ 口径铁律(R198.6): 必须用 os.listdir 只扫顶层目录, 禁止改 os.walk 递归!
        #    实测全仓嵌套 SKILL.md 共 48 个(cloudbase__skillhub/references 28 + gstack/.agents/skills 20),
        #    这些是引用/依赖文件, 非独立 skill。os.walk 递归会把 162 误计为 210(+48),
        #    导致 accuracy 恒偏低。listdir 顶层扫描天然免疫嵌套。
        _disk_names: set[str] = set()
        for _base in _disk_bases:
            _disk_names.update(
                e for e in os.listdir(_base)
                if os.path.isdir(os.path.join(_base, e))
                and os.path.exists(os.path.join(_base, e, 'SKILL.md'))
                and e not in _sys_skill_dirs
            )
        disk_real = len(_disk_names)
        acc = max(0, 8 - abs(reg_oc - disk_real))  # 每差1扣1分(原 //10 档位差1~9都满分, OC指出宽容度过大)
        parts['accuracy'] = {'score': acc, 'max': 8,
                             'detail': f'注册表oc={reg_oc} vs 磁盘={disk_real}',
                             'evidence': 'cross_platform_map.json 计数对比',
                             'evidence_fingerprint': 'cross_platform_map:注册表ocvs磁盘计数'}
    except Exception:
        # R193: fail-closed——cross_platform_map 不可读时显式 unavailable，禁止静默 0 分
        parts['accuracy'] = {'score': 0, 'max': 8, 'detail': '注册表读取失败',
                             'evidence': 'cross_platform_map.json',
                             'evidence_fingerprint': 'cross_platform_map:注册表hmvs磁盘计数',
                             'unavailable': True}

    # D1-4 Watcher 自动化 (6分)
    w = func.get('watcher', {})
    if func.get('unavailable'):
        parts['watcher'] = {'score': 0, 'max': 6, 'unavailable': True,
                            'detail': f"DATA UNAVAILABLE: {func.get('reason', 'functional_dim_checks 不可用')}",
                            'evidence': 'watcher 三脚本真实触发',
                            'evidence_fingerprint': 'watcher:真实触发检测'}
    else:
        w_ok = int(w.get('ok_n', 0))
        parts['watcher'] = {'score': round(w_ok / 3 * 6, 1), 'max': 6,
                            'detail': w.get('detail', 'watcher 功能检查不可用'),
                            'evidence': 'watcher 三脚本真实触发 (detect 全量/auto-sync -ReportOnly/confirm-delete -WhatIf)',
                            'evidence_fingerprint': 'watcher:真实触发检测'}

    # D1-5 同步脚本质量 (6分): sync-skills-bridge 执行 0 ERROR
    # R-fix: powershell.exe 不在 PATH 时裸名 subprocess 抛 FileNotFoundError → RUN_FAILED
    # → ERROR 计数 0 → 假满分。用全路径兜底（与 functional_dim_checks.py PWSH 一致）。
    _pws = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),  # path-hygiene:ok  Windows 系统常量（非机器特定，且有裸名兜底）
                        'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    if not os.path.exists(_pws):
        _pws = 'powershell.exe'
    sync_out = run([_pws, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    os.path.join(PROJECT_DIR, 'skill', 'sync', 'sync-skills-bridge.ps1'),
                    '-ReportOnly'], timeout=300)
    if is_script_missing(sync_out):
        # 证据脚本缺失（powershell -File 目标不存在）→ 隔离计分
        parts['sync'] = dead_script_part(6, missing_script_name(sync_out))
    else:
        err = len(re.findall(r'\[ERROR\]', sync_out))
        parts['sync'] = {'score': 6 if err == 0 else max(0, 6 - err * 2), 'max': 6,
                         'detail': f'sync 脚本 ERROR={err}',
                         'evidence': 'sync-skills-bridge.ps1 -ReportOnly',
                         'evidence_fingerprint': 'sync-skills-bridge:ReportOnly ERROR数'}

    # D1-6 数据层自洽性 (8分): 三方一致数 / 基准真实 skill（动态，不含 OC-only）
    # R166-U2: 弃用 triple_diff 同一"三方一致数"（registry 已计），改内容级自洽（互斥证据）
    di = func.get('dataintegrity', {})
    di_health = float(di.get('health', 0))
    parts['dataintegrity'] = {'score': round(di_health / 100 * 8, 1), 'max': 8,
                              'detail': di.get('detail', '内容级自洽检查不可用'),
                              'evidence': 'eval/functional_dim_checks.py (内容级自洽)',
                              'evidence_fingerprint': 'functional_dim_checks:数据层内容自洽'}

    total = round(sum(float(p['score']) for p in parts.values()), 1)
    return {'line': '主线① 跨平台skill互通同步', 'total': total, 'pass': LINE_PASS,
            'parts': parts,
            'evidence': ['triple_diff.py', 'junction 检查', 'sync-skills-bridge.ps1']}