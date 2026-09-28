#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路由结果跨进程缓存测试（对标轮四 7-A / D-19）。

立论依据是实测：各在役端每轮都是新进程，落 BGE 的查询稳定 ~1.53 s（约 95% 是模型
重复加载），直连命中仅 ~85 ms。缓存的价值与危险同源——**命中必须比计算快一个
数量级，且绝不能在索引重建后仍把旧结果（含已退役技能）供出去**。故失效正确性
（指纹/TTL/混合格式行）是本文件主体，提速只是顺带断言。
"""

import json
import os
import subprocess
import sys
import time

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)
import route_cache as rc  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每个用例独立缓存文件 + 固定指纹，防污染真实 eval/_cache/。"""
    monkeypatch.setattr(rc, "CACHE_PATH", str(tmp_path / "route_cache.jsonl"))
    monkeypatch.setattr(rc, "fingerprint", lambda: "fp-test")
    monkeypatch.delenv("FENJUE_ROUTE_CACHE", raising=False)
    yield


def _q():
    return "帮我把超市后台的商品表格加个导出按钮"


def test_store_then_lookup_roundtrip():
    key = rc.make_key(_q(), {"top_k": 5})
    assert rc.lookup(key) is None
    rc.store(key, {"top1": "chaoshi-admin-inline-edit", "candidates": []})
    got = rc.lookup(key)
    assert got is not None and got["top1"] == "chaoshi-admin-inline-edit"


def test_key_separates_query_and_flags():
    base = rc.make_key(_q(), {"top_k": 5})
    assert base != rc.make_key(_q(), {"top_k": 3})
    assert base != rc.make_key(_q(), {"top_k": 5, "enable_llm": False})
    assert base == rc.make_key("  " + _q() + " \n", {"top_k": 5})  # 规范化等价


def test_fingerprint_change_invalidates_all():
    """索引重建（指纹变）后旧缓存必须全部不可见——防把退役技能供出来。"""
    key = rc.make_key(_q(), {"top_k": 5})
    rc.store(key, {"top1": "stale"})
    assert rc.lookup(key)["top1"] == "stale"
    rc.fingerprint = lambda: "fp-rebuilt"
    assert rc.lookup(key) is None


def test_ttl_expired_entry_is_dropped(tmp_path, monkeypatch):
    key = rc.make_key(_q(), {"top_k": 5})
    rc.store(key, {"top1": "old"})
    path = rc.CACHE_PATH
    lines = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    lines[0]["ts"] = time.time() - (rc.TTL_SECONDS + 3600)
    with open(path, "w", encoding="utf-8") as f:
        for rec in lines:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    assert rc.lookup(key) is None


def test_malformed_and_foreign_lines_are_tolerated():
    """缓存文件是追加式多写入方产物，必须容忍坏行/BOM/非 JSON 行（R219d 族）。"""
    key = rc.make_key(_q(), {"top_k": 5})
    rc.store(key, {"top1": "ok"})
    with open(rc.CACHE_PATH, "a", encoding="utf-8") as f:
        f.write("this is not json\n")
        f.write("\n")
        f.write('{"fp": "other", broken\n')
    assert rc.lookup(key)["top1"] == "ok"


def test_env_disable_blocks_read_and_write(monkeypatch):
    monkeypatch.setenv("FENJUE_ROUTE_CACHE", "0")
    key = rc.make_key(_q(), {"top_k": 5})
    assert rc.enabled() is False
    rc.store(key, {"top1": "x"})
    assert not os.path.exists(rc.CACHE_PATH)


