#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_index 输出契约测试。"""

import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import generate_index as gi  # noqa: E402


def test_generate_index_output(monkeypatch, tmp_path) -> None:
    out = tmp_path / "index.md"
    monkeypatch.setattr(gi, "INDEX_PATH", str(out))
    assert gi.main() == 0
    content = out.read_text(encoding="utf-8")
    assert "AUTO-GENERATED" in content
    # P0-1 收口（2026-09-23）：端数标签由真相源派生，禁硬编码四端/六端
    _cn = {3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八"}
    expected = f"{_cn.get(len(gi.ENDPOINTS), len(gi.ENDPOINTS))}端"
    assert expected in content
    assert "verify_truth_consistency" in content
