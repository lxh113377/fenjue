#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""注入预算归因台账测试（对标轮四 7-E，治 D-22 / D-28）。

病灶实测：L1 注入硬预算的**消费面**在焚诀仓，**增长源**在 <SKILLS_ROOT> 仓，而该仓
`.git/hooks` 只有 post-commit 没有 pre-commit ⇒ 增长提交当时零校验；焚诀侧表现为
「我一个字没动，verify 从 28/28 变 29 PASS/1 FAIL」，且红因不可归因。
台账的作用是把「基线移动」从裸改常量变成**必须署名 + 必须给因 + 硬顶不得随迁**。
"""

import json
import os
import sys

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)
import inject_ledger as il  # noqa: E402
from verify_checks import governance_layer as gl  # noqa: E402

g_c31 = gl.check_c31_inject_ledger


def _rec(**kw):
    base = {"ts": "2026-09-24T19:02:00", "actor_repo": "global_skills", "actor_commit": "22990da",
            "cause": "A-memory-start V10.69.0 脏源检测条目入册，SKILL.md +1.6KB",
            "scope": "baseline_move", "delta_bytes": 3000, "baseline_before": 61472,
            "baseline_after": 64472, "hard_cap": 65536, "decision": "applied"}
    base.update(kw)
    return base


def test_empty_ledger_is_red_not_green(tmp_path):
    """空台账=「未初始化」而非「无违例」（R247：空面不得静默 PASS）。"""
    p = tmp_path / "ledger.jsonl"
    st, detail = il.validate([], baseline=61472, hard_cap=65536, ledger_path=str(p))
    assert st == "FAIL" and "未初始化" in detail


def test_applied_baseline_move_must_match_config():
    """基线只能经由台账移动：末条 applied 的 baseline_after != 常量即红（防裸改）。"""
    recs = [_rec(baseline_after=61472)]
    st, detail = il.validate(recs, baseline=64472, hard_cap=65536, ledger_path="x")
    assert st == "FAIL" and "裸改" in detail
    assert il.validate([_rec()], baseline=64472, hard_cap=65536, ledger_path="x")[0] == "PASS"


def test_applied_entry_requires_attribution():
    """无 commit / 无因由 = 不给过——杜绝「静默洗白」这条路存在。"""
    for bad in (_rec(actor_commit=""), _rec(cause="短"), _rec(actor_repo="")):
        st, detail = il.validate([bad], baseline=64472, hard_cap=65536, ledger_path="x")
        assert st == "FAIL", bad


def test_hard_cap_can_never_rise():
    """硬顶是天花板：台账里出现比初值更高的 hard_cap 即红（防"基线失控"改走"上限失控"）。"""
    st, detail = il.validate([_rec(hard_cap=70000)], baseline=64472, hard_cap=65536,
                             ledger_path="x", initial_hard_cap=65536)
    assert st == "FAIL" and "硬顶" in detail


def test_pending_entries_warn_without_faking_green():
    """待裁决条目必须显式出现在明细里（阻塞要可见，不能被"绿"吞掉）。"""
    recs = [_rec(), _rec(decision="pending", cause="增长方需瘦身或 owner 重标基线（当前阻塞提交）")]
    st, detail = il.validate(recs, baseline=64472, hard_cap=65536, ledger_path="x")
    assert st == "PASS" and "待裁决 1" in detail


def test_malformed_lines_tolerated_and_counted(tmp_path):
    p = tmp_path / "ledger.jsonl"
    p.write_text("not json\n\n" + json.dumps(_rec()) + "\n", encoding="utf-8")
    recs = il.load(str(p))
    assert len(recs) == 1 and recs[0]["decision"] == "applied"


def test_append_refuses_unattributed_move(tmp_path):
    p = str(tmp_path / "ledger.jsonl")
    with pytest.raises(ValueError):
        il.append_entry(p, {"baseline_after": 64472, "decision": "applied", "cause": "x" * 30})
    il.append_entry(p, _rec())
    assert len(il.load(p)) == 1


def test_headroom_warning_below_five_percent():
    st, detail = il.validate([_rec()], baseline=64472, hard_cap=65536, ledger_path="x",
                             measured_total=64472)
    assert st == "PASS" and "余量" in detail and "⚠" in detail


def test_pending_before_a_later_applied_is_closed():
    """台账是追加式的：applied 之后不再报它之前那条 pending（否则裁决永远挂着）。"""
    recs = [_rec(decision="pending", cause="增长事件待裁决：外仓发布顶破基线 +3000 字节"),
            _rec(decision="applied", baseline_after=64472, cause="owner 废除签批门后经台账移动基线")]
    st, detail = il.validate(recs, baseline=64472, hard_cap=65536, ledger_path="x")
    assert st == "PASS" and "待裁决" not in detail and "pending=1" in detail


def test_absorbed_conclusion_also_closes_pending():
    """增长被瘦身消化（absorbed，基线不动）同样是处置结论，须关闭其前的 pending。"""
    recs = [_rec(),
            _rec(decision="pending", baseline_after=0, cause="注入区被外仓发布顶破 +3000B 待处置"),
            _rec(decision="absorbed", baseline_after=64472,
                 cause="增长方自行瘦身 + 治理仓壳文件去重，总量已回到基线以下，基线未动")]
    st, detail = il.validate(recs, baseline=64472, hard_cap=65536, ledger_path="x")
    assert st == "PASS" and "待裁决" not in detail and "pending=1" in detail


def _actor_verifiable():
    """署名核验在本机是否**真的可用**（D-41：CI 上外仓不在/浅克隆，取不到提交属"不可核验"分支，
    测试若把"可核验"当默认环境，就会在干净签出上假红——判据本身没错，是断言假设了机器）。"""
    return il.commit_touches_injection("global_memory", "b755ebc") is False


def test_c31_is_cwd_independent(tmp_path, monkeypatch):
    """回归：C31 曾在别的仓（GM 提交时 cwd=<MEMORY_ROOT>）把相对路径
    `AGENTS.md` 判成「文件缺失」⇒ 新装的闸自己弄坏了别人的提交链。
    判据面必须锚在治理仓根，绝不随 cwd 漂移（C25 同口径）。"""
    monkeypatch.chdir(tmp_path)
    st, detail = g_c31(skip_external=True)
    assert st in ("PASS", "SKIP"), "换 cwd 后 C31 漂移: %s" % detail


def test_actor_commit_relevance_is_verifiable():
    """W4 的存在理由（实测）：一笔 applied 移动基线时引了 `b755ebc`——那提交只改了
    memory/2026-09-24.md（+27 行日志），与注入预算毫无关系。**非空署名 ≠ 相关署名**。
    取真仓真提交做判据自证，不用假 hash（假 hash 只会测到「取不到」分支）。"""
    if not os.path.isdir(il.ACTOR_REPO_DIRS["global_memory"]):
        pytest.skip("global_memory 不在本机")
    if not _actor_verifiable():
        pytest.skip("外仓不可核验（浅克隆/异机/CI）⇒ 本例只在本机成立，见 W4 两分支测试")
    assert il.commit_touches_injection("global_memory", "b755ebc") is False
    assert il.commit_touches_injection("global_skills", "928517a") is True
    assert il.commit_touches_injection("global_skills", "928517a+5819b47") is None  # 复合标注不判定


def test_w4_blocks_irrelevant_effective_entry():
    """W4 两分支都要覆盖：可核验 ⇒ 生效条硬拦；不可核验（CI/异机/浅克隆）⇒ 只 ⚠ 不红，
    绝不把"取不到提交"当成"违规"，也不能当成"通过"而不吭声。"""
    bad = _rec(actor_repo="global_memory", actor_commit="b755ebc")
    if _actor_verifiable():
        st, detail = il.validate([bad], baseline=bad["baseline_after"], hard_cap=65536,
                                 ledger_path="x", verify_actor=True)
        assert st == "FAIL" and "W4" in detail
    else:
        st, detail = il.validate([bad], baseline=bad["baseline_after"], hard_cap=65536,
                                 ledger_path="x", verify_actor=True)
        assert st == "PASS" and "不可核验" in detail, \
            "环境取不到署名提交时必须走不可核验分支，不得静默判过：%s" % detail
    # 关掉核验（异机/浅克隆）必须回到 PASS，不得把"无法核验"当成"违规"
    assert il.validate([bad], baseline=bad["baseline_after"], hard_cap=65536,
                       ledger_path="x", verify_actor=False)[0] == "PASS"


def test_w4_does_not_retroactively_redden_history():
    """历史误标只 ⚠ 不红：只有**生效**那条硬拦，否则每加一条新规则就把昨天的自己判红。"""
    bad = _rec(actor_repo="global_memory", actor_commit="b755ebc")
    good = _rec(actor_repo="global_skills", actor_commit="928517a")  # 末条=生效
    st, detail = il.validate([bad, good], baseline=good["baseline_after"], hard_cap=65536,
                             ledger_path="x", verify_actor=True)
    assert st == "PASS", detail
    assert "不可核验" in detail or "历史" in detail, detail   # 两条路径都必须吭一声
    if _actor_verifiable():
        assert "历史 applied 署名与注入面无涉" in detail, detail


def test_applied_rejects_non_sha_actor(tmp_path):
    """机制根治 P0-21：台账实测出现过 actor_commit="HEAD"，那种署名在校验时点指向任意提交，
    等于没有署名。--record 侧直接拒收，不留"先记账再人工认"的口子。"""
    for bad in ("HEAD", "main", "在途未提交"):
        with pytest.raises(ValueError):
            il.append_entry(str(tmp_path / "l.jsonl"),
                            _rec(actor_commit=bad, baseline_after=64472,
                                 cause="必要增长，但署名写成了分支名"))
    il.append_entry(str(tmp_path / "l.jsonl"),
                    _rec(actor_commit="6167c7b+928517a", baseline_after=64472,
                         cause="复合标注两个真实 sha 应放行"))


def test_c31_registered_in_verify_and_wired():
    """新判据必须真进注册表与消费面（R278 同族：只写函数不接线=假保险）。"""
    src = open(os.path.join(EVAL_DIR, "verify_truth_consistency.py"), encoding="utf-8").read()
    assert "check_c31_inject_ledger" in src, "C31 未注册进 verify 判据面"
    assert "'check_c31_inject_ledger': 'governance_layer'" in src, "C31 未登记 _CHECK_HOME"
    stub = open(os.path.join(EVAL_DIR, "stubs", "registry.json"), encoding="utf-8").read()
    assert "C31" in stub, "新判据未补隔离桩（R272 交付契约）"
