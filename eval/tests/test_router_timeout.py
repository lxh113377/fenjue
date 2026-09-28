#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""unified_router --timeout 内部保障测试（R192）。"""

import os
import sys
import time

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import unified_router as ur  # noqa: E402


def test_timeout_guard_raises_after_deadline() -> None:
    guard = ur.TimeoutGuard(0.05)
    time.sleep(0.07)
    with pytest.raises(ur.RouteTimeout):
        guard.check()


def test_timeout_guard_within_budget_passes() -> None:
    ur.TimeoutGuard(5).check()


def test_cli_timeout_missing_value() -> None:
    assert ur.cli_main(["--timeout"]) == 2


def test_cli_timeout_non_numeric() -> None:
    assert ur.cli_main(["--timeout", "abc"]) == 2


def test_cli_timeout_maps_route_timeout_to_124(monkeypatch, capsys) -> None:
    def boom(query):
        raise ur.RouteTimeout("timeout")

    monkeypatch.setattr(ur, "route", boom)
    assert ur.cli_main(["--json", "--timeout", "5", "测试"]) == 124
    out = capsys.readouterr().out
    assert "timeout" in out
    assert "degraded" in out
