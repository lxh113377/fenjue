#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_r214_fallback.py — R214-3 决策链 fallback 盲区补测（P0-1 实证零覆盖区）

覆盖:
  1. unified_router.classify_domain 不可达(=None, R212 删除内联兜底后的唯一降级路径)
     -> route() 不崩、结构完整、BGE/Tag 召回兜底, 与正常态对照
  2. bge_layer 不可达(FENJUE_BGE_DISABLE=1) -> TF-IDF 确定性降级, FALLBACK_USED 置位
  3. 双缺失(domain=None + BGE off) -> 最后一道防线, 结构仍完整
  4. route() 主链结构契约 + enable_llm 分支 + LLM 消歧联动
  5. normalize_query 同义词归一化
  6. C14 产物时效门禁单元(超期/缺失/正常) + verify checks 注册
  7. score_track200.score_line4 可判定口径回归(manual 不计分母, 防口径回退)
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unified_router as ur  # noqa: E402
import bge_layer  # noqa: E402
import score_track200  # noqa: E402
import verify_truth_consistency as vtc  # noqa: E402

_EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 召回资产是 gitignored 本机件（onnx 权重 eval/bge_onnx/、tfidf 索引 eval/tfidf_skill_ids.json），
# 干净签出/CI 上必然不在场 ⇒ 「兜底仍有召回」这一面**不可测**。P0-31：缺依赖即 skip 并写明理由，
# 禁止把「量具不在」跑成真缺陷红（同 D-41/D-45/C25 外盘降级口径）。
_RECALL_ASSETS = (os.path.isdir(os.path.join(_EVAL_DIR, 'bge_onnx', 'onnx'))
                  or os.path.isfile(os.path.join(_EVAL_DIR, 'tfidf_skill_ids.json')))
_needs_recall_assets = pytest.mark.skipif(
    not _RECALL_ASSETS,
    reason='召回资产（BGE onnx 权重 / TF-IDF 索引）为 gitignored 本机件，本环境不可测（P0-31）')

# 已探测: 直连不命中 + domain_classifier 词表命中 -> 可穿透 L0->召回全管线
PROBE_QUERY = "用 ffmpeg 转换音频格式"
PROBE_DOMAIN = "media"
# 直连不命中(词表外) -> domain=None 属正常路径(词表覆盖有限), 非降级
NO_DOMAIN_QUERY = "随机生成一个十六位长度的密码字符串组合"

ROUTE_KEYS = {"query", "domain", "tag_hits", "candidates", "top1",
              "llm_prompt", "needs_llm_decision", "llm_reason",
              "direct_hit", "confidence"}


# ---------------------------------------------------------------- L0 降级链
@_needs_recall_assets
def test_domain_classifier_none_route_still_works(monkeypatch):
    """R212 后 classify_domain=None 的降级路径: 不崩 + 结构完整 + 仍有召回。"""
    monkeypatch.setattr(ur, "classify_domain", None)
    r = ur.route(PROBE_QUERY)
    assert r["domain"] is None
    assert ROUTE_KEYS <= set(r)
    assert isinstance(r["candidates"], list) and r["candidates"], "BGE/Tag 兜底应有召回"


def test_domain_classifier_normal_vs_none_equivalence(monkeypatch):
    """正常态 domain=media; 降级态 domain=None 但均返回合法结构(降级≠故障)。"""
    r_ok = ur.route(PROBE_QUERY)
    assert r_ok["domain"] == PROBE_DOMAIN
    monkeypatch.setattr(ur, "classify_domain", None)
    r_degraded = ur.route(PROBE_QUERY)
    assert r_degraded["domain"] is None
    assert set(r_degraded) == set(r_ok), "降级路径不得缺字段"


# ---------------------------------------------------------------- BGE 降级链
@_needs_recall_assets
def test_bge_disabled_tfidf_fallback(monkeypatch):
    """FENJUE_BGE_DISABLE=1 -> bge_recall 走 TF-IDF 确定性降级并置位 FALLBACK_USED。"""
    monkeypatch.setenv("FENJUE_BGE_DISABLE", "1")
    monkeypatch.setattr(bge_layer, "FALLBACK_USED", False)
    r = ur.route(PROBE_QUERY)
    assert bge_layer.FALLBACK_USED is True
    assert isinstance(r["candidates"], list) and r["candidates"]


def test_dual_missing_last_line_of_defense(monkeypatch):
    """双缺失(classify_domain=None + BGE off) -> 最后一道防线仍返回完整结构。"""
    monkeypatch.setattr(ur, "classify_domain", None)
    monkeypatch.setenv("FENJUE_BGE_DISABLE", "1")
    monkeypatch.setattr(bge_layer, "FALLBACK_USED", False)
    r = ur.route(NO_DOMAIN_QUERY)
    assert ROUTE_KEYS <= set(r)
    assert r["domain"] is None


def test_bge_disabled_top1_still_skill_name(monkeypatch):
    """降级召回的 top1 仍是合法 skill 名(非崩溃占位/非空串)。"""
    monkeypatch.setenv("FENJUE_BGE_DISABLE", "1")
    monkeypatch.setattr(bge_layer, "FALLBACK_USED", False)
    r = ur.route(PROBE_QUERY)
    if r["candidates"]:
        assert isinstance(r["top1"], str) and r["top1"].strip()


