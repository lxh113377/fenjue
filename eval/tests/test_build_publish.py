#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_publish.py 契约测试（R212, 2026-09-05）。

覆盖 R212 语义修订：
  - 一致 → --check 通过；
  - KNOWN_DIVERGED 刻意分叉 → 豁免不 FAIL（构建时跳过覆盖）；
  - 孤儿副本（不在 SOURCES 清单）→ --check FAIL；
  - 缺失副本 → --check FAIL，构建自动补齐；
  - 非分叉漂移无 --force → 构建拒绝；--force 才覆盖。
"""

from __future__ import annotations

import pytest

from scripts import build_publish as bp


@pytest.fixture
def layout(tmp_path, monkeypatch):
    """把 EVAL_DIR / PUBLISH_EVAL_DIR 指到临时目录；默认副本=源（一致），
    仅 KNOWN_DIVERGED 文件保留差异（人决策认可的刻意分叉现状）。"""
    ev = tmp_path / "eval"
    pub = tmp_path / "pub" / "eval"
    ev.mkdir(parents=True)
    pub.mkdir(parents=True)
    for src, dst in bp.SOURCES:
        (ev / src).write_text(f"SRC {dst}\n", encoding="utf-8")
        if dst in bp.KNOWN_DIVERGED:
            (pub / dst).write_text(f"DIVERGED {dst}\n", encoding="utf-8")
        else:
            (pub / dst).write_text(f"SRC {dst}\n", encoding="utf-8")
    monkeypatch.setattr(bp, "EVAL_DIR", ev)
    monkeypatch.setattr(bp, "PUBLISH_EVAL_DIR", pub)
    return ev, pub


def test_check_all_aligned(layout) -> None:
    """源/副本字节一致 → --check 通过。"""
    ev, pub = layout
    for src, dst in bp.SOURCES:
        (pub / dst).write_text((ev / src).read_text(encoding="utf-8"), encoding="utf-8")
    assert bp.cmd_check() == 0


def test_check_known_diverged_exempt(layout) -> None:
    """KNOWN_DIVERGED 文件源/副本不同 → 豁免不 FAIL。"""
    assert bp.cmd_check() == 0


def test_check_orphan_fails(layout) -> None:
    """孤儿副本（不在 SOURCES 清单的 .py）→ --check FAIL。"""
    ev, pub = layout
    (pub / "orphan_inject.py").write_text("X\n", encoding="utf-8")
    assert bp.cmd_check() == 1


def test_check_missing_fails(layout) -> None:
    """副本缺失 → --check FAIL。"""
    ev, pub = layout
    (pub / bp.SOURCES[0][1]).unlink()
    assert bp.cmd_check() == 1


def test_build_fills_missing(layout) -> None:
    """缺失副本 → 构建自动补齐。"""
    ev, pub = layout
    _, dst = bp.SOURCES[0]
    (pub / dst).unlink()
    assert bp.cmd_build(force=False, dry_run=False) == 0
    assert (pub / dst).is_file()


def test_build_plain_drift_requires_force(layout) -> None:
    """非分叉漂移无 --force → 拒绝；带 --force → 覆盖。"""
    ev, pub = layout
    # 挑一个非 KNOWN_DIVERGED 文件制造漂移
    victim = next(iter(set(d for _, d in bp.SOURCES) - bp.KNOWN_DIVERGED))
    src_text = (ev / victim).read_text(encoding="utf-8")
    (pub / victim).write_text(src_text + "DRIFTED\n", encoding="utf-8")
    assert bp.cmd_build(force=False, dry_run=False) == 1
    assert bp.cmd_build(force=True, dry_run=False) == 0
    assert (pub / victim).read_text(encoding="utf-8") == src_text


def test_build_diverged_not_overwritten(layout) -> None:
    """KNOWN_DIVERGED 文件构建时跳过覆盖（保护人决策分叉现状）。"""
    ev, pub = layout
    victim = next(iter(bp.KNOWN_DIVERGED))
    before = (pub / victim).read_text(encoding="utf-8")
    (ev / victim).write_text("SRC 已更新\n", encoding="utf-8")
    assert bp.cmd_build(force=True, dry_run=False) == 0
    assert (pub / victim).read_text(encoding="utf-8") == before  # 未被覆盖