def test_env_override_cache_path(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere.jsonl"
    monkeypatch.setenv("FENJUE_ROUTE_CACHE_FILE", str(target))
    monkeypatch.setattr(rc, "CACHE_PATH", rc.cache_path())
    key = rc.make_key(_q(), {"top_k": 5})
    rc.store(key, {"top1": "y"})
    assert target.exists() and rc.lookup(key)["top1"] == "y"


def test_compaction_keeps_within_cap(monkeypatch):
    """增长有界（文档化不变量 ≤2×MAX，滞后带把重写摊销成 O(1)），且最新条目必存活。"""
    monkeypatch.setattr(rc, "MAX_ENTRIES", 5)
    for i in range(14):
        rc.store(rc.make_key("查询 %d" % i, {"top_k": 5}), {"top1": "s%d" % i})
    recs = [json.loads(l) for l in open(rc.CACHE_PATH, encoding="utf-8") if l.strip()]
    assert len(recs) <= rc.MAX_ENTRIES * 2, "缓存条目必须有界"
    assert len(recs) < 14, "未触发压缩"
    assert rc.lookup(rc.make_key("查询 13", {"top_k": 5}))["top1"] == "s13"


@pytest.mark.skipif(not os.path.exists(os.path.join(EVAL_DIR, "bge_fullbody_embeddings.npy")),
                    reason="BGE 索引产物不在本机（CI 最小环境）")
def test_cli_second_call_hits_cache(tmp_path):
    """集成面（**无负载依赖档**）：真实 CLI 两次同查询 —— 第二次必须走缓存且不改结果。

    D-67/D-76 归因结果（2026-09-25，钩子自查 `/tmp/fenjue_pch.log` 抓到真凶）：原用例把
    `ms2 < 150` 这条墙钟判据放在默认链里，而它会 spawn 两个 router 进程（BGE 加载受 CPU 争用
    支配）⇒ 机器空闲时过、并发时红 ⇒ "同一棵树直跑绿、提交上下文红"反复三轮。按 R-ENUM 的处置
    是**分档**而不是抬阈值（抬了等于把"我的机器刚好空"写进判据）。缓存收益的墙钟口径见
    integration 档 `test_cli_second_call_is_fast_under_load_free_machine`。
    """
    router = os.path.join(EVAL_DIR, "unified_router.py")
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               FENJUE_ROUTE_CACHE_FILE=str(tmp_path / "cli_cache.jsonl"))
    env.pop("FENJUE_ROUTE_CACHE", None)

    def _run():
        t0 = time.perf_counter()
        p = subprocess.run([sys.executable, router, "--json", _q()], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=env, timeout=180)
        return (time.perf_counter() - t0) * 1000, p

    ms1, p1 = _run()
    assert p1.returncode == 0, p1.stderr[-400:]
    out1 = json.loads(p1.stdout)
    ms2, p2 = _run()
    out2 = json.loads(p2.stdout)
    assert p2.returncode == 0 and out2.get("cached") is True
    assert out2["top1"] == out1["top1"], "缓存不得改变路由结果"


@pytest.mark.integration
@pytest.mark.timeout(420)
def test_cli_second_call_is_fast_under_load_free_machine(tmp_path):
    """性能断言（真实面档）：冷进程 spawn 受负载支配，只在显式开启时跑。

    两侧边界值（轮四实测）：未命中 1563 ms / 命中 71 ms（22×），判据取 150 ms 为该口径下的
    上界；在并发上下文里这一档**不可测**，故默认跳过。
    """
    if os.environ.get("FENJUE_RUN_INTEGRATION") != "1":
        pytest.skip("墙钟判据依赖机器负载（并发下必红），真实面档需显式开启 FENJUE_RUN_INTEGRATION=1")
    router = os.path.join(EVAL_DIR, "unified_router.py")
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               FENJUE_ROUTE_CACHE_FILE=str(tmp_path / "cli_cache2.jsonl"))
    env.pop("FENJUE_ROUTE_CACHE", None)
    subprocess.run([sys.executable, router, "--json", _q()], capture_output=True, env=env,
                   timeout=180)
    t0 = time.perf_counter()
    p = subprocess.run([sys.executable, router, "--json", _q()], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=180)
    ms = (time.perf_counter() - t0) * 1000
    assert p.returncode == 0 and json.loads(p.stdout).get("cached") is True
    assert ms < 150, "第二次调用 %.0f ms，未达轮四实测的 <150 ms 口径" % ms
