# -*- coding: utf-8 -*-
"""R209-2③ 补测：六模块单元/冒烟 + direct_layer 守护组（coverage 34%→40%+）。

补测簇（deliverables/全量代码与架构优化分析_R209.md §2.3 M3，双代理交叉裁定）：
  rebuild_no_bge / frozen_blind_eval / cc_blind_recheck / aggregate_status /
  build_registry / scorecard（主模块）。
守护测试：direct_layer 本地守卫 / NOT USE 守卫 / NONE 哨兵 / _cregex 预编译缓存。
负面用例：坏 pattern 兜底 / 基线污染断言 / 非 JSON 输出容错。
"""
import json
import os
import sys
import types

import numpy as np
import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if EVAL_DIR not in sys.path:
    sys.path.insert(0, EVAL_DIR)

import direct_layer  # noqa: E402
import rebuild_no_bge  # noqa: E402
import frozen_blind_eval  # noqa: E402
import cc_blind_recheck  # noqa: E402
import build_registry  # noqa: E402
import aggregate_status  # noqa: E402
import scorecard  # noqa: E402


# ============ direct_layer 守护组 ============
class TestDirectLayerGuards:
    def test_cregex_cache_identity_and_flag(self):
        """预编译缓存：同 pattern 复用同一编译对象，且 IGNORECASE 生效。"""
        p = "r209_cache_probe_pattern"
        a = direct_layer._cregex(p)
        b = direct_layer._cregex(p)
        assert a is b
        assert a.search("R209_CACHE_PROBE_PATTERN") is not None

    def test_cregex_bad_pattern_propagates_reerror(self):
        """负面：坏 pattern 编译抛 re.error（与原 re.search 行为一致）。"""
        import re as _re
        with pytest.raises(_re.error):
            direct_layer._cregex("([unclosed")

    def test_bad_pattern_in_map_is_skipped(self, monkeypatch):
        """负面兜底：DIRECT_MAP 中坏 pattern 不崩溃，走 except re.error: continue。"""
        monkeypatch.setattr(direct_layer, "DIRECT_MAP",
                            [("([unclosed", "skill-x"), ("正常命中", "skill-y")])
        assert direct_layer.direct_route("请正常命中一下") == "skill-y"
        assert direct_layer.direct_route("完全无关的查询") is None

    def test_direct_hit_and_none_sentinel(self, monkeypatch):
        monkeypatch.setattr(direct_layer, "DIRECT_MAP",
                            [("查询.*git 提交", "skill-git"),
                             ("会议材料提前|会议.*材料", "NONE")])
        assert direct_layer.direct_route("帮我查询 git 提交记录") == "skill-git"
        assert direct_layer.direct_route("会议材料提前准备一下") == "NONE"

    def test_local_guard_fallback(self, monkeypatch):
        """R18.2 本地守卫：本地意图跳过云端直连，无本地替代时回落该云端为次优解。"""
        monkeypatch.setattr(direct_layer, "DIRECT_MAP",
                            [("生成图片", "byted-seedream-image-generate")])
        monkeypatch.setattr(direct_layer, "NEGATIVE_TAG_MAP", {})
        # 无本地意图 → 直连命中
        assert direct_layer.direct_route("帮我生成图片") == "byted-seedream-image-generate"
        # 本地意图（"不用云端" 命中 local_kw）→ 跳过云端 → 回落次优解（R166）
        assert direct_layer.direct_route("不用云端，本地生成图片") == "byted-seedream-image-generate"

    def test_not_use_guard_blocks_direct(self, monkeypatch):
        """R20 NOT USE 守卫：直连命中但负标签生效 → 放弃直连回落全管线(None)。"""
        monkeypatch.setattr(direct_layer, "DIRECT_MAP",
                            [("转写.*音频", "video-whisper-transcribe")])
        monkeypatch.setattr(direct_layer, "NEGATIVE_TAG_MAP",
                            {"video-whisper-transcribe": ["视频"]})
        # 负标签 "视频" 命中且无否定前缀 → 拦截
        assert direct_layer.direct_route("帮我把视频转写音频") is None
        # 负标签不命中 → 直连放行
        assert direct_layer.direct_route("帮我把录音转写音频") == "video-whisper-transcribe"


