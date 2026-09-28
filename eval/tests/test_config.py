#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config 路径配置化测试。"""

import importlib
import os

import pytest  # noqa: E402
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import config  # noqa: E402


@pytest.mark.skipif(os.name != "nt",
                    reason="PROJECT_DIR 目录名断言依赖本机仓库名（CI checkout 目录名不同，跳过）")
def test_config_env_override(monkeypatch) -> None:
    monkeypatch.setenv("FENJUE_SKILLS_DIR", r"X:\skills")
    monkeypatch.setenv("FENJUE_GLOBAL_MEMORY", r"X:\memory")
    try:
        mod = importlib.reload(config)
        assert mod.GLOBAL_SKILLS == r"X:\skills"
        assert mod.GLOBAL_MEMORY == r"X:\memory"
        assert mod.SKILL_CONTENT == os.path.join(mod.GLOBAL_MEMORY, "skill_content")  # R209-3: 平台中立（Linux os.path.join 不转反斜杠）
        assert mod.PROJECT_DIR == os.path.dirname(os.path.dirname(os.path.abspath(config.__file__))) \
            and os.path.isfile(os.path.join(mod.PROJECT_DIR, "eval", "config.py")), \
            "PROJECT_DIR 解析必须指向含 eval/config.py 的治理仓根（按目录名断言在 clone/worktree 下必假红）"
    finally:
        # reload 会把脏值经 sys.modules 泄漏给其后所有运行时读 config 的模块
        # （2026-09-24 实证：C27/C28 real-surface 与 exit-code 全过测试被连污）。
        # monkeypatch.undo() 还原 env 后必须再 reload 回干净态。
        monkeypatch.undo()
        importlib.reload(config)
