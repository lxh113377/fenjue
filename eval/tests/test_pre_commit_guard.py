#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pre-commit direct-map 护栏单测（R193 补充）：direct_map.d/ 存在即拦截。"""

import os
import subprocess
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import pre_commit_hooks as pch  # noqa: E402


def test_direct_map_guard_pass_without_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pch, "ROOT", str(tmp_path))
    assert pch.check_direct_map_dir() is True


def test_direct_map_guard_fail_when_dir_exists(tmp_path, monkeypatch):
    (tmp_path / "eval" / "direct_map.d").mkdir(parents=True)
    monkeypatch.setattr(pch, "ROOT", str(tmp_path))
    assert pch.check_direct_map_dir() is False


def test_direct_map_guard_fail_on_loose_file(tmp_path, monkeypatch):
    """目录不存在但残留直接文件（误建）同样拦截。"""
    (tmp_path / "eval").mkdir(parents=True)
    (tmp_path / "eval" / "direct_map.d").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(pch, "ROOT", str(tmp_path))
    assert pch.check_direct_map_dir() is False


def test_duplicate_guard_pass_on_clean(tmp_path, monkeypatch):
    for d in ("eval", "audit", "scripts", "feedback"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pch, "ROOT", str(tmp_path))
    assert pch.check_duplicates() is True


def test_duplicate_guard_fail_on_backup_suffix(tmp_path, monkeypatch):
    (tmp_path / "eval").mkdir(parents=True)
    (tmp_path / "eval" / "router_v1_backup.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(pch, "ROOT", str(tmp_path))
    assert pch.check_duplicates() is False


def test_duplicate_guard_fail_on_cross_dir_same_name(tmp_path, monkeypatch):
    (tmp_path / "eval").mkdir(parents=True)
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "eval" / "same.py").write_text("a", encoding="utf-8")
    (tmp_path / "scripts" / "same.py").write_text("b", encoding="utf-8")
    monkeypatch.setattr(pch, "ROOT", str(tmp_path))
    assert pch.check_duplicates() is False


def test_duplicate_guard_publish_exempt(tmp_path, monkeypatch):
    (tmp_path / "publish").mkdir(parents=True)
    (tmp_path / "publish" / "tool_bak.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(pch, "ROOT", str(tmp_path))
    assert pch.check_duplicates() is True


# ── index-refs 闸（R196-05 CI 化）─────────────────────────────────────────────
# 目标：mock git diff 输出，验证「触发拦截」与「不触发放行」两分支。

def _fake_git_diff(stdout_text, exc=None):
    """构造 mock subprocess.run：返回指定 stdout，或抛异常。"""
    def _run(cmd, **kwargs):
        if exc:
            raise exc
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout_text)
    return _run


def test_commit_touches_index_refs_true_part3(monkeypatch):
    """触发分支：暂存含 memory_index.part3.md → True。"""
    fake = _fake_git_diff("eval/foo.py\n<MEMORY_ROOT>/meta/memory_index.part3.md\n")
    monkeypatch.setattr(pch.subprocess, "run", fake)
    assert pch._commit_touches_index_refs() is True


def test_commit_touches_index_refs_true_part3_1(monkeypatch):
    """触发分支：暂存含 memory_index.part3-1.md（glob 前缀命中）→ True。"""
    fake = _fake_git_diff("meta/memory_index.part3-1.md\n")
    monkeypatch.setattr(pch.subprocess, "run", fake)
    assert pch._commit_touches_index_refs() is True


def test_commit_touches_index_refs_false_other_files(monkeypatch):
    """不触发分支：暂存仅普通文件 → False。"""
    fake = _fake_git_diff("eval/foo.py\nmemory/07-next-steps.part17.md\n")
    monkeypatch.setattr(pch.subprocess, "run", fake)
    assert pch._commit_touches_index_refs() is False


def test_commit_touches_index_refs_false_empty(monkeypatch):
    """不触发分支：无暂存改动（空输出）→ False，不误拦。"""
    fake = _fake_git_diff("")
    monkeypatch.setattr(pch.subprocess, "run", fake)
    assert pch._commit_touches_index_refs() is False


def test_commit_touches_index_refs_false_on_exception(monkeypatch):
    """异常降级：git diff 失败（非 git 环境）→ False（fail-safe 不误拦）。"""
    fake = _fake_git_diff("", exc=FileNotFoundError("git not found"))
    monkeypatch.setattr(pch.subprocess, "run", fake)
    assert pch._commit_touches_index_refs() is False


def _fake_run(returncode):
    """构造 mock _run：返回指定 returncode 的 CompletedProcess。"""
    def _run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode,
                                           stdout="", stderr="")
    return _run