# ============ rebuild_no_bge ============
class TestRebuildNoBge:
    def _fake_env(self, monkeypatch, old_names, rows, reg_names):
        old_skills = [{"name": n} for n in old_names]
        old_arr = np.arange(rows * 4, dtype="float32").reshape(rows, 4)
        reg = {"skills": {n: {} for n in reg_names}}
        monkeypatch.setattr(rebuild_no_bge, "np", types.SimpleNamespace(load=lambda p: old_arr))
        monkeypatch.setattr(rebuild_no_bge.bi, "REGISTRY_FILE", "fake_registry.json")

        def fake_load_json(path):
            return old_skills if "bge_fullbody_skills" in str(path) else reg
        monkeypatch.setattr(rebuild_no_bge.bi, "load_json", fake_load_json)

    def test_load_old_bge_trims_dead_and_reports_added(self, monkeypatch, capsys):
        """R201 自动差集：旧 BGE 有/注册表无 → 裁剪；注册表新增 → 警告不崩溃。"""
        self._fake_env(monkeypatch, ["a", "b", "c"], 3, ["a", "c", "d-new"])
        new_arr, new_skills = rebuild_no_bge.load_old_bge()
        assert new_arr.shape == (2, 4)
        assert [s["name"] for s in new_skills] == ["a", "c"]
        out = capsys.readouterr()
        assert "自动识别已删技能 1 个" in out.out          # dead = {b}
        assert "d-new" in out.out                          # added 警告列出新增技能

    def test_load_old_bge_asserts_polluted_baseline(self, monkeypatch):
        """负面：npy 行数与清单脱同步 → AssertionError 提示先恢复基线。"""
        self._fake_env(monkeypatch, ["a", "b", "c"], 2, ["a", "b", "c"])
        with pytest.raises(AssertionError, match="基线被污染"):
            rebuild_no_bge.load_old_bge()

    def test_import_smoke(self):
        assert callable(rebuild_no_bge.load_old_bge)
        assert callable(rebuild_no_bge.main)


