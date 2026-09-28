#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_router_trace_guard.py — R207 N1 回归测试。

背景: _legacy_cli() 内 TRACE_ENABLED/TRACE_SOURCE 赋值曾无 global 声明，
函数内赋值仅是局部遮蔽，模块级常量（import 时由 env 求值）不受影响 →
R168"eval 不写生产 trace"意图失效（--eval 仍以 production 身份写 trace）。
本测试: 预置模块级 TRACE_ENABLED=True/TRACE_SOURCE='production'（模拟生产默认），
调用 --eval CLI 后断言模块级已被改写为 False/'regression'（global 修复生效）。
"""

import sys

import unified_router as ur

FAKE_METRICS = {
    "total": 0,
    "direct_hits": 0,
    "direct_rate": 0.0,
    "llm_recommend": 0,
    "llm_recommend_rate": 0.0,
    "bge_only": {"top1": 0.0, "top3": 0.0, "correct": 0},
    "full_pipeline": {"top1": 0.0, "top3": 0.0, "correct": 0},
    "pipeline_delta": 0.0,
}


def test_eval_cli_disables_module_trace(monkeypatch, capsys) -> None:
    """--eval 后模块级 TRACE_ENABLED/TRACE_SOURCE 必须被 global 赋值改写。"""
    # 模拟生产默认（import 时 env FENJUE_ROUTE_TRACE=1 → True / 'production'）
    monkeypatch.setattr(ur, "TRACE_ENABLED", True)
    monkeypatch.setattr(ur, "TRACE_SOURCE", "production")
    # mock 掉 run_eval（避免真实全量推理），保留 --eval 分支的变量改写逻辑
    monkeypatch.setattr(ur, "run_eval", lambda *a, **k: FAKE_METRICS)
    monkeypatch.setattr(sys, "argv", ["unified_router.py", "--eval"])

    ur._legacy_cli()
    capsys.readouterr()  # 吸收 CLI 输出

    assert ur.TRACE_ENABLED is False, (
        "N1 回归: --eval 后模块级 TRACE_ENABLED 必须为 False（缺 global 声明时此断言失败）"
    )
    assert ur.TRACE_SOURCE == "regression", (
        "N1 回归: --eval 后模块级 TRACE_SOURCE 必须为 'regression'"
    )
