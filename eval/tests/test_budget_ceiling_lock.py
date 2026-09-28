# -*- coding: utf-8 -*-
"""budget_ceiling_lock 隔离桩（对标轮九 D-63）——四向判别，防"基线记错方向"式假通过。"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'eval'))

import budget_ceiling_lock as b  # noqa: E402


def test_pytest_ceiling_is_read_from_config(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text('addopts = "-q --timeout=120"', encoding="utf-8")
    assert b.pytest_ceiling(str(p)) == 120


def test_missing_ceiling_is_fast_fail_not_silence(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text('addopts = "-q"', encoding="utf-8")
    try:
        b.pytest_ceiling(str(p))
        raise AssertionError("天花板缺失必须抛错（L2）")
    except ValueError:
        pass


def test_over_budget_violation_and_compliant_pass():
    assert b.judge([("a.py", 3, 900)], 120)["violations"]
    assert b.judge([("a.py", 3, 60)], 120)["verdict"] == "PASS"


def test_empty_face_fails_r247():
    res = b.judge([], 120)
    assert res["verdict"] == "FAIL-FAST" and "R247" in res["reason"]


def test_granfather_only_covers_registered_line_and_budget():
    base = {"grandfathered": {"a.py": {"max_line": 3, "max_budget": 900}}}
    assert b.judge([("a.py", 3, 900)], 120, base)["verdict"] == "PASS"
    assert b.judge([("a.py", 9, 990)], 120, base)["violations"], "未登记的越界必须红"


def test_baseline_aggregates_true_max_per_file(tmp_path, monkeypatch):
    """同文件多处越界：基线必须记真最大值（首版 last-wins 把 600 记成 300，反咬存量自己）。"""
    monkeypatch.setattr(b, "ROOT", str(tmp_path))
    monkeypatch.setattr(b, "BASELINE", str(tmp_path / "bl.json"))
    src = tmp_path / "eval" / "m.py"
    src.parent.mkdir()
    src.write_text("import subprocess\n"
                   "subprocess.run(['x'], timeout=600)\n"
                   "subprocess.run(['y'], timeout=300)\n", encoding="utf-8")
    monkeypatch.setattr(b, "pytest_ceiling", lambda: 120)
    assert b.main(["--update-baseline"]) == 0
    data = json.load(open(b.BASELINE, encoding="utf-8"))
    # D-104：基线条目必须带 violations 条数；行号退化为"展示用"，不再参与判定
    assert data["grandfathered"]["eval/m.py"] == {"max_line": 3, "max_budget": 600,
                                                  "violations": 2}
    assert b.main([]) == 0, "存量登记后应判绿"


def test_scan_uses_ast_not_prose(tmp_path):
    """文档串/注释里写的 `timeout=…` 不算预算（首版正则误报，实测 11 条里混 1 条假阳性）。"""
    mod = tmp_path / "eval" / "prose.py"
    mod.parent.mkdir()
    mod.write_text('"""\u8bf4\u660e subprocess(timeout=180) \u662f\u53d9\u8ff0"""\n', encoding="utf-8")
    monkey_root = str(tmp_path)
    assert [h for h in b.scan(monkey_root) if h[0].endswith("prose.py")] == []


# ---- D-104（对标轮十七续）：行号不得当棘轮坐标 ----
# 一手实测：本轮 3 条"越界"（scripts/run_gate.py:85 1800s、cross_writer_idempotence.py:221 900s、
# stubs/stub_secret_scan.py:25 300s）预算与基线记的一字不差，只因别人在它们上方插了几行注释
# ⇒ 旧口径 `line <= max_line` 不成立 ⇒ 判红。假越界的代价是真越界永远排不进队。

def _rec(violations=1, max_budget=900, max_line=3):
    return {"grandfathered": {"a.py": {"max_line": max_line, "max_budget": max_budget,
                                       "violations": violations}}}


def test_line_drift_within_recorded_budget_is_green():
    """回归锁：上方插行让 line 漂到 9999，只要预算与条数没变就必须绿。"""
    assert b.judge([("a.py", 9999, 900)], 120, _rec())["verdict"] == "PASS"


def test_raising_budget_above_recorded_tier_is_red():
    v = b.judge([("a.py", 3, 901)], 120, _rec())
    assert v["verdict"] == "FAIL" and v["violations"][0]["why"] == "预算超基线档位"


def test_adding_second_violating_site_beyond_recorded_count_is_red():
    """同文件多一个越界点 = 新增债务，即便档位没变也要红（只降不升）。"""
    v = b.judge([("a.py", 3, 900), ("a.py", 88, 300)], 120, _rec(violations=1))
    assert v["verdict"] == "FAIL"
    assert [x["line"] for x in v["violations"]] == [88], "豁免要给最坏的那条，不能挑软的"


def test_more_recorded_sites_are_all_exempted_by_count():
    sites = [("a.py", 1, 1800), ("a.py", 2, 900), ("a.py", 3, 600)]
    assert b.judge(sites, 120, _rec(violations=3, max_budget=1800))["verdict"] == "PASS"
    assert b.judge(sites, 120, _rec(violations=2, max_budget=1800))["verdict"] == "FAIL"


def test_shrinking_debt_is_always_green():
    """收口方向永不判红：条数从 2 降到 1、档位从 1800 降到 900 都绿。"""
    assert b.judge([("a.py", 7, 900)], 120, _rec(violations=2, max_budget=1800))["verdict"] == "PASS"


def test_file_never_registered_is_red_with_reason():
    v = b.judge([("new.py", 5, 300)], 120, _rec())
    assert v["verdict"] == "FAIL" and v["violations"][0]["why"] == "该文件从未登记豁免"


def test_legacy_baseline_without_violations_field_still_works():
    """向后兼容：老基线只有 max_line/max_budget 时按「每文件一条豁免」处理，不误放不误杀。"""
    legacy = {"grandfathered": {"a.py": {"max_line": 3, "max_budget": 900}}}
    assert b.judge([("a.py", 42, 900)], 120, legacy)["verdict"] == "PASS"
    assert b.judge([("a.py", 42, 900), ("a.py", 43, 900)], 120, legacy)["verdict"] == "FAIL"


def test_update_baseline_records_violation_counts(tmp_path, monkeypatch):
    """写基线必须带上条数，否则下一轮又退回行号坐标。"""
    monkeypatch.setattr(b, "ROOT", str(tmp_path))
    monkeypatch.setattr(b, "BASELINE", str(tmp_path / "bl.json"))
    src = tmp_path / "eval" / "m.py"
    src.parent.mkdir()
    src.write_text("import subprocess\nsubprocess.run(['x'], timeout=900)\n"
                   "subprocess.run(['y'], timeout=1800)\n"
                   "subprocess.run(['z'], timeout=30)\n", encoding="utf-8")
    monkeypatch.setattr(b, "pytest_ceiling", lambda: 120)
    monkeypatch.setattr(sys, "argv", ["budget_ceiling_lock.py", "--update-baseline"])
    assert b.main() == 0
    data = json.load(open(tmp_path / "bl.json", encoding="utf-8"))
    rec = data["grandfathered"]["eval/m.py"]
    assert rec["violations"] == 2 and rec["max_budget"] == 1800
