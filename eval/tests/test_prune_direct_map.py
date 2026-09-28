#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prune_direct_map 冒烟（R209-2③ 补测簇：208 stmts 0%）。

覆盖: first_matching_remove 剪枝判定 / report 汇总口径 / _restore_map 只读回退。
"""
import json
import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import direct_layer  # noqa: E402
import prune_direct_map as pdm  # noqa: E402


def test_first_matching_remove_hits_only_removed():
    dm = [['规则甲', 'sk1'], ['规则乙', 'sk2']]
    assert pdm.first_matching_remove('匹配规则乙', dm, {1}) == 1
    # 规则乙不在 remove 集 → 即使匹配也跳过
    assert pdm.first_matching_remove('匹配规则乙', dm, {0}) is None


def test_first_matching_remove_bad_regex_skipped():
    dm = [['[unclosed', 'sk-bad'], ['规则乙', 'sk2']]
    assert pdm.first_matching_remove('匹配规则乙', dm, {0, 1}) == 1


def test_first_matching_remove_none():
    dm = [['规则甲', 'sk1']]
    assert pdm.first_matching_remove('完全不相关', dm, {0}) is None


def test_report_smoke(tmp_path, monkeypatch):
    results = [{'matched': [0, 1], 'changes': [{'rule': 1}]},
               {'matched': [0], 'changes': []}]
    (tmp_path / 'prune_results.json').write_text(
        json.dumps(results), encoding='utf-8')
    monkeypatch.setattr(pdm, 'RESULT_PATH', str(tmp_path / 'prune_results.json'))
    monkeypatch.setattr(pdm, 'TMP', str(tmp_path))
    dm = direct_layer._load_direct_map()
    out = pdm.report()
    assert out['total'] == len(dm)
    assert out['matched'] == len({0, 1})
    assert 1 in out['load_bearing']          # changed 规则是承重规则
    assert 0 in out['prunable']              # 命中但无 changes → 可剪
    assert (tmp_path / 'prune_report.json').exists()


def test_restore_map_readonly():
    dm = pdm._restore_map()
    assert isinstance(dm, list) and len(dm) > 0
    assert all(isinstance(e, tuple) and len(e) == 2 for e in dm[:5])
