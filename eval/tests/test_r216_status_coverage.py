#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R216: status_report 覆盖率补测（R214-3 遗留：45% → ≥60%）。

主攻 R214-3 登记缺口：v2 评分卡渲染、three_door 审计+台账联动降级（超期/逃生门/阻断）、
无评分卡回退段、主线④⑤⑥/跨端终检/开场预读块、registry 异常路径、写盘路径与孤儿 part 告警、
track_150 PASS_LINE 分支。全部 dry_run 或写盘到 tmp_path，不触碰真实 STATUS.md。
"""
import importlib
import json

import status_report as sr  # noqa: E402


def _v2_scorecard(**over):
    """fenjue-scorecard-v2 夹具：只带两条 line（第三维走「暂无数据」分支）。"""
    sc = {
        "schema": "fenjue-scorecard-v2",
        "ts": "2026-09-06T14:00:00",
        "overall": 135,
        "total_line": 150,
        "line_pass": 40,
        "verdict": "PASS",
        "band": "达标",
        "verdict_blockers": [],
        "achievable_total": 150,
        "achievable_pct": "90%",
        "lines": [
            {"line": "主线① 跨平台skill互通同步", "total": 45,
             "parts": {"a": {"score": 20, "cap": 20, "max": 25}, "b": 25},
             "evidence": ["e1"]},
            {"line": "主线② 多agent统一记忆+路由", "total": 45,
             "parts": {"a": 45}, "evidence": ["e2"]},
        ],
        "red_team": {"confirmed": ["c1"], "blindspots": ["b1"]},
    }
    sc.update(over)
    return sc


def _three_door(**over):
    td = {
        "ts": "2026-09-06T14:30:00",
        "machine_baseline": {"score": 130, "pct": "86.7%"},
        "codex_blind": {"weighted_pct": "93.1", "total": 291,
                        "exact": 270, "usable": 1, "wrong": 20},
        "independent_checks": {"blind_set": "291", "regression": "PASS", "lessons": "80%"},
        "cc_recheck": {"agreement_rate": 88},
        "red_team": {"confirmed": ["z1"], "false_positive": ["f1", "f2", "f3"],
                     "blindspots": []},
        "verdict_note": "x" * 100,
    }
    td.update(over)
    return td


def test_generate_status_v2_three_door_full(capsys):
    """v2 + three_door + 台账超期/逃生门联动降级 + 主线④⑤⑥/跨端/预读全块渲染。"""
    tracking = {"defects": [
        {"status": "open", "deadline": "2026-08-01", "owner": "<OWNER_NICK>",
         "escape_hatch_deadline": "2026-08-02"},
        {"status": "open", "deadline": "2099-01-01", "owner": "未指派"},
        {"status": "closed", "deadline": "", "owner": "x", "resolution": "refuted"},
        {"status": "closed", "deadline": "", "owner": "x", "resolution": "fixed"},
    ]}
    out = sr.generate_status(
        latest={}, dry_run=True,
        scorecard=_v2_scorecard(), three_door=_three_door(),
        tracking=tracking,
        gate={"all_pass": True, "results": [
            {"id": "C15", "desc": "d", "status": "PASS", "detail": "ok"}]},
        lessons_hitrate={"hit_rate": 85.0, "hit": 17, "miss": 3, "manual": 1},
        attention_sim={"dilution": {"scenarios": [
            {"scenario": "s1", "tokens": 1000, "dilution_vs_p0": 1.5,
             "relevant_attention_mean": 0.4, "p50": 0.35}]}},
        skill_usage={"total_calls": 10, "skills_seen": 50,
                     "low_frequency_candidates": ["a"],
                     "per_skill": {"s1": 5, "s2": 3}},
        cross_layer={"all_pass": True, "passed": 8, "total": 8, "results": []},
        pread={"pread_declared": 3, "pread_avg_hits": 2, "skill_declared": 3,
               "skill_avg": 2, "memory_declared": 3, "memory_avg": 2},
    )
    out = capsys.readouterr().out  # dry_run 路径 print 而非 return
    assert "判定(Codex): ❌ 未达标（不达标）" in out      # 台账超期 → 一票联动降级
    assert "阻断: " in out and "超期 pending" in out and "逃生门超期" in out
    assert "本轮缺陷发现" in out and "⚠️噪声高" in out     # fp/(conf+fp)>0.5
    assert "主线④" in out and "主线⑤" in out and "主线⑥" in out
    assert "跨端四层终检" in out and "开场预读门禁" in out
    assert "（暂无数据）" in out                          # 主线③ 缺 line 条目


def test_generate_status_v2_clean_pass(capsys):
    """无台账超期 + 无 blockers → PASS 保持、verdict_note 截断 72。"""
    out = sr.generate_status(latest={}, dry_run=True,
                             scorecard=_v2_scorecard(), three_door=_three_door())
    out = capsys.readouterr().out  # dry_run 路径 print 而非 return
    assert "判定(Codex): ✅ 达标" in out
    assert "判定说明:" in out and "…" in out              # vn=100 字符 > cut=72


def test_generate_status_fallback_old_reports(capsys):
    """无评分卡 → 旧 reports 回退渲染（含缺维「暂无数据」分支）。"""
    latest = {
        ("优化记忆", "R100"): ("2026-09-01T00:00:00",
                               {"score": 120, "out_of": 150}, "n1", "s1"),
        ("skill_tree", "R101"): ("2026-09-01T00:00:00",
                                 {"score": 100, "out_of": 150}, "n2", "s2"),
    }
    out = sr.generate_status(latest=latest, dry_run=True)
    out = capsys.readouterr().out  # dry_run 路径 print 而非 return
    assert "当前轮次(旧自评, 回退)" in out
    assert "（暂无数据）" in out


def test_load_registry_counts_edge_paths(tmp_path, monkeypatch):
    """registry 三态：skills 非 dict / 文件缺失（异常）/ 正常计数。"""
    reg_dir = tmp_path / "skill" / "registry"
    reg_dir.mkdir(parents=True)
    p = reg_dir / "unified-skills-index.json"
    monkeypatch.setattr(sr, "PROJECT_DIR", str(tmp_path))

    p.write_text(json.dumps({"skills": ["a", "b"]}), encoding="utf-8")
    assert sr.load_registry_counts() == (None, None)      # skills 非 dict

    p.unlink()
    assert sr.load_registry_counts() == (None, None)      # 文件缺失 → 异常分支

    p.write_text(json.dumps({"skills": {"a": {"domain": "x"}, "b": {"domain": "y"},
                                        "c": {"domain": "x"}}}), encoding="utf-8")
    assert sr.load_registry_counts() == (3, 2)            # 3 skill / 2 域


def test_generate_status_write_path_and_orphan_warn(tmp_path, monkeypatch, capsys):
    """dry_run=False 写盘：壳+正文落 tmp、非托管 part 告警、registry 缺失走静态回退行。"""
    monkeypatch.setattr(sr, "PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(sr, "STATUS_PATH", str(tmp_path / "STATUS.md"))
    monkeypatch.setattr(sr, "STATUS_PART1_PATH", str(tmp_path / "STATUS.part1.md"))
    (tmp_path / "STATUS.part9.md").write_text("orphan", encoding="utf-8")
    latest = {("优化记忆", "R100"): ("2026-09-01T00:00:00",
                                     {"score": 120, "out_of": 150}, "n", "s")}
    sr.generate_status(latest=latest, dry_run=False)
    assert (tmp_path / "STATUS.md").exists()
    assert (tmp_path / "STATUS.part1.md").exists()
    assert "STATUS part" in capsys.readouterr().err       # 孤儿 part WARN
    assert "指针壳" in (tmp_path / "STATUS.md").read_text(encoding="utf-8")


def test_pass_line_track150_branch():
    """track_150 口径分支（R213 动态达标线的另一侧）：reload 切换后恢复。"""
    import truth_constants as tc
    real = tc.SCORECARD_ACTIVE_TRACK
    tc.SCORECARD_ACTIVE_TRACK = "track_150"
    try:
        importlib.reload(sr)
        assert sr.PASS_LINE == "%s/%s" % (tc.SCORECARD_PASS_LINE, tc.SCORECARD_TOTAL)
    finally:
        tc.SCORECARD_ACTIVE_TRACK = real
        importlib.reload(sr)
    assert sr.PASS_LINE == "%s/%s" % (
        tc.SCORECARD_TRACK_200.get("pass_line", tc.SCORECARD_PASS_LINE),
        tc.SCORECARD_TRACK_200.get("total", tc.SCORECARD_TOTAL))
