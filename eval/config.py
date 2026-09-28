#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config.py — 焚诀路径配置化（R192 阶段2；P1-6 收口 2026-09-02）。

环境变量优先；根常量唯一定义点 = truth_constants.GLOBAL_*_ROOT，本模块仅
re-export（保持旧引用名 SKILLS_DIR 等兼容）。新增代码禁止手写盘符字面量，
新增由 CI path-hygiene ratchet lint 拦截（eval/path_hygiene.py）。
"""

import os

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)

try:
    from truth_constants import GLOBAL_SKILLS_ROOT, GLOBAL_MEMORY_ROOT
    GLOBAL_SKILLS = os.environ.get("FENJUE_SKILLS_DIR", GLOBAL_SKILLS_ROOT)
    GLOBAL_MEMORY = os.environ.get("FENJUE_GLOBAL_MEMORY", GLOBAL_MEMORY_ROOT)
except ImportError:  # 兜底：truth_constants 不可达时保持旧行为（不放大失败面）
    GLOBAL_SKILLS = os.environ.get("FENJUE_SKILLS_DIR", r"<SKILLS_ROOT>")
    GLOBAL_MEMORY = os.environ.get("FENJUE_GLOBAL_MEMORY", r"<MEMORY_ROOT>")

SKILLS_DIR = GLOBAL_SKILLS  # 兼容 bge_layer 等旧引用名
SKILL_CONTENT = os.environ.get(
    "FENJUE_SKILL_CONTENT", os.path.join(GLOBAL_MEMORY, "skill_content")
)
PLUGIN_SKILLS_DIR = os.environ.get(
    "FENJUE_PLUGIN_SKILLS_DIR", r"<NPM_GLOBAL>\node_modules\openclaw\skills"
)
# 系统目录排除清单（不算 skill）：单一真相源（原 build_indexes/build_registry/
# functional_dim_checks/verify_truth_consistency/scorecard_sync 五处硬拷贝，漂移即口径分裂）
SYSTEM_DIRS = ("_temp", "_trash", "_bak", ".git", ".hermes")
ROUTE_TRACE = os.path.join(EVAL_DIR, "route_trace.jsonl")
