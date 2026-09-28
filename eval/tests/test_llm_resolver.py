#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_llm_resolver.py — llm_layer 决策层契约测试（R192 适配现役 API）。

原 mock 端到端测试引用 R162.1 已并轨移除的 resolve_llm_decision；
现役对外 API 为 build_llm_decision_prompt / _should_llm_decide。
"""

import sys

EVAL_DIR = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import llm_layer  # noqa: E402


def test_build_llm_decision_prompt_contract() -> None:
    cands = [
        {"name": "A-get-memory", "score": 0.5, "domain": "memory"},
        {"name": "fenjue-memory-audit", "score": 0.49, "domain": "memory"},
    ]
    prompt = llm_layer.build_llm_decision_prompt("审计一下记忆系统", cands)
    assert isinstance(prompt, dict)
    for key in ("system", "user", "full"):
        assert key in prompt
    assert "审计一下记忆系统" in prompt["user"]
    assert "A-get-memory" in prompt["full"]


def test_should_llm_decide_close_tie() -> None:
    cands = [
        {"name": "A-get-memory", "score": 0.51, "domain": "memory"},
        {"name": "fenjue-memory-audit", "score": 0.50, "domain": "memory"},
    ]
    should, reason = llm_layer._should_llm_decide(cands, "memory", "审计一下记忆系统")
    assert should is True
    assert "并列" in reason or "低置信" in reason


def test_should_llm_decide_clear_winner() -> None:
    cands = [
        {"name": "c-cleanup", "score": 0.9, "domain": "system"},
        {"name": "debugging-fixing", "score": 0.3, "domain": "code"},
    ]
    should, _ = llm_layer._should_llm_decide(cands, "system", "清理垃圾文件")
    assert should is False


def test_should_llm_decide_meta_exit_misalignment() -> None:
    cands = [
        {"name": "A-get-memory", "score": 0.8, "domain": "memory"},
        {"name": "fenjue-memory-audit", "score": 0.6, "domain": "memory"},
    ]
    should, reason = llm_layer._should_llm_decide(cands, "memory", "审计一下记忆系统")
    assert should is True
    assert "意图错位" in reason