# ============ frozen_blind_eval ============
class TestFrozenBlindEval:
    def test_evaluate_scoring_weights_and_none_hit(self, monkeypatch):
        """R164 计分：命中加权/条数；盲区期望 None 且路由 NONE → 命中；上限暴露。"""
        tiers = [{"queries": [
            {"query": "q1", "expected_skill": "sk-a", "judge": "exact"},
            {"query": "q2", "expected_skill": None, "judge": "blindspot"},
            {"query": "q3", "expected_skill": "sk-x", "judge": "wrong"},
        ]}]
        canned = {"q1": "sk-a", "q2": "NONE", "q3": "sk-wrong-answer"}
        monkeypatch.setattr(frozen_blind_eval, "load_frozen", lambda set_name: tiers)
        monkeypatch.setattr(frozen_blind_eval, "run_router", lambda q: (canned[q], ""))
        r = frozen_blind_eval.evaluate("frozen")
        # q1 hit(w=1.0) + q2 hit(w=0.4, 盲区) + q3 miss(w=0.5)
        assert r["n"] == 3 and r["hits"] == 2
        assert r["score"] == round((1.0 + 0.4) / 3 * 100, 1)
        assert r["max_achievable"] == round((1.0 + 0.4 + 0.5) / 3 * 100, 1)
        assert [row["hit"] for row in r["results"]] == [True, True, False]

    def test_run_router_exception_returns_error_marker(self, monkeypatch):
        """路由器异常 → ('?', err) 软失败（不中断盲测）。R214-3: 适配 enable_memory=False 签名。"""
        stub = types.SimpleNamespace(
            route=lambda q, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setitem(sys.modules, "unified_router", stub)
        top1, err = frozen_blind_eval.run_router("任意查询")
        assert top1 == "?" and "boom" in err

    def test_load_frozen_real_files_smoke(self):
        """真实冻结集可读且为分层结构（冻结原则：只跑不调）。"""
        frozen = frozen_blind_eval.load_frozen("frozen")
        assert isinstance(frozen, list) and len(frozen) > 0
        layered = frozen_blind_eval.load_frozen("layered")
        assert isinstance(layered, list) and len(layered) > 0


# ============ cc_blind_recheck ============
class TestCcBlindRecheck:
    def test_parse_json_out_array_object_and_garbage(self):
        """负面容错：LLM 输出夹带文本时提取首个 JSON；非 JSON 返回 None。"""
        assert cc_blind_recheck.parse_json_out('裁决如下 [1, 2] 完毕') == [1, 2]
        assert cc_blind_recheck.parse_json_out('前缀 {"a": 1}') == {"a": 1}
        assert cc_blind_recheck.parse_json_out("没有任何结构化内容") is None
        assert cc_blind_recheck.parse_json_out("[broken json") is None

    def test_norm_sentinels(self):
        assert cc_blind_recheck.norm("NONE") is None
        assert cc_blind_recheck.norm("") is None
        assert cc_blind_recheck.norm(None) is None
        assert cc_blind_recheck.norm("skill-a") == "skill-a"

    def test_unique_report_paths_never_overwrites(self, tmp_path):
        """同日多次复核 _r2/_r3 递增，绝不覆盖历史报告。"""
        base = str(tmp_path / "report")
        md1, js1 = cc_blind_recheck.unique_report_paths(base)
        assert md1.endswith("report.md") and js1.endswith("report.json")
        open(md1, "w", encoding="utf-8").close()
        md2, _js2 = cc_blind_recheck.unique_report_paths(base)
        assert md2.endswith("report_r2.md")
        open(_js2, "w", encoding="utf-8").close()
        md3, js3 = cc_blind_recheck.unique_report_paths(base)
        assert md3.endswith("report_r3.md") and js3.endswith("report_r3.json")

    def test_load_samples_three_door_ids(self, monkeypatch, tmp_path):
        for door in ("oc", "cc", "hermes"):
            (tmp_path / f"sample_{door}.json").write_text(
                json.dumps({"queries": [{"query": f"{door}-q1"}, {"query": f"{door}-q2"}]}),
                encoding="utf-8")
        monkeypatch.setattr(cc_blind_recheck, "SAMPLES_DIR", str(tmp_path))
        entries = cc_blind_recheck.load_samples("three_door")
        assert [e["id"] for e in entries] == ["oc-1", "oc-2", "cc-1", "cc-2", "hermes-1", "hermes-2"]

    def test_build_prompt_contains_entries(self):
        p = cc_blind_recheck.build_prompt([{"id": "oc-1", "query": "R209 测试问题"}])
        assert "R209 测试问题" in p and "oc-1" in p


# ============ build_registry ============
_SKILL_MD_FULL = """---
name: my-r209-skill
display_name: My R209 Skill
description: 补测用虚构技能
domain: code
version: 1.2.3
user_created: "true"
---
# 标题行（不应成为 description）
正文第一段说明文字。
"""

_SKILL_MD_BARE = """# 只有标题
裸文件第一段，无 frontmatter。
"""


class TestBuildRegistry:
    def test_parse_skill_md_full_frontmatter(self, tmp_path):
        d = tmp_path / "my-r209-skill"
        d.mkdir()
        (d / "SKILL.md").write_text(_SKILL_MD_FULL, encoding="utf-8")
        meta = build_registry.parse_skill_md(str(d))
        assert meta["name"] == "my-r209-skill"
        assert meta["display_name"] == "My R209 Skill"
        assert meta["domain"] == "code"
        assert meta["version"] == "1.2.3"
        assert meta["user_created"] is True
        assert meta["source"] == "user-created"
        # R278（2026-09-22）：原断言硬编码 ["oc","wb","tc","cx"] —— 其中 oc 已退役
        # （2026-09-21）、tc 已改名为 tr ⇒ 期望值与 build_registry 默认值（随
        # truth_constants.endpoints.active 演进）脱节，本测试恒 FAIL。
        # 改为**动态取权威源**：默认值必须 == endpoints.active，主文件改端点后自动跟随。
        import json as _json
        import os as _os
        _tc = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                           "truth_constants.json")
        with open(_tc, encoding="utf-8") as _fh:
            _active = _json.load(_fh)["endpoints"]["active"]
        assert meta["compatible_platforms"] == _active, (
            f"默认平台集应与 truth_constants.endpoints.active 一致: "
            f"{meta['compatible_platforms']} != {_active}")

    def test_parse_skill_md_bare_falls_back_to_dirname(self, tmp_path):
        d = tmp_path / "bare-skill-dir"
        d.mkdir()
        (d / "SKILL.md").write_text(_SKILL_MD_BARE, encoding="utf-8")
        meta = build_registry.parse_skill_md(str(d))
        assert meta["name"] == "bare-skill-dir"          # 无 name → 目录音
        assert meta["description"].startswith("裸文件第一段")
        assert meta["source"] == "community"             # user_created 缺省 → community
        assert isinstance(meta["domain"], str) and meta["domain"]

    def test_parse_skill_md_missing_returns_none(self, tmp_path):
        d = tmp_path / "empty-dir"
        d.mkdir()
        assert build_registry.parse_skill_md(str(d)) is None

    def test_infer_domain_returns_nonempty(self):
        dom = build_registry._infer_domain("git 提交助手", "辅助提交代码")
        assert isinstance(dom, str) and dom.strip()


