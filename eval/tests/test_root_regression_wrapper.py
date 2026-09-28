# -*- coding: utf-8 -*-
"""test_root_regression_wrapper.py — R208 A4（P2-3）根级回归脚本接入本地 pytest 收集链。

eval/ 根级 4 个回归/门禁脚本（test_historical_regression / test_negative_guard /
test_not_use_boundary / test_router_regression）以「子进程 + 退出码」作为 CI 门禁
（ci.yml run_gate 显式调用），不是 pytest 风格模块，无法被 pytest 直接收集。

本 wrapper 以 subprocess 集成测试方式将其纳入本地 pytest 收集链（行为等价），
期望退出码 0 = 通过（含 SKIP 分支）；任一非 0 视为回归失败。
"""
import subprocess
import sys

import pytest

EVAL_DIR = "eval"


@pytest.mark.parametrize(
    "script",
    [
        "test_historical_regression.py",
        "test_negative_guard.py",
        "test_not_use_boundary.py",
        "test_router_regression.py",
    ],
)
def test_root_regression_script_exit_zero(script):
    r = subprocess.run(
        [sys.executable, script],
        cwd=EVAL_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )
    assert r.returncode == 0, (
        f"{script} 退出码 {r.returncode}（0=通过/含SKIP, 1=有FAIL）\n"
        f"--- stdout ---\n{r.stdout[-2000:]}\n--- stderr ---\n{r.stderr[-1000:]}"
    )