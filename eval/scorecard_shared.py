#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scorecard_shared.py — 焚诀评分卡共享层（R208 O-4 拆分：scorecard.py 单体 963 行 → 编排层 + 本共享层 + 三线模块）

从原 scorecard.py 搬移:
  - 常量（truth_constants 转发 / 路径锚点 / JUNCTION_PATHS）
  - 纯函数（band_of / compute_verdict）
  - 计分基础设施（run / _script_target / 缺失哨兵判定 / dead_script_part /
    load_func_checks + _FUNC_CACHE）

约束: 本模块不 import scorecard 系其他模块（单向依赖，防循环）。
scorecard.py 从本模块 re-export 同名符号，保持 `scorecard.band_of` 等外部命名空间兼容
（test_scorecard_pure.py / score_track200.py 依赖）。
"""
import os
import sys
import json
import re
import subprocess

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
AUDIT_DIR = os.path.join(PROJECT_DIR, 'audit')
sys.path.insert(0, EVAL_DIR)
from truth_constants import (  # noqa: E402,F401
    SCORECARD_TOTAL as TOTAL,
    SCORECARD_PASS_LINE as PASS_LINE,
    SCORECARD_LINE_PASS as LINE_PASS,
    SCORECARD_DIM_PASS_RATE as DIM_PASS_RATE,
    get_junction_skills_paths,
    GLOBAL_MEMORY as GM,
    GLOBAL_SKILLS as SKILLS_DIR,
)
from failure_cost_metric import compute_failure_cost  # noqa: E402,F401  # P2 #10 失败成本度量（scorecard.py main 消费，经此转发保持单源）

SC = os.path.join(GM, 'skill_content')


def band_of(overall):
    """R163 分数带: ≥145 优秀 / 135-144 良好 / 120-134 合格 / <120 不达标"""
    if overall >= 145:
        return '优秀'
    if overall >= 135:
        return '良好'
    if overall >= 120:
        return '合格'
    return '不达标'


def compute_verdict(overall, line_pass, dim_pass, testset_ok, confirmed_n,
                    overdue_pending_n, escape_overdue_n=0, unavailable_dims=None):
    """R166-U1: 判定与确认缺陷解耦。
    PASS ⇔ 总分达标 ∧ 单线达标 ∧ 单维达标 ∧ 测试集版本化通过 ∧ confirmed=0 ∧ 超期 pending=0。
    R168: 逃生门超期（escape_hatch_deadline 已过仍未修复/未附决策文档）同样阻断 PASS。
    任何阻断项 → FAIL + blockers 清单（禁止"优秀/PASS"与确认缺陷共存）。
    返回 (pass_ok: bool, blockers: list[str])。
    """
    blockers = []
    if overall < PASS_LINE:
        blockers.append(f'总分未达达标线 {PASS_LINE}/{TOTAL}')
    if not line_pass:
        blockers.append('存在未达标主线')
    if not dim_pass:
        blockers.append('存在单维破限')
    if not testset_ok:
        blockers.append('测试集版本化 FAIL')
    if confirmed_n > 0:
        blockers.append(f'确认缺陷 {confirmed_n} 条未闭环')
    if overdue_pending_n > 0:
        blockers.append(f'超期 pending {overdue_pending_n} 条未闭环')
    if escape_overdue_n > 0:
        blockers.append(f'逃生门超期未裁决 {escape_overdue_n} 条')
    if unavailable_dims:
        blockers.append('存在 DATA UNAVAILABLE 维度: ' + ', '.join(unavailable_dims))
    return (not blockers), blockers


JUNCTION_PATHS = get_junction_skills_paths()  # 从 truth_constants 动态生成（四端）


def run(cmd, cwd=None, timeout=180, env=None):
    try:
        # 磁盘存在性自检：证据脚本缺失时返回可识别哨兵，下游可标记 unavailable，
        # 避免"脚本不存在 → 正则失配 → 静默 0 分"误判（如 negative_tag_audit.py 被删/移走）。
        target = _script_target(cmd)
        if target and not os.path.exists(target):
            return "__SCRIPT_MISSING__:" + os.path.basename(target)
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                           timeout=timeout, cwd=cwd or PROJECT_DIR, errors='replace',
                           env=env or None)
        return r.stdout + r.stderr
    except Exception as e:
        return 'RUN_FAILED: ' + str(e)  # fail-closed: 下游可检测此哨兵值


def _script_target(cmd):
    """从命令中提取待执行脚本文件路径（用于磁盘存在性自检）。

    仅返回确为文件路径的实参，避免把 -NoProfile / -m / -c 等标志或模块名误判为脚本。
    正确解析 `powershell -NoProfile -ExecutionPolicy Bypass -File <script.ps1>` 等带前置
    标志的形式——只取 -File 后的真路径；-Command 多为内联代码，无文件可检则返回 None。
    """
    if not cmd:
        return None
    if cmd[0] == sys.executable:
        for a in cmd[1:]:
            if a.startswith('-'):
                continue
            # 仅当形同文件路径（含分隔符或以脚本扩展名结尾）才视为可检脚本
            if os.sep in a or a.endswith(('.py', '.ps1', '.js')):
                return a
        return None
    if cmd[0] == 'powershell.exe':
        for i, a in enumerate(cmd):
            if a == '-File' and i + 1 < len(cmd):
                return cmd[i + 1]
        return None
    return None


def is_script_missing(out):
    return isinstance(out, str) and out.startswith("__SCRIPT_MISSING__:")


def missing_script_name(out):
    return out[len("__SCRIPT_MISSING__:"):]


def dead_script_part(max_score, name):
    """证据脚本缺失 → 标记 DATA UNAVAILABLE，隔离计分（不静默 0 分、不计入有效分）。"""
    return {'score': 0, 'max': max_score, 'unavailable': True,
            'detail': f"DATA UNAVAILABLE: 证据脚本 {name} 不存在于磁盘（已隔离，避免引用失效脚本）",
            'evidence': name,
            'evidence_fingerprint': f'dead-script:{name}'}


def mark_missing_if_dead(out, parts, mapping):
    """若 out 为缺失脚本哨兵，将 mapping 内全部 part 标记 unavailable。返回 True 表示已标记。"""
    if is_script_missing(out):
        name = missing_script_name(out)
        for key, mx in mapping.items():
            parts[key] = dead_script_part(mx, name)
        return True
    return False


_FUNC_CACHE = None


def load_func_checks():
    """R166-U2: 功能化检查结果（只跑一次，供 watcher/coverage/version/dataintegrity 共用）。"""
    global _FUNC_CACHE
    if _FUNC_CACHE is None:
        out = run([sys.executable, os.path.join(EVAL_DIR, 'functional_dim_checks.py'), '--json'],
                  timeout=900)
        if is_script_missing(out):
            # 证据脚本缺失 → 显式 unavailable（驱动 watcher/coverage/version/dataintegrity 全部隔离）
            _FUNC_CACHE = {'unavailable': True,
                           'reason': f'证据脚本 {missing_script_name(out)} 不存在于磁盘（已隔离）'}
            return _FUNC_CACHE  # R208 O-5 续修: 哨兵分支须短路返回，否则 reason（脚本名）被下方空输出分支覆盖
        m = re.search(r'(\{\s*"schema":\s*"fenjue-functional-dims-v1".*\})', out, re.S)
        try:
            _FUNC_CACHE = json.loads(m.group(1)) if m else {}
        except Exception as e:
            # R193: fail-closed——functional_dim_checks 输出不可解析时禁止静默 0 分
            _FUNC_CACHE = {'unavailable': True, 'reason': f'functional_dim_checks JSON 解析失败: {e}'}
        if not _FUNC_CACHE:
            _FUNC_CACHE = {'unavailable': True, 'reason': 'functional_dim_checks 无输出/不可用'}
    return _FUNC_CACHE