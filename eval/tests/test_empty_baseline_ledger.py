#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""空基线台账测试（对标轮四 7-C / C32）。

要杀的是第三种假绿：**文件是空的，于是"没有违例"和"根本没扫"长得一模一样**。
所以判据的全部力量落在"空面必须自证扫过什么/多少/何时"，而测试的全部力量落在
"每一条登记要求都能被绕过式地证伪"——尤其 `scanned_units` 与实扫面的双向对账。
"""

import copy
import json
import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)
import empty_baseline_ledger as eb  # noqa: E402

TODAY = "2026-09-24"
STATE = [{"id": "t1", "path": "a.json", "kind": "dict", "present": True, "empty": True, "units": 200},
         {"id": "t2", "path": "b.json", "kind": "list", "present": True, "empty": False, "units": 44}]
ENTRY = {"id": "t1", "scanned_units": 200, "surface": "scan_dirs_py_files",
         "at": TODAY, "note": "ruff 扫 eval/scripts/audit/feedback 四面"}


def _j(entries, state=None, today=TODAY):
    return eb.judge(state or STATE, entries, today=today)


def test_empty_without_entry_is_red():
    st, detail = _j({})
    assert st == "FAIL" and "未登记" in detail


def test_nonempty_face_needs_no_entry():
    state = [s for s in copy.deepcopy(STATE) if s["id"] == "t2"]
    assert _j({}, state=state)[0] == "PASS"


def test_zero_scanned_units_is_red():
    e = dict(ENTRY, scanned_units=0)
    assert "非正数" in _j({"t1": e})[1]


def test_overstated_units_vs_live_surface_is_red():
    """登记的扫描面**超过**当前实扫面 = 虚报或口径漂移，也必须红（只查下界会放过吹牛）。"""
    e = dict(ENTRY, scanned_units=9999)
    st, detail = _j({"t1": e})
    assert st == "FAIL" and "超当前实扫面" in detail


def test_stale_registration_is_red():
    e = dict(ENTRY, at="2025-01-01")
    assert "过期" in _j({"t1": e})[1]


def test_bad_date_is_red():
    assert "ISO" in _j({"t1": dict(ENTRY, at="昨天")})[1]


def test_counter_face_requires_next_due():
    state = [{"id": "t3", "path": "c.json", "kind": "counter", "present": True, "empty": True,
              "units": 30}]
    e = dict(ENTRY, id="t3", scanned_units=30)
    assert "next_due" in _j({"t3": e}, state=state)[1]
    assert _j({"t3": dict(e, next_due="2026-12-31")}, state=state)[0] == "PASS"


def test_layered_surface_counts_cases_not_tiers():
    """回归：layered_testset 是 5 个分层组，取「组数」会把面写小 58 倍（实测 5 vs 291）。
    面口径写小 = 允许把 291 题的轮换登记成 5，等于给 vacuous pass 开后门。"""
    units = eb.surface_units({"surface": "layered_testset"})
    data = eb._read_json("layered_testset.json")
    assert len(data) < units, "只数到了分层组数，没数到用例数"
    assert units >= 200, "分层题集真实用例数应在 291 量级，实得 %d" % units


def test_missing_surface_field_is_red():
    assert "surface" in _j({"t1": dict(ENTRY, surface="")})[1]


def test_missing_baseline_file_is_red():
    state = [{"id": "t4", "path": "gone.json", "kind": "dict", "present": False, "empty": True,
              "units": 5}]
    assert "缺失" in _j({}, state=state)[1]


def test_init_then_check_passes_on_real_surface(tmp_path):
    """集成面：对真实三面 --init 采集后必须自查通过（否则登记器本身是空的）。

    `scanned_units > 0` 只在**该面可测**时断言：三面之一（llm-failure-cases）的实扫源是
    gitignored 的本机件，CI 上根本不存在 ⇒ units=0。不可测面不得被假装"量到了"，
    但必须被 judge 容忍（不得反过来判成虚报），这正是下面 check(path) 要过的路。
    """
    path = str(tmp_path / "ledger.json")
    payload = eb.init_ledger(path=path, next_due="2026-12-31")
    assert payload["entries"], "真实盘面一个空面都没登记 = 采集器没在工作"
    state = {st["id"]: st for st in eb.collect_state()}
    measurable = [e["id"] for e in payload["entries"] if state[e["id"]]["units"] > 0]
    assert measurable, "三面全部不可测 = 采集器没在工作"
    for e in payload["entries"]:
        if state[e["id"]]["units"] > 0:
            assert e["scanned_units"] > 0, e
    st, detail = eb.check(path, skip_external=True)
    unmeasurable = [e["id"] for e in payload["entries"] if state[e["id"]]["units"] <= 0]
    if unmeasurable:
        # 数据源缺失却仍被登记成 0 ⇒ "采集结果"自查不过本来就对（init ≠ 登记）。
        assert st == "FAIL" and all(u in detail for u in unmeasurable), detail
    else:
        # 三面皆登记在册（或不可达被跳过）；不可达不得把判据变成 CI 假红（D-41）。
        assert st == "PASS", detail
    committed = eb.check(skip_external=True)
    assert committed[0] in ("PASS", "SKIP"), \
        "已提交台账在 CI 语义下假红：%s" % committed[1]


def test_skip_external_only_frees_truly_unreachable_faces():
    """D-41 的反逃生门锁：只有"基线与数据源同时不在"才可跳过；
    源在而登记缺失（真正要杀的 vacuous 情形）在任何环境下都必须判红。"""
    a = {"id": "ghost-face", "path": "p.json", "kind": "list", "present": False,
         "source_present": False, "empty": True, "units": 0}
    b = {"id": "lazy-face", "path": "q.json", "kind": "list", "present": False,
         "source_present": True, "empty": True, "units": 5}
    st, detail = eb.judge([a], {}, skip_external=True)
    assert st == "SKIP" and "不可达" in detail, detail
    st, detail = eb.judge([b], {}, skip_external=True)
    assert st == "FAIL" and "基线文件缺失" in detail, "改环境标记就能绕过登记 ⇒ 判据被掏空"
    st, _ = eb.judge([a], {}, skip_external=False)
    assert st == "FAIL", "本机环境下不可达面仍须 fail-closed"


def test_targets_cover_the_three_known_empty_baselines():
    """三处 vacuous pass 必须都在受管清单里（漏一个就是本轮 6-B 没做完）。

    D-41 换锁法：原先在此断言"三个基线文件都存在于磁盘"——但 `llm_failure_cases.json`
    是 gitignored 的派生件（R162.1），CI 上本就不该存在，那条断言把"面不可达"误当缺陷。
    改锁**清单与实扫面一一对应 + 每面必须声明数据源**（源缺失才可判不可达）。
    """
    ids = {t["id"] for t in eb.TARGETS}
    assert ids == {"style-ratchet", "llm-failure-cases", "blindset-rotation"}
    for t in eb.TARGETS:
        assert t.get("source"), "%s 未声明数据源 ⇒ CI 上无法区分不可达与漏登记" % t["id"]
    assert {st["id"] for st in eb.collect_state()} == ids, "采集面与清单漂移"
    assert sum(1 for st in eb.collect_state() if st["source_present"]) >= 2, \
        "三面里至少两面在本环境可测（全不可测＝采集器本身失联，判据面消失）"


def test_c32_registered_and_stubbed():
    src = open(os.path.join(EVAL_DIR, "verify_truth_consistency.py"), encoding="utf-8").read()
    assert "check_c32_empty_baseline_ledger" in src, "C32 未注册进 verify"
    assert "'check_c32_empty_baseline_ledger': 'governance_layer'" in src, "C32 未登记 _CHECK_HOME"
    stub = open(os.path.join(EVAL_DIR, "stubs", "registry.json"), encoding="utf-8").read()
    assert "C32" in stub, "新判据未补隔离桩（R272 交付契约）"
    json.loads(stub)  # 登记表必须是合法 JSON（R271 字符串批量替换曾打烂过它）
