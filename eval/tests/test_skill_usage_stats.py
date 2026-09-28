#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""使用率采样的流量来源口径测试（对标轮六 D-33 / D-34）。

动机是先回测自己：7-A 缓存的收益取决于真实查询重复率，而回测 `route_trace.jsonl` 时发现
7,809 行里 **5,526 行（71%）是 adversarial/regression 测试自流量**。于是顺着这条线查消费方，
撞上两个度量效度漏洞：`skill_usage_stats`（主线⑥分母）与 `fenjue_measure` 的 D27 都不分来源——
后者更糟：只看"文件行数 ≥10"就加分，跑一次测试即白拿。所以本文件同时锁两处。

生产口径判定：production 2,283 次调用 / 162 个去重查询 ⇒ 精确命中 92.9%（这才是 7-A 的真实收益，
此前我保守地说"收益取决于重复率"是被自己的合成数据误导了）。
"""

import json
import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)
import skill_usage_stats as sus  # noqa: E402

TRACE = os.path.join(EVAL_DIR, "route_trace.jsonl")


def _rows(*pairs):
    return [{"src": s, "top1": t} for s, t in pairs]


def test_production_only_by_default():
    rows = _rows(("production", "a"), ("adversarial", "a"), ("regression", "b"))
    counter, excluded = sus.count_trace_rows(rows)
    assert dict(counter) == {"a": 1}
    assert dict(excluded) == {"adversarial": 1, "regression": 1}


def test_all_mode_includes_test_traffic():
    rows = _rows(("production", "a"), ("adversarial", "a"))
    counter, excluded = sus.count_trace_rows(rows, "all")
    assert counter["a"] == 2 and not excluded


def test_missing_src_counted_as_production():
    """缺 src 的旧行按 production 对待——宁可少排除，也不静默丢掉真实调用。"""
    counter, excluded = sus.count_trace_rows([{"top1": "x"}])
    assert counter["x"] == 1 and not excluded


def test_real_trace_source_split_is_measurable():
    """真实 trace 必须能按 src 拆开算命中率（这是 7-A 收益的唯一可信口径）。"""
    if not os.path.exists(TRACE):
        sys.stdout.write("(本机无 trace，跳过)")
        return
    by = {}
    for line in open(TRACE, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not d.get("q"):
            continue
        by.setdefault(d.get("src") or "production", []).append(d["q"].strip().casefold())
    assert by, "trace 有内容却按 src 归不出任何一组，说明口径假设已变"
    prod = by.get("production") or []
    if len(prod) >= 20:
        uniq = len(set(prod))
        assert uniq < len(prod), "production 查询全无重复 ⇒ 精确缓存无收益，7-A 需重估"


def test_fenjue_measure_d27_no_longer_counts_raw_lines():
    """D27 回归锁：'fenjue_measure' 的 trace 加分不得再看裸行数。"""
    src = open(os.path.join(os.path.dirname(EVAL_DIR), "audit", "fenjue_measure.py"),
               encoding="utf-8").read()
    assert "prod_lines" in src and "len(lines) >= 10" not in src, \
        "D27 退回行数判定 ⇒ 跑一次测试即白拿分（vacuous 指标回潮）"


def test_collect_llm_resolutions_records_span():
    """D-37：L3 决策日志没有 src，时间跨度是区分"现役残影"与"历史合法"的唯一线索。"""
    cnt, span = sus.collect_llm_resolutions([
        {"resolution": "skill-merge", "ts": "2026-08-11T03:00:02"},
        {"resolution": "skill-merge", "ts": "2026-08-05T22:59:05"},
        {"resolution": "live-skill", "ts": "2026-09-24T10:00:00"},
        {"resolution": "", "ts": "2026-09-24T10:00:00"},
        {"resolution": "no-ts-skill"},
    ])
    assert cnt == {"skill-merge": 2, "live-skill": 1, "no-ts-skill": 1}
    assert span["skill-merge"] == ("2026-08-05", "2026-08-11")
    assert "no-ts-skill" not in span and "" not in cnt


def test_ghost_source_never_blames_the_router_without_evidence():
    """端到端（真实数据）：每笔残影必须带来源；且"生产路由仍在送注册表外技能名"
    这件事只有当真出现时才允许被断言 —— 出现即 C30 看护面有洞（D-35 结论的回归锁）。"""
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert sus.main(["--json"]) == 0
    data = json.loads(buf.getvalue())
    assert any("分母按输入拆分" in d for d in data["disclosures"]), \
        "拆分口径的披露必须随产物同行（本机无 trace 数据时也要有这条）"
    assert set(data["per_source_calls"]) in ({"route_trace", "llm_decisions"},
                                             {"route_trace", "llm_decisions_archive"}), \
        "分母拆分口径消失（键名变了也判失效：拆不开就等于没拆）"
    for g in data["ghost_names"]:
        assert g["source"] in ("route_trace", "llm_decisions", "both"), g
        assert g["count"] > 0
    router_ghosts = [g for g in data["ghost_names"] if g["source"] in ("route_trace", "both")]
    for g in router_ghosts:
        assert not g["name"][0].islower(), (
            "生产路由 trace 供出了小写技能名且不在注册表 ⇒ 退役名仍在被送出，C30 有洞：%s" % g)


def test_newest_day_and_archive_flags():
    assert sus.newest_day([{"ts": "2026-08-05T01:02:03"}, {"ts": "2026-08-11T23:59:59"}]) == "2026-08-11"
    assert sus.newest_day([{"q": "x"}, {}]) == ""
    assert sus.is_archived("2026-08-11", "2026-09-25", 30) is True
    assert sus.is_archived("2026-09-20", "2026-09-25", 30) is False
    assert sus.is_archived("", "2026-09-25", 30) is True, "无日期信息必须保守判归档"


def _main_json(argv):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert sus.main(argv) == 0
    return json.loads(buf.getvalue())


def test_dead_input_is_out_of_the_live_denominator_but_still_audited():
    """D-38：`llm_decisions.jsonl` 实测停在 2026-08-11（被 route_trace 的 llm_decision 通道取代）。
    归档面不得再进"哪些技能该降级"的分母，但必须仍在残影审计里看得见。"""
    live = _main_json(["--json"])
    old = _main_json(["--json", "--include-archive"])
    assert "llm_decisions_archive" in live["per_source_calls"]
    # 两个输入文件都是 gitignored 的本机件（CI 上不存在）。缺面时不假装量到了日期，
    # 而是验"降级契约"：读不到就必须给出空面 + 仍判归档 + 行数 0（R247 不许 vacuous 判过）。
    has_llm = os.path.exists(os.path.join(EVAL_DIR, "llm_decisions.jsonl"))
    if has_llm:
        assert live["archived_inputs"]["llm_decisions"]["newest_ts_day"] == "2026-08-11"
    else:
        assert live["archived_inputs"]["llm_decisions"] == {
            "rows": 0, "newest_ts_day": "", "excluded_from_denominator": True,
            "after_days": live["archived_inputs"]["llm_decisions"]["after_days"]}, \
            "输入面缺失时的降级契约变了（既没测到东西也没保守排除）"
    if has_llm:   # 只有真有归档数据时，"排除使分母变小"才可测；无面时不做比较（不假装量到）
        assert live["total_calls"] < old["total_calls"], "--include-archive 应把归档行算回分母"
        assert live["skills_seen"] < old["skills_seen"], "死掉的历史面在凭空撑大已见过技能数"
        assert len(live["low_frequency_candidates"]) < len(old["low_frequency_candidates"]), \
            "归档输入不该继续制造降级候选"
    assert len(live["ghost_names"]) == len(old["ghost_names"]), "残影审计面不得随归档一起失明"
    assert all(g["source"] for g in live["ghost_names"])


def test_real_subchannels_are_not_mistaken_for_test_traffic():
    """D-38 续：排除判定用测试来源白名单。`llm_decision`（L3 消歧真实回写）与未知新来源
    一律保守计入——黑名单会把它们和 adversarial 混在一起静默掉出分母。"""
    rows = _rows(("production", "a"), ("llm_decision", "b"), ("manual-probe", "c"),
                 ("adversarial", "d"), ("regression", "e"))
    cnt, exc = sus.count_trace_rows(rows)
    assert set(cnt) == {"a", "b", "c"}, cnt
    assert dict(exc) == {"adversarial": 1, "regression": 1}
