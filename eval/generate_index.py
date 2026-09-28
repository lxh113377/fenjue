#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_index.py — 生成根 index.md（R192 单一真相源派生）

AUTO-GENERATED | DO NOT EDIT | 跑 `python eval/generate_index.py`

数据源：
  - eval/truth_constants.json：端点/主线/4KB/评分阈值（唯一常量源）
  - STATUS.md：指标行（aggregate_status.py 生成）
  - skill/registry/unified-skills-index.json：注册表计数
  - 目录扫描：存在的目录（junction 状态固定表）
"""

import datetime
import json
import os
import re
import sys
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
INDEX_PATH = os.path.join(PROJECT_DIR, 'index.md')
STATUS_PATH = os.path.join(PROJECT_DIR, 'STATUS.md')
REGISTRY = os.path.join(PROJECT_DIR, 'skill', 'registry', 'unified-skills-index.json')

sys.path.insert(0, EVAL_DIR)
from truth_constants import (  # noqa: E402
    ENDPOINTS,
    MAINLINES,
    SCORECARD_ACTIVE_TOTAL,
    SCORECARD_ACTIVE_PASS_LINE,
    SCORECARD_ACTIVE_PASS_PCT,
    SCORECARD_ACTIVE_TRACK,
    FRAGMENT_MAX_BYTES,
    derive_max_gate_id,
)


def status_line(status_md: str, key: str) -> str:
    m = re.search(re.escape(key) + r':\s*([^\n]+)', status_md)
    return m.group(1).strip() if m else '（STATUS.md 未含该行，跑 aggregate_status.py 刷新）'


def main() -> int:
    reg = json.loads(Path(REGISTRY).read_text(encoding='utf-8'))
    skills_count = len(reg.get('skills', {}))
    status_md = ''
    if os.path.exists(STATUS_PATH):
        status_md = Path(STATUS_PATH).read_text(encoding='utf-8')

    endpoints = ' / '.join(ENDPOINTS)
    _CN_NUMS = {"4": "四", "5": "五", "6": "六", "7": "七", "8": "八"}
    ep_label = f'{_CN_NUMS.get(str(len(ENDPOINTS)), len(ENDPOINTS))}端'  # P0-1: 端数标签动态派生，禁手抄四端/六端
    mainlines = ' / '.join(f'{i+1}.{m["name"]}' for i, m in enumerate(MAINLINES))
    dir_rows = []
    dirs = [
        ('eval/', '路由/评估工具集', '活跃'),
        ('audit/', '审计脚本', '活跃'),
        ('skill/', ep_label + '技能注册+同步', '活跃'),
        ('skill_tree/', 'skill 路由索引/审计报告', '活跃'),
        ('reports/', '审计报告+优化记录', '持续产出'),
        ('archive/', '历史归档', '只读'),
        ('deliverables/', '工程保障报告', '只读'),
        ('memory', '→ <MEMORY_ROOT>\\memory', 'junction'),
        ('memory_content', '→ <MEMORY_ROOT>', 'junction'),
        ('prompts', '→ <MEMORY_ROOT>\\prompts', 'junction'),
    ]
    for name, desc, st in dirs:
        if os.path.exists(os.path.join(PROJECT_DIR, name)):
            dir_rows.append(f'| `{name}` | {desc} | {st} |')

    ts = datetime.datetime.now().isoformat(timespec='seconds')
    # R278：门禁编号范围**动态取**（原先写死 "C1-C9"，门禁已增到 C29 却未回扫 —— 同型漂移）。
    # 2026-09-24 对标轮：解析逻辑上收到 truth_constants.derive_max_gate_id（唯一派生点），
    # 与 aggregate_status 共用，消除两份内联正则各自腐烂。
    _gmax = derive_max_gate_id()
    GATE_RANGE = 'C1~C%d' % _gmax if _gmax else 'C1~C?'
    content = f'''# 焚诀 — 项目总索引

> AUTO-GENERATED: {ts} | DO NOT EDIT — 跑 `python eval/generate_index.py`
> 多agent统一记忆+技能路由系统 | {ep_label}({endpoints}) | 六大主线
>
> 权威源: <MEMORY_ROOT>\\ | 本项目是其治理工作区
> 常量源: eval/truth_constants.json（变更须留痕经门禁自证，不设人工签批门）；门禁: eval/verify_truth_consistency.py {GATE_RANGE}

## 拓扑事实（truth_constants 派生，禁止手抄）

| 事实 | 值 |
|------|-----|
| 端点数 | {len(ENDPOINTS)}（{endpoints}） |
| 主线数 | {len(MAINLINES)}（{mainlines}） |
| 4KB 分卷 | >{FRAGMENT_MAX_BYTES}B 必拆，0 孤儿 part |
| 评分卡 | {SCORECARD_ACTIVE_TRACK} TOTAL={SCORECARD_ACTIVE_TOTAL} PASS={SCORECARD_ACTIVE_PASS_LINE}（{int(SCORECARD_ACTIVE_PASS_PCT * 100)}%） |

## 目录结构

| 目录 | 用途 | 状态 |
|------|------|------|
{chr(10).join(dir_rows)}

## 核心指标（来自 STATUS.md，跑 `python eval/aggregate_status.py` 刷新）

| 指标 | 值 |
|------|-----|
| 当前轮次 | {status_line(status_md, '当前轮次')} |
| 机器实测综合 | {status_line(status_md, '机器实测综合')} |
| 归一化达成率 | {status_line(status_md, '归一化达成率')} |
| 判定(Codex) | {status_line(status_md, '判定(Codex)')} |

## 关键文件

- `eval/truth_constants.json` — 唯一常量源（端点/主线/评分阈值）
- `eval/verify_truth_consistency.py` — {GATE_RANGE} 真相源门禁（pre-commit + 周维护 Step 0；接入点自检见 `eval/check_gate_wiring.py`）
- `eval/index_integrity.py` — TF-IDF pickle 完整性校验
- `eval/unified_router.py` — 焚诀路由核心（直连→域→Tag→BGE→Ensemble→Memory boost→置信分层）
- `STATUS.md` — AUTO-GENERATED 指标壳（`python eval/aggregate_status.py`）
- `AGENTS.md` — 项目上下文（handoff 生成 + 手工分卷）
- `skill/registry/unified-skills-index.json` — 注册表（{skills_count} 条，build_registry.py 生成）

## 维护节奏

每周维护（见 `skill/checklist/weekly_maintenance.md`）:
1. `python eval/verify_truth_consistency.py` + `python eval/index_integrity.py --check`
2. sync {ep_label} + 路由回归 + scorecard
3. `python eval/aggregate_status.py` 刷新 STATUS
4. `python eval/generate_index.py` 刷新本文件 + 更新 AGENTS.md

> 评估冻结期（R170, 2026-08-04~09-04）: 评分卡不加新维度；平台分层权威 `skill/registry/platform_tiers.json`。
'''
    # external-write-ok: generate_index 写全局 index.md（build_indexes 单一生成器管控，写前守恒校验）
    Path(INDEX_PATH).write_text(content, encoding='utf-8')  # external-write-ok: 同上
    print(f'index.md 已生成: {INDEX_PATH} ({len(content)} chars)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
