#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style_ratchet 单元测试（R210-05）：双层键控 diff + 降级分支。"""
import json
import os
import sys

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import style_ratchet as sr  # noqa: E402


@pytest.fixture()
def ratchet(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "BASELINE_PATH", str(tmp_path / "baseline.json"))
    return sr


def _write_baseline(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def test_new_file_violation_fails(ratchet, tmp_path, monkeypatch):
    _write_baseline(ratchet.BASELINE_PATH, {"eval/a.py": {"E701": 2}})
    monkeypatch.setattr(ratchet, "_run_ruff",
                        lambda: ({"eval/b.py": {"E741": 3}}, ""))
    assert ratchet.check() == 1  # 新文件出现违规 → FAIL


def test_count_increase_fails(ratchet, tmp_path, monkeypatch):
    _write_baseline(ratchet.BASELINE_PATH, {"eval/a.py": {"E701": 2}})
    monkeypatch.setattr(ratchet, "_run_ruff",
                        lambda: ({"eval/a.py": {"E701": 5}}, ""))
    assert ratchet.check() == 1  # 同文件计数上升 → FAIL


def test_structural_reversal_fails(ratchet, tmp_path, monkeypatch):
    # 总数不变但结构反弹：E701 清零、E741 新增 → 双层键控必须拦截
    _write_baseline(ratchet.BASELINE_PATH, {"eval/a.py": {"E701": 3}})
    monkeypatch.setattr(ratchet, "_run_ruff",
                        lambda: ({"eval/a.py": {"E741": 3}}, ""))
    assert ratchet.check() == 1


def test_decrease_passes_with_improvement_hint(ratchet, tmp_path, monkeypatch, capsys):
    _write_baseline(ratchet.BASELINE_PATH, {"eval/a.py": {"E701": 5}})
    monkeypatch.setattr(ratchet, "_run_ruff",
                        lambda: ({"eval/a.py": {"E701": 2}}, ""))
    assert ratchet.check() == 0  # 下降放行（棘轮只进不退）
    assert "存量改善" in capsys.readouterr().out


def test_ruff_unavailable_skips(ratchet, tmp_path, monkeypatch, capsys):
    _write_baseline(ratchet.BASELINE_PATH, {"eval/a.py": {"E701": 1}})
    monkeypatch.setattr(ratchet, "_run_ruff", lambda: (None, "ruff 不可用（模拟）"))
    assert ratchet.check() == 0  # 降级 SKIP 放行
    assert "SKIP" in capsys.readouterr().out


def test_baseline_missing_fails(ratchet, tmp_path):
    # 基线文件不存在 → exit 2（提示先 --update-baseline）
    assert ratchet.check() == 2
