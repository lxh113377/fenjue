#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""direct_layer 守护测试（R209-2③：生产第一跳，58% → 行为锁定）。

守护契约:
  ① 直连优先级（首条命中即短路）
  ② _cregex 预编译缓存（R209 P1：同 pattern 返回同一 compiled 对象）
  ③ 本地守卫（R18.2）：本地关键词跳过云端直连，无替代时回落次优
  ④ NOT USE 负标签守卫（R20）+ 否定前缀放行
  ⑤ 坏正则跳过不崩（except re.error 兜底）
  ⑥ FENJUE_DIRECT_MAP_DIR 测试目录覆盖（R165）+ reload 隔离
"""
import importlib
import json
import os
import sys

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import direct_layer as dl  # noqa: E402

RULES = [
    ['做PPT|生成PPT', 'ppt-skill-a'],
    ['画.*流程图', 'flow-skill-b'],
    ['生成图片', 'byted-seedream-image-generate'],  # 云端 skill（本地守卫名单内）
]


@pytest.fixture()
def dm_reload(tmp_path, monkeypatch):
    """FENJUE_DIRECT_MAP_DIR 指向 tmp 规则目录 → reload 生效 → teardown 还原。"""
    d = tmp_path / 'dm.d'
    d.mkdir()
    (d / 'a.json').write_text(
        json.dumps(RULES, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setenv('FENJUE_DIRECT_MAP_DIR', str(d))
    importlib.reload(dl)
    yield dl
    monkeypatch.undo()
    importlib.reload(dl)  # 恢复真实 DIRECT_MAP，防污染同进程其他测试


def test_direct_route_first_match_wins(dm_reload):
    assert dm_reload.direct_route('帮我做PPT') == 'ppt-skill-a'
    assert dm_reload.direct_route('生成PPT大纲') == 'ppt-skill-a'


def test_direct_route_second_pattern(dm_reload):
    assert dm_reload.direct_route('帮我画一个系统流程图') == 'flow-skill-b'


def test_direct_route_no_match_returns_none(dm_reload):
    assert dm_reload.direct_route('今天天气如何') is None


def test_direct_route_bad_regex_skipped(tmp_path, monkeypatch):
    d = tmp_path / 'dm2.d'
    d.mkdir()
    (d / 'a.json').write_text(
        json.dumps([['[unclosed', 'sk-bad'], ['规则乙', 'sk2']]), encoding='utf-8')
    monkeypatch.setenv('FENJUE_DIRECT_MAP_DIR', str(d))
    importlib.reload(dl)
    try:
        assert dl.direct_route('匹配规则乙') == 'sk2'  # 坏正则跳过不崩
    finally:
        monkeypatch.undo()
        importlib.reload(dl)


def test_local_guard_skips_cloud_without_fallback(dm_reload):
    # 单条云端规则 + 本地关键词 → 跳过；skipped_cloud 回落后仍是它自身 → 返回次优
    # （R166 回落语义：无本地替代时回落被跳过的云端直连）
    assert dm_reload.direct_route('本地生成图片') == 'byted-seedream-image-generate'


def test_local_guard_prefers_non_cloud_rule(tmp_path, monkeypatch):
    d = tmp_path / 'dm3.d'
    d.mkdir()
    (d / 'a.json').write_text(json.dumps([
        ['本地生成图片', 'local-first-skill'],
        ['生成图片', 'byted-seedream-image-generate'],
    ], ensure_ascii=False), encoding='utf-8')
    monkeypatch.setenv('FENJUE_DIRECT_MAP_DIR', str(d))
    importlib.reload(dl)
    try:
        # 第一条非云端规则先命中 → 直接返回，不触云端
        assert dl.direct_route('本地生成图片') == 'local-first-skill'
    finally:
        monkeypatch.undo()
        importlib.reload(dl)


def test_negative_tag_guard_blocks_then_negation_releases(dm_reload, monkeypatch):
    monkeypatch.setattr(dm_reload, 'NEGATIVE_TAG_MAP', {'flow-skill-b': ['纯手工.*流程']})
    # 命中 '画.*流程图' 且负标签生效（匹配点前缀无否定词）→ 放弃直连
    assert dm_reload.direct_route('帮我画纯手工流程图') is None
    # 匹配点前 6 字符含否定词 '不用'（R20.1）→ 负标签失效 → 放行
    assert dm_reload.direct_route('不用画纯手工流程图') == 'flow-skill-b'


def test_cregex_cache_identity(dm_reload):
    c1 = dm_reload._cregex('abc.*def')
    c2 = dm_reload._cregex('abc.*def')
    assert c1 is c2                       # R209 P1: 同 pattern 返回同一 compiled 对象
    assert dm_reload._cregex('xyz') is not c1


def test_cregex_cache_after_real_route(dm_reload):
    dm_reload.direct_route('帮我做PPT')
    assert any('PPT' in k for k in dm_reload._CREGEX_CACHE)


def test_valid_entries_structure():
    assert dl._valid_entries([['a', 'b']]) == [('a', 'b')]
    assert dl._valid_entries([('a', 'b')]) == [('a', 'b')]
    assert dl._valid_entries([]) == []
    assert dl._valid_entries(None) == []
    assert dl._valid_entries([['a']]) == []          # 元数不足
    assert dl._valid_entries([[1, 'b']]) == []       # 非字符串 pattern
    assert dl._valid_entries('not-a-list') == []
