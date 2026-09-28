#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""memory_layer 单测（R193 阶段2）：正常/损坏/缺文件 + 纯函数参数化。"""

import json
import os
import sys
from datetime import datetime, timedelta

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import memory_layer as ml  # noqa: E402


def _reset_cache():
    ml._TRACE_FREQ_CACHE["ts"] = None
    ml._TRACE_FREQ_CACHE["freq"] = None
    ml._EVAL_QUERY_CACHE = None


def _trace_line(src, query, top1, days_ago=0):
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return json.dumps({"src": src, "q": query, "top1": top1, "ts": ts}, ensure_ascii=False)


def test_extract_context_tags_basic():
    tags = ml.extract_context_tags("帮我修复这个报错")
    assert "报错" in tags and "修复" in tags


def test_extract_context_tags_regex():
    assert "生成.*视频" in ml.extract_context_tags("帮我生成视频")
    assert "生成.*视频" not in ml.extract_context_tags("帮我生成图片")


def test_memory_boost_empty_candidates():
    assert ml.memory_boost([], "随便") == []


def test_memory_boost_no_tags_no_freq(monkeypatch):
    monkeypatch.setattr(ml, "_load_session_frequency", lambda: {})
    cands = [{"name": "x", "score": 0.5, "domain": "d", "boost": 0.0}]
    assert ml.memory_boost(cands, "完全无关的查询") == cands


def test_memory_boost_applies_boost(monkeypatch):
    monkeypatch.setattr(ml, "_load_session_frequency", lambda: {})
    cands = [
        {"name": "A-get-memory", "score": 0.42, "domain": "d", "boost": 0.0},
        {"name": "other", "score": 0.40, "domain": "d", "boost": 0.0},
    ]
    out = ml.memory_boost(cands, "帮我做记忆管理经验反哺")
    assert out[0]["name"] == "A-get-memory"
    assert out[0]["boost"] > 0


def test_memory_boost_conservative_no_flip(monkeypatch):
    monkeypatch.setattr(ml, "_load_session_frequency", lambda: {})
    cands = [
        {"name": "alpha", "score": 0.60, "domain": "d", "boost": 0.0},
        {"name": "A-get-memory", "score": 0.59, "domain": "d", "boost": 0.0},
    ]
    out = ml.memory_boost(cands, "记忆管理")
    # 弱 boost（<=0.10）不得推翻 BGE 原 top1
    assert out[0]["name"] == "alpha"


def test_normalize_freq_damping():
    assert ml._normalize_freq({}) == {}
    # 单次提及 → 压缩为 1/3，防弱证据满额 boost
    assert ml._normalize_freq({"skill-a": 1}) == {"skill-a": 1 / 3}
    # 高频归一化到 1.0
    assert ml._normalize_freq({"skill-a": 3, "skill-b": 6})["skill-b"] == 1.0


def test_load_trace_frequency_normal(monkeypatch, tmp_path):
    _reset_cache()
    monkeypatch.setattr(ml, "EVAL_DIR", str(tmp_path))
    trace = tmp_path / "route_trace.jsonl"
    trace.write_text(
        "\n".join([
            _trace_line("production", "真实用户问题", "skill-a", 0),
            _trace_line("production", "真实用户问题2", "skill-a", 0),
            _trace_line("production", "真实用户问题3", "skill-b", 0),
            _trace_line("regression", "评估查询", "skill-a", 0),  # 非 production 排除
            _trace_line("production", "NONE查询", "NONE", 0),      # NONE 排除
        ]) + "\n",
        encoding="utf-8",
    )
    freq = ml._load_trace_frequency()
    assert "skill-a" in freq and "skill-b" in freq
    assert freq["skill-a"] > freq["skill-b"]


def test_load_trace_frequency_corrupt(monkeypatch, tmp_path):
    _reset_cache()
    monkeypatch.setattr(ml, "EVAL_DIR", str(tmp_path))
    (tmp_path / "route_trace.jsonl").write_text(
        '{"src": "production", "q": "ok", "top1": "skill-a", "ts": "' +
        datetime.now().isoformat(timespec="seconds") + '"}\n'
        'NOT-A-JSON-LINE\n{"src": "production", "q": "x", "top1": "skill-b", "ts": "BAD-TS"}\n',
        encoding="utf-8",
    )
    freq = ml._load_trace_frequency()
    assert "skill-a" in freq  # 损坏行跳过不阻塞


def test_load_trace_frequency_missing(monkeypatch, tmp_path):
    _reset_cache()
    monkeypatch.setattr(ml, "EVAL_DIR", str(tmp_path))
    assert ml._load_trace_frequency() == {}


def test_load_trace_frequency_eval_query_excluded(monkeypatch, tmp_path):
    _reset_cache()
    monkeypatch.setattr(ml, "EVAL_DIR", str(tmp_path))
    (tmp_path / "test_queries.json").write_text(
        json.dumps([{"queries": [{"query": "评估集问题"}]}], ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "route_trace.jsonl").write_text(
        _trace_line("production", "评估集问题", "skill-a", 0) + "\n",
        encoding="utf-8",
    )
    assert ml._load_trace_frequency() == {}


# ====== R208 O-6 治本: eval 查询集 mtime 指纹缓存 ======

def test_known_eval_queries_cache_reuse_skips_source_read(monkeypatch, tmp_path):
    """正常轮（源 mtime 未变）只读派生件，不重读源 json（O-6 治本核心）。"""
    _reset_cache()
    monkeypatch.setattr(ml, "EVAL_DIR", str(tmp_path))
    src = tmp_path / "test_queries.json"
    src.write_text(json.dumps([{"queries": [{"query": "源查询A"}]}]), encoding="utf-8")
    assert "源查询A" in ml._known_eval_queries()

    # 派生件已落盘（首行 = mtime 指纹，其余 = 每行一个查询）
    meta_path = tmp_path / "_cache" / "eval_queries.txt"
    assert meta_path.is_file()
    first_line = meta_path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#E1 " + ml._eval_fingerprint(
        ml._eval_source_mtimes()), "指纹行应与当前 4 源 mtime 一致"

    # 源文件被改坏但 mtime 不变 → 走缓存命中，不碰损坏源（等于证明正常轮不重读源）
    mt = src.stat().st_mtime
    src.write_text("NOT-A-JSON", encoding="utf-8")
    os.utime(src, (mt, mt))
    _reset_cache()
    qs = ml._known_eval_queries()
    assert qs == {"源查询A"}, "mtime 未变应命中缓存，损坏源不应被读取"


def test_known_eval_queries_refresh_on_source_change(monkeypatch, tmp_path):
    """源文件 mtime 变更 → 指纹失效重建查询集。"""
    _reset_cache()
    monkeypatch.setattr(ml, "EVAL_DIR", str(tmp_path))
    src = tmp_path / "test_queries.json"
    src.write_text(json.dumps([{"queries": [{"query": "旧查询"}]}]), encoding="utf-8")
    assert "旧查询" in ml._known_eval_queries()

    src.write_text(json.dumps([{"queries": [{"query": "新查询"}]}]), encoding="utf-8")
    _reset_cache()
    qs = ml._known_eval_queries()
    assert "新查询" in qs and "旧查询" not in qs
