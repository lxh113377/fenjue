#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常用技能表存在性 + 格式测试（R194）。"""

import os

import pytest  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMMON_FILE = os.path.join(PROJECT_ROOT, "memory", "常用技能.md")
SKILLS_DIR = r"<SKILLS_ROOT>"

# R209-3: memory/ 已 gitignore（CI 无此文件），技能树为本机 junction 环境 → CI 跳过。
pytestmark = pytest.mark.skipif(
    not (os.path.exists(COMMON_FILE) and os.path.isdir(SKILLS_DIR)),
    reason="依赖本机 memory/常用技能.md 与 global_skills（CI 跳过）")

RESIDENT = (
    "A-memory-start",
    "A-project-handoff",
    "A-get-memory",
    "A-ask-questions",
    "A-prompt-better",
)


def test_common_skills_file_exists():
    assert os.path.isfile(COMMON_FILE)


def test_common_skills_size_within_4kb():
    assert os.path.getsize(COMMON_FILE) <= 4096


def test_common_skills_has_all_sections():
    with open(COMMON_FILE, encoding="utf-8") as fh:
        text = fh.read()
    for section in ("常驻", "项目常用", "按需", "补录区"):
        assert section in text


def test_common_skills_resident_present():
    with open(COMMON_FILE, encoding="utf-8") as fh:
        text = fh.read()
    for name in RESIDENT:
        assert name in text


def test_common_skills_entries_exist_on_disk():
    with open(COMMON_FILE, encoding="utf-8") as fh:
        text = fh.read()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        name = line[2:].split("—")[0].strip()
        if not name or name == "（空）" or "→" in name:
            continue
        assert os.path.isfile(os.path.join(SKILLS_DIR, name, "SKILL.md")), f"{name} 缺失"
