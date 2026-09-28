#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_hitrate_cli.py — 对外主打入口 hitrate_cli.py 的行为测试。

补这条的原因是对标轮实测到的一个盲区：`eval/hitrate_cli.py` 是 README
「30 秒上手」里评委敲的第一条命令，也是 pyproject `[project.scripts]`
注册的 `fenjue-hitrate` 入口，但公开子集里 **没有任何测试引用过它**
（取数面 = `grep -rl "hitrate_cli" eval/tests/` 实测 0 命中，2026-09-29）。
一个没有任何测试的对外入口，等于把"能跑"这句话交给运气。

覆盖面（每个断言都对应当前实测读数，不写"应该能跑"）：
  1. 两种技能布局都能读：扁平 `<name>.md` 与 Agent Skills 标准 `<name>/SKILL.md`
  2. 同名时标准目录优先（它是显式声明的技能身份）
  3. 扁平面回归值锁定：14 条查询 / Top-1 10 条 / Top-3 12 条（改算法必须显式动这里）
  4. 零输入与「期望技能不在清单里」两条异常路径都返回 rc=2，不记 PASS
  5. 入口以子进程真跑（只 import 纯函数不算测入口）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hitrate_cli import evaluate, load_skills, parse_frontmatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "eval" / "hitrate_cli.py"
FLAT = ROOT / "examples" / "skills"
FLAT_Q = ROOT / "examples" / "queries.json"
STANDARD = ROOT / "examples" / "agent-skills" / "skills"
STANDARD_Q = ROOT / "examples" / "agent-skills" / "queries.json"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *[str(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT),
    )


class TestLayouts:
    def test_flat_layout_loads_all_skills(self):
        names = {s["name"] for s in load_skills(FLAT)}
        assert len(names) == 12, f"扁平均应 12 个技能，实测 {len(names)}"
        assert "code-review" in names

    def test_agent_skills_standard_layout_loads(self):
        """标准目录格式（<name>/SKILL.md）必须免翻译直接可评估。"""
        names = {s["name"] for s in load_skills(STANDARD)}
        assert names == {"chart-render", "log-triage", "sql-optimize"}

    def test_profile_uses_frontmatter_triplet(self):
        skill = next(s for s in load_skills(STANDARD) if s["name"] == "log-triage")
        assert "日志" in skill["profile"] and "triage" in skill["profile"]

    def test_standard_layout_wins_on_name_clash(self, tmp_path: Path):
        """同名冲突：目录式 SKILL.md 是显式身份，覆盖扁平件而非并存成两条。"""
        (tmp_path / "demo.md").write_text(
            "---\nname: demo\ndescription: 旧描述\ntriggers: 旧\n---\n正文\n",
            encoding="utf-8")
        pkg = tmp_path / "demo"
        pkg.mkdir()
        (pkg / "SKILL.md").write_text(
            "---\nname: demo\ndescription: 新描述\ntriggers: 新\n---\n正文\n",
            encoding="utf-8")
        skills = load_skills(tmp_path)
        assert len(skills) == 1, "同名不得在清单里出现两次（会让期望技能歧义）"
        assert "新描述" in skills[0]["profile"]


class TestEvaluation:
    def test_flat_face_regression_values(self):
        """锁 README 对外的这组数：改分词器/权重必然撞红这里，这是有意的。"""
        skills = load_skills(FLAT)
        cases = json.loads(FLAT_Q.read_text(encoding="utf-8"))
        res = evaluate(skills, cases, top=3)
        assert res["skills"] == 12 and res["n_cases"] == 14
        assert res["overall"]["top1"] == 10
        assert res["overall"]["top3"] == 12
        assert res["tiers"]["hard"]["top1_rate"] == pytest.approx(0.4)

    def test_standard_face_scores_and_reports_tiers(self):
        skills = load_skills(STANDARD)
        cases = json.loads(STANDARD_Q.read_text(encoding="utf-8"))
        res = evaluate(skills, cases, top=3)
        assert res["n_cases"] == 4
        assert set(res["tiers"]) == {"easy", "medium", "hard"}
        assert res["overall"]["top1"] == 4, "3 个互不重叠的技能做格式演示，应当全对"


class TestFrontmatter:
    def test_plain_text_form(self):
        fm = parse_frontmatter("---\nname: a\ndescription: b\n---\n正文\n")
        assert fm == {"name": "a", "description": "b"}

    def test_missing_frontmatter_is_empty_not_crash(self):
        assert parse_frontmatter("没有围栏的正文") == {}


class TestEntrypoint:
    """入口必须被真跑：rc + stdout 形状，而不是只 import 纯函数。"""

    def test_flat_face_rc0_and_reports_table(self):
        r = run_cli("--skills-dir", FLAT, "--queries", FLAT_Q, "--top", 3)
        assert r.returncode == 0, r.stderr[-500:]
        assert "Top-1率" in r.stdout and "合计" in r.stdout

    def test_standard_face_rc0(self):
        r = run_cli("--skills-dir", STANDARD, "--queries", STANDARD_Q, "--top", 3)
        assert r.returncode == 0, r.stderr[-500:]

    def test_json_flag_emits_machine_readable(self):
        r = run_cli("--skills-dir", FLAT, "--queries", FLAT_Q, "--json")
        assert r.returncode == 0, r.stderr[-500:]
        payload = json.loads(r.stdout)
        assert payload["overall"]["top1"] == 10

    def test_missing_dir_returns_2(self, tmp_path: Path):
        r = run_cli("--skills-dir", tmp_path / "nope", "--queries", FLAT_Q)
        assert r.returncode == 2
        assert "技能目录不存在" in r.stderr

    def test_empty_skill_dir_returns_2_not_pass(self, tmp_path: Path):
        """零输入不得记 PASS：这是本仓「恒绿尺子比没有尺子更坏」的入口级体现。"""
        empty = tmp_path / "empty"
        empty.mkdir()
        r = run_cli("--skills-dir", empty, "--queries", FLAT_Q)
        assert r.returncode == 2
        assert "零输入" in r.stderr

    def test_unknown_expected_skill_returns_2(self, tmp_path: Path):
        q = tmp_path / "q.json"
        q.write_text(json.dumps(
            [{"query": "随便说点什么", "expected_skill": "does-not-exist", "tier": "easy"}],
            ensure_ascii=False), encoding="utf-8")
        r = run_cli("--skills-dir", FLAT, "--queries", q)
        assert r.returncode == 2
        assert "不存在的技能" in r.stderr
