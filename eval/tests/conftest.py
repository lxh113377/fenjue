#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
conftest.py — 让 pytest 能在 eval/tests/ 下 import 兄弟模块。

历史原因: triple_diff / unified_router / direct_layer 都在 eval/ 或 audit/ 下，
不在同一 package。把 PROJECT_ROOT 与 eval/ 加入 sys.path，测试即可:
    from audit.triple_diff import compute_triple_diff
    from unified_router import direct_route
"""
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVAL_DIR = os.path.join(PROJECT_ROOT, 'eval')
AUDIT_DIR = os.path.join(PROJECT_ROOT, 'audit')

for p in (PROJECT_ROOT, EVAL_DIR, AUDIT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _scrub_hook_git_env(monkeypatch):
    """R279b（2026-09-23）：剥离继承的 GIT_* 环境（hook 污染隔离）。

    实证：pre-commit hook 导出的 GIT_DIR（真仓 .git 绝对路径）会让
    测试内所有 `git` 子进程（mini 仓 fixture、_git 助手）误操作真仓——
    已实测导致真仓被连投 36 个测试提交、681 文件 tree 缺失、远端污染。
    本 fixture 全文件自动生效；确需 GIT_* 的单测须显式 monkeypatch.setenv
    （如 test_git_atomicity_ignores_inherited_hook_env）。
    """
    for var in list(os.environ):
        if var.startswith("GIT_"):
            monkeypatch.delenv(var, raising=False)