def test_check_index_refs_trigger_block(monkeypatch):
    """触发拦截：索引改动 + 缺失（rc=1）→ False（fail-closed）。"""
    monkeypatch.setattr(pch, "_run", _fake_run(1))
    monkeypatch.setattr(pch, "_commit_touches_index_refs", lambda: True)
    assert pch.check_index_refs() is False


def test_check_index_refs_trigger_pass(monkeypatch):
    """触发放行：索引改动 + 全绿（rc=0）→ True。"""
    monkeypatch.setattr(pch, "_run", _fake_run(0))
    monkeypatch.setattr(pch, "_commit_touches_index_refs", lambda: True)
    assert pch.check_index_refs() is True


def test_check_index_refs_not_touched_pass(monkeypatch):
    """不触发放行：非索引改动 + 全绿 → True。"""
    monkeypatch.setattr(pch, "_run", _fake_run(0))
    monkeypatch.setattr(pch, "_commit_touches_index_refs", lambda: False)
    assert pch.check_index_refs() is True


def test_check_index_refs_not_touched_missing_nonblocking(monkeypatch):
    """不触发 + 缺失（rc=1）：放行（不阻断非索引改动），仅提示。"""
    monkeypatch.setattr(pch, "_run", _fake_run(1))
    monkeypatch.setattr(pch, "_commit_touches_index_refs", lambda: False)
    assert pch.check_index_refs() is True  # 不阻断


# ── path-index-due 闸（R199 第 10 闸）─────────────────────────────────────────

def test_path_index_due_pass_when_not_overdue(monkeypatch) -> None:
    """未逾期（rc=0）→ 放行（无论是否触发）。"""
    monkeypatch.setattr(pch, "_run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="✅ 未逾期\n", stderr=""))
    monkeypatch.setattr(pch, "_commit_touches_path_index", lambda: True)
    assert pch.check_path_index_due() is True


def test_path_index_due_block_when_overdue(monkeypatch) -> None:
    """触发（涉 path_index 改动）+ 逾期（rc=1）→ 拦截提交。"""
    monkeypatch.setattr(pch, "_run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="🔴 已逾期\n", stderr=""))
    monkeypatch.setattr(pch, "_commit_touches_path_index", lambda: True)
    assert pch.check_path_index_due() is False


def test_path_index_due_block_when_misconfig(monkeypatch) -> None:
    """触发 + 状态字段缺失/损坏（rc=2）→ 同样拦截（防放行）。"""
    monkeypatch.setattr(pch, "_run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, stdout="⚠️ 字段缺失\n", stderr=""))
    monkeypatch.setattr(pch, "_commit_touches_path_index", lambda: True)
    assert pch.check_path_index_due() is False


# ── path-index-due 触发条件分流（R199 降噪，2026-08-17）──────────────────────

def test_commit_touches_path_index_true(monkeypatch) -> None:
    fake = _fake_git_diff("meta/path_index.md\n")
    monkeypatch.setattr(pch.subprocess, "run", fake)
    assert pch._commit_touches_path_index() is True


def test_commit_touches_path_index_false(monkeypatch) -> None:
    fake = _fake_git_diff("eval/foo.py\nmemory/07-next-steps.part17.md\n")
    monkeypatch.setattr(pch.subprocess, "run", fake)
    assert pch._commit_touches_path_index() is False


def test_commit_touches_path_index_false_on_exception(monkeypatch) -> None:
    fake = _fake_git_diff("", exc=FileNotFoundError("git not found"))
    monkeypatch.setattr(pch.subprocess, "run", fake)
    assert pch._commit_touches_path_index() is False


def test_path_index_due_touched_overdue_blocks(monkeypatch) -> None:
    """触发（涉 path_index 改动）+ 逾期 → 拦截。"""
    monkeypatch.setattr(pch, "_run", _fake_run(1))
    monkeypatch.setattr(pch, "_commit_touches_path_index", lambda: True)
    assert pch.check_path_index_due() is False


def test_path_index_due_not_touched_overdue_warns_only(monkeypatch) -> None:
    """非触发 + 逾期 → 警告放行（不阻塞无关提交）。"""
    monkeypatch.setattr(pch, "_run", _fake_run(1))
    monkeypatch.setattr(pch, "_commit_touches_path_index", lambda: False)
    assert pch.check_path_index_due() is True


def test_path_index_due_touched_ok_passes(monkeypatch) -> None:
    """触发 + 未逾期 → 放行。"""
    monkeypatch.setattr(pch, "_run", _fake_run(0))
    monkeypatch.setattr(pch, "_commit_touches_path_index", lambda: True)
    assert pch.check_path_index_due() is True
