#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_guard 契约测试（R196）：env_mode 读取 + 备份/密钥/入库保护检查。"""

import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import env_guard as eg  # noqa: E402


def test_read_env_mode_from_constraints(tmp_path, monkeypatch):
    monkeypatch.delenv("ENV_MODE", raising=False)
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "06-constraints.md").write_text(
        "# 06\n\n## 环境隔离（R196）\n- env_mode: production\n", encoding="utf-8")
    assert eg.read_env_mode(str(tmp_path)) == "production"


def test_read_env_mode_env_var_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("ENV_MODE", "staging")
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "06-constraints.md").write_text(
        "- env_mode: production\n", encoding="utf-8")
    assert eg.read_env_mode(str(tmp_path)) == "staging"


def test_read_env_mode_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("ENV_MODE", raising=False)
    assert eg.read_env_mode(str(tmp_path)) is None


def test_backup_recency_reports_stale(tmp_path, monkeypatch):
    import datetime
    old = datetime.datetime.now() - datetime.timedelta(days=30)
    snap = tmp_path / "gm-snap"
    snap.mkdir()
    os.utime(snap, (old.timestamp(), old.timestamp()))
    monkeypatch.setattr(eg, "DR_SNAPSHOT_ROOT", str(tmp_path))
    monkeypatch.setattr(eg, "PROJECT_DIR", str(tmp_path / "nonexistent"))
    ok, detail = eg.check_backup_recency()
    assert ok is False
    assert "超过" in detail


def test_backup_recency_fresh(tmp_path, monkeypatch):
    snap = tmp_path / "gm-snap"
    snap.mkdir()
    monkeypatch.setattr(eg, "DR_SNAPSHOT_ROOT", str(tmp_path))
    monkeypatch.setattr(eg, "PROJECT_DIR", str(tmp_path / "nonexistent"))
    ok, detail = eg.check_backup_recency()
    assert ok is True


def test_env_file_protection_untracked_ok(tmp_path):
    ok, _ = eg.check_env_file_protection(str(tmp_path))
    assert ok is True


def test_env_guard_main_exit_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ENV_MODE", "development")
    assert eg.main(["--project", str(tmp_path), "--json"]) == 0
    import json
    data = json.loads(capsys.readouterr().out)
    assert data["env_mode"] == "development"
    assert data["all_warn"] is False
