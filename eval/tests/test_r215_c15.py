# -*- coding: utf-8 -*-
"""R215 C15 单测：G8 数据流假设锚定面校验（verify_truth_consistency.check_c15_dataflow_assumption）。

覆盖：checks 注册防移除 / 无日志 SKIP / 有锚点 PASS / 有代码标记无锚点 FAIL / 无标记 PASS。
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import verify_truth_consistency as vtc  # noqa: E402

DAY = '2026-09-06'
LOG_SUBDIR = os.path.join('.workbuddy', 'memory')


def test_c15_registered_in_checks():
    """C15 已注册进 verify checks 列表（防门禁被悄悄移除）。"""
    src = inspect.getsource(vtc.main)
    assert 'C15' in src and 'check_c15_dataflow_assumption' in src


def test_c15_no_log_skips(tmp_path, monkeypatch):
    """当日日志不存在 -> SKIP（无锚定面）。"""
    monkeypatch.setattr(vtc, 'PROJECT_DIR', str(tmp_path))
    status, detail = vtc.check_c15_dataflow_assumption(today=DAY)
    assert status == 'SKIP' and DAY in detail


def test_c15_anchor_passes(tmp_path, monkeypatch):
    """日志含「数据流假设」锚点 -> PASS（G8 已留痕）。"""
    logdir = tmp_path / LOG_SUBDIR
    logdir.mkdir(parents=True)
    (logdir / (DAY + '.md')).write_text(
        '# 日志\n## R215 轮\n- G8 数据流假设落地\n', encoding='utf-8')
    monkeypatch.setattr(vtc, 'PROJECT_DIR', str(tmp_path))
    status, _ = vtc.check_c15_dataflow_assumption(today=DAY)
    assert status == 'PASS'


def test_c15_code_mark_without_anchor_fails(tmp_path, monkeypatch):
    """日志记录了代码修改痕迹（hash/rule_editor）但无锚点 -> FAIL。"""
    logdir = tmp_path / LOG_SUBDIR
    logdir.mkdir(parents=True)
    (logdir / (DAY + '.md')).write_text(
        '# 日志\n- 提交 e8a39df 修复分母\n', encoding='utf-8')
    monkeypatch.setattr(vtc, 'PROJECT_DIR', str(tmp_path))
    status, detail = vtc.check_c15_dataflow_assumption(today=DAY)
    assert status == 'FAIL' and '锚点' in detail


def test_c15_no_code_mark_passes(tmp_path, monkeypatch):
    """日志无代码修改痕迹 -> PASS（G8 不触发）。"""
    logdir = tmp_path / LOG_SUBDIR
    logdir.mkdir(parents=True)
    (logdir / (DAY + '.md')).write_text(
        '# 日志\n- 纯咨询轮，只回答了概念问题\n', encoding='utf-8')
    monkeypatch.setattr(vtc, 'PROJECT_DIR', str(tmp_path))
    status, _ = vtc.check_c15_dataflow_assumption(today=DAY)
    assert status == 'PASS'
