# -*- coding: utf-8 -*-
"""skill_registry_consistency.py 的两向对照测试（轮十八追加轮 D-124：CI 在用却 0% 覆盖）。"""
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "eval"))

import skill_registry_consistency as src  # noqa: E402


def _face(tmp_path, name, n, extra_fields=None):
    body = {}
    for i in range(n):
        e = {"domain": "code"}
        if extra_fields:
            e.update(extra_fields(i))
        body["s%03d" % i] = e
    p = tmp_path / name
    io.open(str(p), "w", encoding="utf-8").write(
        json.dumps({"skills": body}, ensure_ascii=False))
    return str(p)


def _wire(tmp_path, reg, cpm, monkeypatch):
    monkeypatch.setattr(src, "REG", reg)
    monkeypatch.setattr(src, "CPM", cpm)
    monkeypatch.setattr(src, "TRUTH", str(tmp_path / "no-truth.json"))


def test_empty_face_is_fail_fast_not_pass(tmp_path, monkeypatch, capsys):
    """本次修的就是这条：`{"skills": {}}` 曾打印「结论: PASS」并以 0 退出。"""
    reg = _face(tmp_path, "reg.json", 30)
    io.open(reg, "w", encoding="utf-8").write(json.dumps({"skills": {}}))
    _wire(tmp_path, reg, _face(tmp_path, "cpm.json", 30), monkeypatch)
    assert src.main([]) == 2
    out = capsys.readouterr().out
    assert "FAIL-FAST" in out and "零违规" in out and "结论: PASS" not in out


def test_face_below_floor_is_fail_fast(tmp_path, monkeypatch, capsys):
    """截断成 5 条也不能过关：下限是常量，不是"本次读到多少就算多少"。"""
    _wire(tmp_path, _face(tmp_path, "reg.json", 5), _face(tmp_path, "cpm.json", 5), monkeypatch)
    assert src.main([]) == 2
    assert "低于面下限" in capsys.readouterr().out


def test_corrupt_json_fails_fast_instead_of_traceback(tmp_path, monkeypatch, capsys):
    reg = str(tmp_path / "bad.json")
    io.open(reg, "w", encoding="utf-8").write("{这不是 JSON")
    _wire(tmp_path, reg, _face(tmp_path, "cpm.json", 30), monkeypatch)
    rc = src.main([])                      # 旧实现直接抛 JSONDecodeError（不可归因）
    assert rc == 2
    msg = capsys.readouterr().out
    assert "不可解析" in msg and "bad.json" in msg


def test_wrong_shape_is_fail_fast(tmp_path, monkeypatch, capsys):
    reg = str(tmp_path / "list.json")
    io.open(reg, "w", encoding="utf-8").write(json.dumps({"skills": ["a", "b"]}))
    _wire(tmp_path, reg, _face(tmp_path, "cpm.json", 30), monkeypatch)
    assert src.main([]) == 2
    assert "类型不对" in capsys.readouterr().out


def test_half_registered_is_red(tmp_path, monkeypatch, capsys):
    reg = _face(tmp_path, "reg.json", 31)          # s030 只在注册表里
    _wire(tmp_path, reg, _face(tmp_path, "cpm.json", 30), monkeypatch)
    assert src.main([]) == 1
    out = capsys.readouterr().out
    assert "半登记" in out and "s030" in out


def test_missing_domain_is_red(tmp_path, monkeypatch, capsys):
    reg = str(tmp_path / "regnd.json")
    io.open(reg, "w", encoding="utf-8").write(json.dumps({"skills": {
        "s%03d" % i: ({"domain": ""} if i == 3 else {"domain": "code"}) for i in range(30)}}))
    _wire(tmp_path, reg, _face(tmp_path, "cpm.json", 30), monkeypatch)
    assert src.main([]) == 1
    assert "缺 domain" in capsys.readouterr().out


def test_cpm_extra_is_informational(tmp_path, monkeypatch, capsys):
    """cpm 多出项是台账历史，只提示不判红（docstring 第 3 条）。"""
    _wire(tmp_path, _face(tmp_path, "reg.json", 30), _face(tmp_path, "cpm.json", 33), monkeypatch)
    assert src.main([]) == 0
    out = capsys.readouterr().out
    assert "cpm 历史多出 3 条" in out


def test_clean_face_is_green_both_output_modes(tmp_path, monkeypatch, capsys):
    f = _face(tmp_path, "reg.json", 30)
    _wire(tmp_path, f, f, monkeypatch)
    assert src.main([]) == 0
    assert "结论: PASS" in capsys.readouterr().out
    assert src.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["all_pass"] is True


def test_json_mode_reports_fail_fast_verdict(tmp_path, monkeypatch, capsys):
    reg = str(tmp_path / "reg.json")
    io.open(reg, "w", encoding="utf-8").write(json.dumps({"skills": {}}))
    _wire(tmp_path, reg, _face(tmp_path, "cpm.json", 30), monkeypatch)
    assert src.main(["--json"]) == 2
    assert json.loads(capsys.readouterr().out)["verdict"] == "FAIL-FAST"


def test_real_repo_face_is_green_and_well_above_floor():
    """现网面：167 条量级，远低于下限说明面被写坏 —— 这条同时是 CI 绿的本地复现。"""
    reg, err_reg = src.load_face(src.REG)
    cpm, err_cpm = src.load_face(src.CPM)
    assert err_reg is None and err_cpm is None
    assert len(reg) >= src.MIN_FACE and len(cpm) >= src.MIN_FACE
    assert src.main([]) == 0
