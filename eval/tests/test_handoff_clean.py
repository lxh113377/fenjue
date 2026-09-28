#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handoff clean 契约测试（R196，缺口-1 / 二.1）：dry-run 只出清单，--apply 才移动。"""

import importlib.util
import os
import pytest

HANDOFF_CANDIDATES = [
    r"<SKILLS_ROOT>\A-project-handoff\scripts\handoff.py",
    r"<USER_HOME>\.agents\skills\A-project-handoff\scripts\handoff.py",
]


def _load_handoff():
    for path in HANDOFF_CANDIDATES:
        if os.path.exists(path):
            # V3.41.0 起 handoff.py 拆分为 handoff_lib 包（同目录）——
            # spec_from_file_location 不带目录上下文，必须手动注入 sys.path
            # 否则 `from handoff_lib.common import ...` 直接 ModuleNotFoundError。
            import sys
            scripts_dir = os.path.dirname(path)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            spec = importlib.util.spec_from_file_location("handoff_r196", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    pytest.skip("handoff.py 不可达（CI/离线环境）")


def _make_project(tmp_path):
    """R199.4 契约（2026-09-21 更新）：顶层源码目录受豁免，过期副本只在非豁免目录被检出。

    - src/app_old.py  → 豁免（活代码保护，见 handoff_lib/common.py:53-58 与
      A-project-handoff/references/commands.md:90；iCAN 2026-09-12 src/rule_copy.py
      被误迁致 ImportError 的真实事故背书）
    - report_backup.md / docs/notes_copy.md → 应被检出
    """
    proj = tmp_path / "demo"
    (proj / "src").mkdir(parents=True)
    (proj / "docs").mkdir(parents=True)
    (proj / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "src" / "app_old.py").write_text("x = 2\n", encoding="utf-8")
    (proj / "docs" / "notes_copy.md").write_text("x\n", encoding="utf-8")
    (proj / "report_backup.md").write_text("x\n", encoding="utf-8")
    return proj


def test_scan_finds_stale_copies(tmp_path):
    h = _load_handoff()
    proj = _make_project(tmp_path)
    found = h.scan_stale_copies(proj)
    names = {os.path.basename(p) for p, kind, name in found}
    assert "report_backup.md" in names
    assert "notes_copy.md" in names
    assert "app.py" not in names
    # R199.4 回归守护：顶层源码目录整体豁免，src/ 内文件一律不判过期副本
    assert "app_old.py" not in names, "src/ 应受 STALE_PROTECTED_DIRS 豁免（防 iCAN ImportError 事故复发）"


def test_clean_dry_run_does_not_move(tmp_path, capsys):
    h = _load_handoff()
    proj = _make_project(tmp_path)
    assert h.cmd_clean(str(proj), apply_move=False) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    # dry-run 不移动任何文件（含被检出的）
    assert (proj / "src" / "app_old.py").exists()
    assert (proj / "report_backup.md").exists()
    assert not (proj / "archive").exists()


def test_clean_apply_moves_to_deprecated(tmp_path, capsys):
    h = _load_handoff()
    proj = _make_project(tmp_path)
    # --apply 会调 cmd_sync（force=True），demo 无 memory/ 会报错退出 1；
    # 允许 0 或 1：重点是文件已被移动且源不存在
    rc = h.cmd_clean(str(proj), apply_move=True)
    assert rc in (0, 1)
    dest_root = proj / "archive" / "deprecated"
    assert dest_root.exists()
    moved = {p.name for p in dest_root.rglob("*") if p.is_file()}
    assert {"report_backup.md", "notes_copy.md"} <= moved
    assert not (proj / "report_backup.md").exists()
    # 豁免目录内文件不得被移动（R199.4）
    assert (proj / "src" / "app_old.py").exists()
    assert not list(dest_root.rglob("app_old.py"))