# ============ aggregate_status ============
class TestAggregateStatus:
    def test_evidence_script_ok_missing_warns(self, tmp_path, capsys):
        """负面：证据脚本缺失 → False + WARN（优雅回退，不静默引用死链）。"""
        assert aggregate_status.evidence_script_ok(str(tmp_path / "nope.py"), "R209测试") is False
        assert "不存在" in capsys.readouterr().err

    def test_evidence_script_ok_present(self, tmp_path):
        f = tmp_path / "real.py"
        f.write_text("print('ok')", encoding="utf-8")
        assert aggregate_status.evidence_script_ok(str(f), "R209测试") is True

    def test_pick_latest_by_dim_round(self):
        reports = [
            {"ts": "2026-01-01", "scores": {"perf": {"round": "r1", "score": 5}}, "notes": "old", "session": "s1"},
            {"ts": "2026-02-01", "scores": {"perf": {"round": "r1", "score": 9}}, "notes": "new", "session": "s2"},
            {"ts": "2026-03-01", "scores": {"not-dict": "跳过非字典"}},
        ]
        latest = aggregate_status.pick_latest(reports)
        assert latest[("perf", "r1")][0] == "2026-02-01"
        assert latest[("perf", "r1")][1]["score"] == 9
        assert latest[("perf", "r1")][2] == "new" and latest[("perf", "r1")][3] == "s2"


# ============ scorecard 主模块（collect_red_team 红队判定） ============
class TestScorecardRedTeam:
    def _line(self, line_name, parts):
        return {"line": line_name, "parts": parts}

    def test_collect_red_team_cap_severity_and_blindspot(self, monkeypatch, tmp_path):
        """R165 U1 cap 判定 + 严重度分级 + 盲区/wrong 分流 + 误报源缺省为空。"""
        monkeypatch.setattr(scorecard, "EVAL_DIR", str(tmp_path))  # 隔离 codex_audit_scores.json
        sync = self._line("主线①", {"d-sync": {"score": 10, "max": 12, "cap": 12,
                                               "detail": "扣分明细", "evidence": "证据"}})
        mem = self._line("主线②", {"d-mem": {"score": 8, "max": 8}})   # score==cap → 无缺陷
        routing = self._line("主线③", {"d-route": {"score": 3, "max": 8}})
        routing["blind_findings"] = [
            {"judge": "blindspot", "router_top1": "误路由技能", "query": "盲区问题", "expected": None},
            {"judge": "blindspot", "router_top1": None, "query": "正确拦截", "expected": None},
            {"judge": "wrong", "query": "wrong问题", "expected": "目标技能", "router_top1": "错路由"},
        ]
        r = scorecard.collect_red_team(sync, mem, routing)
        # confirmed = sync扣分(高, max12) + route扣分(中, max8) + wrong(中)
        assert r["counts"]["confirmed"] == 3
        assert r["counts"]["blindspots"] == 1                  # router_top1=None 的盲区不计
        assert r["counts"]["false_positive"] == 0              # 隔离环境无裁决文件
        sev = {c["dim"]: c["severity"] for c in r["confirmed"]}
        assert sev["主线①/d-sync"] == "高"
        assert sev["主线③/d-route"] == "中"
        assert sev["主线③/盲测(wrong)"] == "中"
        assert all(c["dim"].startswith("主线②") is False for c in r["confirmed"])  # mem 无缺陷

    def test_collect_red_team_all_full_scores_clean(self, monkeypatch, tmp_path):
        """全维 score==cap → confirmed 为空（护栏：无证据不入确认清单）。"""
        monkeypatch.setattr(scorecard, "EVAL_DIR", str(tmp_path))
        lines = [self._line(f"线{i}", {"d": {"score": 10, "max": 10}}) for i in range(3)]
        for ln in lines:
            ln["blind_findings"] = []
        r = scorecard.collect_red_team(*lines)
        assert r["counts"] == {"confirmed": 0, "false_positive": 0, "blindspots": 0}