# ---------------------------------------------------------------- route 主链
def test_route_structure_contract():
    """route() 返回结构契约(10 个必需字段, 类型断言)。"""
    r = ur.route(NO_DOMAIN_QUERY)
    assert ROUTE_KEYS <= set(r)
    assert isinstance(r["needs_llm_decision"], bool)
    assert isinstance(r["candidates"], list)
    assert r["direct_hit"] is False  # 该 query 已探测为直连不命中


def test_route_enable_llm_false_suppresses_llm(monkeypatch):
    """enable_llm=False: 即使判定器判 True 也不触发 LLM 消歧。

    _should_llm_decide 经 from-import 绑定进 unified_router 命名空间，
    必须 patch ur 侧绑定（patch llm_layer 无效）。
    """
    monkeypatch.setattr(ur, "_should_llm_decide", lambda *a, **k: (True, "unit"))
    r = ur.route(PROBE_QUERY, enable_llm=False)
    assert r["needs_llm_decision"] is False
    assert r["llm_prompt"] is None


def test_route_llm_decision_propagates(monkeypatch):
    """判定器判 True -> needs_llm_decision=True 且消歧 prompt 已构建。"""
    monkeypatch.setattr(ur, "_should_llm_decide", lambda *a, **k: (True, "unit-test"))
    monkeypatch.setattr(ur, "build_llm_decision_prompt",
                        lambda q, c: f"UNIT PROMPT for {q} x{len(c)}")
    r = ur.route(PROBE_QUERY, enable_llm=True)
    assert r["needs_llm_decision"] is True
    assert "unit-test" in (r["llm_reason"] or "")
    assert r["llm_prompt"].startswith("UNIT PROMPT")


def test_route_top_k_truncates():
    """top_k 截断候选列表长度。"""
    r = ur.route(NO_DOMAIN_QUERY, top_k=2)
    assert len(r["candidates"]) <= 2


# ---------------------------------------------------------------- normalize_query
def test_normalize_query_synonym_append():
    """命中同义词模式 -> 追加规范词且保留原文。"""
    q = ur.normalize_query("帮我捋顺一下这段代码")
    assert "refactor" in q and "捋顺" in q


def test_normalize_query_no_match_returns_original():
    """未命中同义词 -> 原样返回。"""
    q = "随机生成一个十六位长度的密码字符串组合"
    assert ur.normalize_query(q) == q


def test_normalize_query_case_insensitive():
    """同义词正则 IGNORECASE。"""
    q = ur.normalize_query("做个 KeyNote 简报")
    assert "ppt" in q.lower()


# ---------------------------------------------------------------- C14 门禁
def test_c14_registered_in_checks():
    """C14 已注册进 verify checks 列表（R213 新增，防门禁被悄悄移除）。"""
    import inspect
    src = inspect.getsource(vtc.main)
    assert "C14" in src and "check_c14_artifact_freshness" in src


def test_c14_stale_mtime_fails(tmp_path, monkeypatch):
    """mtime 超期 -> FAIL（自食其果验证）。"""
    import time
    stale = tmp_path / "STATUS.md"
    stale.write_text("x", encoding="utf-8")
    past = time.time() - 8 * 86400
    os.utime(stale, (past, past))
    fresh = tmp_path / "ci-blind-eval.json"
    fresh.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(vtc, "C14_WATCH", ("STATUS.md", "ci-blind-eval.json"))
    monkeypatch.setattr(vtc, "PROJECT_DIR", str(tmp_path))
    status, detail = vtc.check_c14_artifact_freshness()
    assert status == "FAIL" and "STATUS.md" in detail


def test_c14_missing_file_fails(tmp_path, monkeypatch):
    """关键产物缺失 -> FAIL。"""
    monkeypatch.setattr(vtc, "C14_WATCH", ("STATUS.md",))
    monkeypatch.setattr(vtc, "PROJECT_DIR", str(tmp_path))
    status, detail = vtc.check_c14_artifact_freshness()
    assert status == "FAIL" and "缺失" in detail


def test_c14_all_fresh_passes(tmp_path, monkeypatch):
    """全部产物新鲜 -> PASS。"""
    for name in ("STATUS.md", "STATUS.part1.md"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    monkeypatch.setattr(vtc, "C14_WATCH", ("STATUS.md", "STATUS.part1.md"))
    monkeypatch.setattr(vtc, "PROJECT_DIR", str(tmp_path))
    status, _ = vtc.check_c14_artifact_freshness()
    assert status == "PASS"


# ---------------------------------------------------------------- ④分母口径回归
def _fake_hitrate(hit, miss, manual):
    return {"total": hit + miss + manual, "hit": hit, "miss": miss, "manual": manual}


def test_score_line4_excludes_manual_from_denominator(monkeypatch):
    """R214-2 口径回归: manual(无目标文件)不计入分母, 12/13 != 12/17。"""
    monkeypatch.setattr(score_track200, "run_json",
                        lambda cmd: (_fake_hitrate(12, 1, 4), None))
    out = score_track200.score_line4()
    assert out["score"] == round(33 * 12 / 13, 1)
    assert "manual 4" in out["detail"] and "不计分母" in out["detail"]


def test_score_line4_all_manual_unavailable(monkeypatch):
    """全部 manual(可判定 0) -> unavailable=True, 不得除零。"""
    monkeypatch.setattr(score_track200, "run_json",
                        lambda cmd: (_fake_hitrate(0, 0, 17), None))
    out = score_track200.score_line4()
    assert out.get("unavailable") is True and out["score"] == 0.0
