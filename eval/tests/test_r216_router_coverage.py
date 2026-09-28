#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R216: unified_router 覆盖率补测（R214-3 遗留：58% → ≥70%）。

主攻 R214-3 登记缺口：run_eval / _gzip_plain / _rotate_trace / _trace 关闭与异常分支 /
CLI --json(--llm-choice) 与普通输出 / watchdog 超时分支 / --timeout 非正数 /
RouteTimeout 非 json stderr / 正常返回收尾 / classify_domain ImportError 降级。
外部重依赖（BGE/LLM/直连表）一律 monkeypatch 打桩，保证确定性；
trace 落点重定向 tmp_path——遵守 R214-3 P0 教训：测试不得写生产 route_trace.jsonl。
"""
import gzip
import importlib
import json
import os
import sys

import pytest

import unified_router as ur  # noqa: E402


def _fake_candidates(score=0.5, name="A-skill-manager"):
    return [{"name": name, "score": score, "domain": "code", "boost": 0.0}]


@pytest.fixture()
def stub_pipeline(monkeypatch):
    """打桩全管线外部依赖：直连不命中、BGE 召回可控、memory/LLM 恒等、trace 静音。"""
    monkeypatch.setattr(ur, "direct_route", lambda q: None)
    monkeypatch.setattr(ur, "bge_recall",
                        lambda q, tag_hits, domain, top_k, raw_query=None:
                        _fake_candidates(score=0.50))
    monkeypatch.setattr(ur, "ensemble_rerank", lambda c, q: c)
    monkeypatch.setattr(ur, "memory_boost", lambda c, q: c)
    monkeypatch.setattr(ur, "_trace", lambda result: None)
    return ur


def test_medium_confidence_forces_llm(stub_pipeline, monkeypatch):
    """top1 ∈ [0.32,0.45) 且 _should_llm_decide=False → MEDIUM 档强制 LLM 消歧（R20）。"""
    monkeypatch.setattr(ur, "bge_recall", lambda *a, **k: _fake_candidates(score=0.40))
    monkeypatch.setattr(ur, "_should_llm_decide", lambda c, d, q: (False, "no"))
    monkeypatch.setattr(ur, "build_llm_decision_prompt", lambda q, c: {"full": "P"})
    r = ur.route("帮我看看这段代码", enable_memory=True, enable_llm=True)
    assert r["confidence"] == "MEDIUM"
    assert r["needs_llm_decision"] is True
    assert "MEDIUM置信" in r["llm_reason"]
    assert r["llm_prompt"] == {"full": "P"}


def test_gzip_plain_compress_and_dedupe(tmp_path):
    """_gzip_plain：明文→gz；明文与 gz 并存删明文；已是 gz 跳过。"""
    plain = tmp_path / "trace.2"
    plain.write_bytes(b"x" * 100)
    ur._gzip_plain(str(plain))
    assert not plain.exists() and (tmp_path / "trace.2.gz").exists()

    plain2 = tmp_path / "trace.3"
    (tmp_path / "trace.3.gz").write_bytes(b"z")
    plain2.write_bytes(b"y")
    ur._gzip_plain(str(plain2))
    assert not plain2.exists()
    assert (tmp_path / "trace.3.gz").read_bytes() == b"z"

    ur._gzip_plain(str(tmp_path / "trace.2.gz"))  # 已压缩：直接跳过不抛错


def test_gzip_plain_failure_swallowed(tmp_path, monkeypatch):
    plain = tmp_path / "trace.4"
    plain.write_bytes(b"x")

    def _boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(gzip, "open", _boom)
    ur._gzip_plain(str(plain))  # 压缩失败不影响调用方（异常吞掉）
    assert plain.exists()  # 明文保留


def test_rotate_trace_rotates_and_gzips(tmp_path, monkeypatch):
    """轮转 + .2~.5 压缩落位。

    D-51（对标轮七，跨平台真缺陷）：夹具原样写 `"{}\\n" * 3`（9 字节），而 Windows 文本模式把
    `\\n` 翻成 `\\r\\n` ⇒ 12 字节 ≥ 阈值 10 会轮转，Linux 保持 9 字节 < 10 **直接早退**，
    于是「本地绿、CI 红」。修法 = 显式 LF 写盘（两侧同为 9 字节）+ 阈值压到其下，
    让判据不再依赖宿主平台的换行翻译。
    """
    tr = tmp_path / "route_trace.jsonl"
    tr.write_text("{}\n" * 3, encoding="utf-8", newline="\n")
    for i in range(2, 6):
        (tmp_path / ("route_trace.jsonl.%d" % i)).write_text(
            "old\n", encoding="utf-8", newline="\n")
    monkeypatch.setattr(ur, "ROUTE_TRACE_PATH", str(tr))
    monkeypatch.setattr(ur, "_ROUTE_TRACE_MAX_BYTES", 5)
    assert tr.stat().st_size == 9, "夹具字节数必须平台无关，否则换行翻译会左右轮转阈值判定（D-51）"
    ur._rotate_trace()
    assert not tr.exists()                      # 主文件轮转落位 .2
    for i in range(2, 6):
        assert (tmp_path / ("route_trace.jsonl.%d.gz" % i)).exists()  # 全部压成 .gz
        assert not (tmp_path / ("route_trace.jsonl.%d" % i)).exists()


def test_rotate_trace_failure_swallowed(tmp_path, monkeypatch):
    tr = tmp_path / "route_trace.jsonl"
    tr.write_text("{}\n" * 3, encoding="utf-8")
    monkeypatch.setattr(ur, "ROUTE_TRACE_PATH", str(tr))
    monkeypatch.setattr(ur, "_ROUTE_TRACE_MAX_BYTES", 10)

    def _boom(a, b):
        raise OSError("replace fail")
    monkeypatch.setattr(os, "replace", _boom)
    ur._rotate_trace()  # 轮转失败不抛出（except pass）


def test_trace_disabled_returns_early(monkeypatch):
    monkeypatch.setattr(ur, "TRACE_ENABLED", False)
    ur._trace({"query": "q"})  # 直接 return，不写任何文件


def test_trace_exception_swallowed(tmp_path, monkeypatch):
    monkeypatch.setattr(ur, "TRACE_ENABLED", True)
    monkeypatch.setattr(ur, "ROUTE_TRACE_PATH", str(tmp_path / "t.jsonl"))

    def _boom():
        raise RuntimeError("rotate fail")
    monkeypatch.setattr(ur, "_rotate_trace", _boom)
    ur._trace({"query": "q", "top1": "x", "candidates": []})  # 异常吞掉不影响路由


def test_run_eval_counts_with_stubbed_route(tmp_path, monkeypatch):
    """run_eval 全管线统计：negative 剔除 / routable=False 剔除 / 直连与 LLM 计数 / 双口径。"""
    data = [
        {"tier": "negative", "queries": [{"query": "你好"}]},
        {"tier": "t1", "queries": [
            {"query": "q1", "expected_skill": "A-skill-manager", "routable": True},
            {"query": "q2", "expected_skill": ["fenjue-memory-audit"], "routable": False},
            {"query": "q3", "expected_skill": "fenjue-lessons-hitrate"},
        ]},
    ]
    p = tmp_path / "test_queries.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ur, "_load_bge", lambda: None)

    def fake_route(query, enable_memory=True, enable_llm=True, enable_tags=False, top_k=5):
        if enable_memory:
            hit = "A-skill-manager" if "q1" in query else "skill-X"
            return {"query": query, "top1": hit,
                    "candidates": [{"name": hit, "score": 0.9}],
                    "direct_hit": "q3" in query, "needs_llm_decision": "q1" in query}
        bge_top3 = ["A-skill-manager", "fenjue-lessons-hitrate"] if "q1" in query else ["skill-Y", "fenjue-lessons-hitrate"]
        return {"query": query,
                "top1": "A-skill-manager" if "q1" in query else "skill-Y",
                "candidates": [{"name": n, "score": 0.8} for n in bge_top3],
                "direct_hit": False, "needs_llm_decision": False}

    monkeypatch.setattr(ur, "route", fake_route)
    m = ur.run_eval(str(p))
    assert m["total"] == 2                       # q2 routable=False 被剔除
    assert m["direct_hits"] == 1 and m["llm_recommend"] == 1
    assert m["full_pipeline"]["correct"] == 1    # 仅 q1 命中
    assert m["bge_only"]["top3"] == 100.0        # q1/q3 的 Top-3 均含期望


def test_cli_json_llm_choice_trace(tmp_path, monkeypatch, capsys):
    """--json + --llm-choice：消歧回写 trace（llm_decision 源）+ 正常返回收尾（rc=0）。"""
    ttrace = tmp_path / "route_trace.jsonl"
    monkeypatch.setattr(ur, "ROUTE_TRACE_PATH", str(ttrace))
    monkeypatch.setenv("FENJUE_ROUTE_TRACE", "1")

    def fake_route(query, **kw):
        return {"query": query, "domain": "code", "top1": "A-skill-manager",
                "direct_hit": False, "needs_llm_decision": True,
                "llm_reason": "r", "candidates": _fake_candidates(),
                "llm_prompt": {"full": "PROMPT"}}

    monkeypatch.setattr(ur, "route", fake_route)
    rc = ur.cli_main(["--json", "--llm-choice", "fenjue-memory-audit", "测试查询"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["llm_choice"] == "fenjue-memory-audit"
    assert out["llm_agree"] is False and out["llm_corrected"] is True
    assert "llm_decision" in ttrace.read_text(encoding="utf-8")


def test_cli_plain_direct_and_llm_branches(monkeypatch, capsys):
    """普通 CLI 输出：直连命中分支 + 建议 LLM 消歧分支 + LLM 提示词打印。"""

    def fake_route(query, **kw):
        if "直连" in query:
            return {"query": query, "domain": None, "top1": "skill-D",
                    "direct_hit": True, "needs_llm_decision": False, "llm_reason": "",
                    "candidates": [{"name": "skill-D", "score": 1.0, "boost": 0.5}],
                    "llm_prompt": None}
        return {"query": query, "domain": "code", "top1": "A-skill-manager",
                "direct_hit": False, "needs_llm_decision": True, "llm_reason": "模糊",
                "candidates": [{"name": "A-skill-manager", "score": 0.4, "boost": 0.0}],
                "llm_prompt": {"full": "PROMPT"}}

    monkeypatch.setattr(ur, "route", fake_route)
    assert ur.cli_main(["直连测试"]) == 0
    assert "直连命中" in capsys.readouterr().out
    assert ur.cli_main(["模糊测试"]) == 0
    out2 = capsys.readouterr().out
    assert "建议LLM消歧" in out2 and "PROMPT" in out2


def test_watchdog_none_guard():
    assert ur._start_watchdog(None) == (None, None)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_watchdog_timeout_kills_via_exit(monkeypatch):
    """deadline 已过的 watchdog 走 stderr 告警 + os._exit(124)；patch 掉真杀进程。"""
    guard = ur.TimeoutGuard(-1.0)
    exited = {}

    def fake_exit(code):
        exited["code"] = code
        raise RuntimeError("os._exit(%s)" % code)
    monkeypatch.setattr(ur.os, "_exit", fake_exit)
    t, stop = ur._start_watchdog(guard)
    t.join(timeout=5)
    stop.set()
    assert exited.get("code") == 124


def test_parse_timeout_non_positive(capsys):
    assert ur._parse_timeout(["--timeout", "0"]) == (None, None)
    assert "--timeout 必须为正数" in capsys.readouterr().err


def test_cli_timeout_plain_stderr(monkeypatch, capsys):
    """非 --json 模式 RouteTimeout → stderr 提示 + 退出码 124。"""

    def boom():
        raise ur.RouteTimeout("route timeout after 0.01s")
    monkeypatch.setattr(ur, "_legacy_cli", boom)
    rc = ur.cli_main(["普通查询", "--timeout", "5"])
    assert rc == 124
    assert "TIMEOUT" in capsys.readouterr().err


def test_classify_domain_import_fallback():
    """R212 降级链：domain_classifier 导入失败 → classify_domain=None，路由继续可用。"""
    real = sys.modules.get("domain_classifier")
    sys.modules["domain_classifier"] = None
    try:
        importlib.reload(ur)
        assert ur.classify_domain is None
    finally:
        if real is not None:
            sys.modules["domain_classifier"] = real
        importlib.reload(ur)
    assert ur.classify_domain is not None
