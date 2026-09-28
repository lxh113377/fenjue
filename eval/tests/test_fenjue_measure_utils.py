#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fenjue_measure 纯函数参数化测试（R193 阶段2）。"""

import os
import sys

import pytest

AUDIT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if AUDIT_DIR not in sys.path:
    sys.path.insert(0, AUDIT_DIR)

from fenjue_measure_utils import clamp, extract_links, read_split_text  # noqa: E402


@pytest.mark.parametrize("v,lo,hi,expected", [
    (5, 0, 10, 5),
    (-1, 0, 10, 0),
    (11, 0, 10, 10),
    (0, 0, 10, 0),
])
def test_clamp(v, lo, hi, expected):
    assert clamp(v, lo, hi) == expected


def test_extract_links_markdown_and_backtick():
    links = extract_links("[a](x.md) `y.json` <MEMORY_ROOT>\\meta\\a.md")
    assert {"x.md", "y.json", r"<MEMORY_ROOT>\meta\a.md"} <= links


def test_extract_links_ignores_urls_and_placeholders():
    links = extract_links("http://example.com #anchor {var} `code.json` `plain.txt`")
    assert links == {"code.json"}


def test_read_split_text_merges_parts(tmp_path):
    base = tmp_path / "doc.md"
    base.write_text("壳", encoding="utf-8")
    (tmp_path / "doc.part1.md").write_text("卷1", encoding="utf-8")
    (tmp_path / "doc.part2.md").write_text("卷2", encoding="utf-8")
    (tmp_path / "other.part1.md").write_text("无关", encoding="utf-8")

    def read_fn(p):
        return open(p, encoding="utf-8").read()

    out = read_split_text(read_fn, str(base))
    assert out == "壳\n卷1\n卷2"


def test_read_split_text_without_parts(tmp_path):
    base = tmp_path / "solo.md"
    base.write_text("只有壳", encoding="utf-8")
    assert read_split_text(lambda p: open(p, encoding="utf-8").read(), str(base)) == "只有壳"
