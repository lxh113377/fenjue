#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan_secrets 密钥扫描测试。"""

import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import scan_secrets as ss  # noqa: E402


def test_scan_secrets_finds_key(monkeypatch, tmp_path) -> None:
    fake_key = "sk-" + "a" * 40  # 动态拼接，避免静态匹配触发扫描器
    (tmp_path / "secret.txt").write_text(
        f"token {fake_key} end", encoding="utf-8"
    )
    monkeypatch.setattr(ss, "ROOT", str(tmp_path))
    assert ss.main() == 1


def test_scan_secrets_clean(monkeypatch, tmp_path) -> None:
    (tmp_path / "ok.txt").write_text("no secrets here", encoding="utf-8")
    monkeypatch.setattr(ss, "ROOT", str(tmp_path))
    assert ss.main() == 0


# === R207 N3: 扩展形态（动态拼接，防测试自身触发全仓扫描） ===

def test_scan_secrets_github_token(monkeypatch, tmp_path) -> None:
    fake = "ghp_" + "a" * 36
    (tmp_path / "gh.txt").write_text(f"token {fake} end", encoding="utf-8")
    monkeypatch.setattr(ss, "ROOT", str(tmp_path))
    assert ss.main() == 1


def test_scan_secrets_github_finegrained(monkeypatch, tmp_path) -> None:
    fake = "github_pat_" + "a" * 30
    (tmp_path / "ghfg.txt").write_text(f"pat={fake}", encoding="utf-8")
    monkeypatch.setattr(ss, "ROOT", str(tmp_path))
    assert ss.main() == 1


def test_scan_secrets_aws_key(monkeypatch, tmp_path) -> None:
    fake = "AKIA" + "A" * 16
    (tmp_path / "aws.txt").write_text(f"aws_access_key={fake}", encoding="utf-8")
    monkeypatch.setattr(ss, "ROOT", str(tmp_path))
    assert ss.main() == 1


def test_scan_secrets_google_key(monkeypatch, tmp_path) -> None:
    fake = "AIza" + "0" * 35
    (tmp_path / "gcp.txt").write_text(f"key={fake}", encoding="utf-8")
    monkeypatch.setattr(ss, "ROOT", str(tmp_path))
    assert ss.main() == 1


def test_scan_secrets_private_key(monkeypatch, tmp_path) -> None:
    head = "-----BEGIN " + "PRIVATE KEY-----"
    (tmp_path / "id_rsa.txt").write_text(f"{head}\nabcdef", encoding="utf-8")
    monkeypatch.setattr(ss, "ROOT", str(tmp_path))
    assert ss.main() == 1


def test_scan_secrets_clean_remains_clean(monkeypatch, tmp_path) -> None:
    """误报护栏: 普通文本/哈希串不应触发新模式。"""
    (tmp_path / "hash.txt").write_text(
        "sha256=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08 "
        "AKIA-like-not-a-key "  # 无 16 位大写尾
        "xox-not-slack",
        encoding="utf-8",
    )
    monkeypatch.setattr(ss, "ROOT", str(tmp_path))
    assert ss.main() == 0
