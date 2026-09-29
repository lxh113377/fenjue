#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_command_face_parity.py — 「对外声明的命令面」双向对账的行为测试。

组织方式沿用本仓那条铁律：一把尺必须同时会绿和会红，且"没东西可比"要判 UNVERIFIED。
  · 正向：权威值现算非空；真面跑绿；三面等价时零违例
  · 反向：假承诺子命令 / 入口点缺声明 / 单面声明 / 教 -q —— 每种各判红并点名
  · 盲区：面缺失、面无测命令 ⇒ PremiseError（判据不得把"没核到"说成"通过"）
  · 接线：本件必须真的在 doctor 名册里（否则它只是一份躺在仓里的文件）
"""
from __future__ import annotations

from pathlib import Path

import pytest

import command_face_parity as cfp

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def faces(tmp_path, monkeypatch):
    """把取数面临时根指向 tmp_path，并给出三面等价的合法语料。"""
    scripts = set(cfp.authoritative_scripts())
    subs = set(cfp.authoritative_subcommands())
    body = ("```bash\n" + " ".join(sorted(scripts)) + "\n"
            + "\n".join(f"fenjue {s}" for s in sorted(subs)) + "\npython -m pytest\n```\n")
    for name in cfp.FACES:
        (tmp_path / name).write_text(body, encoding="utf-8")
    monkeypatch.setattr(cfp, "ROOT", str(tmp_path))
    return tmp_path, scripts, subs, body


class TestAuthorityIsRecomputed:
    def test_scripts_come_from_pyproject(self):
        import tomllib
        want = set(tomllib.loads((ROOT / "pyproject.toml")
                                 .read_text(encoding="utf-8"))["project"]["scripts"])
        assert cfp.authoritative_scripts() == want, "入口点权威值必须取自 pyproject，不另存一份"

    def test_subcommands_come_from_cli_self_description(self):
        subs = cfp.authoritative_subcommands()
        assert {"route", "doctor", "mcp-config"} <= subs
        assert all(s.strip() == s and s for s in subs)

    def test_real_shipped_face_is_clean(self):
        """真面必须绿。新看守没在已知合法输入上跑过绿就接线 = 造一把必红的闸。"""
        scripts, subs = cfp.authoritative_scripts(), cfp.authoritative_subcommands()
        bad, reading = cfp.diff_faces(scripts, subs)
        assert not bad, f"投递面自身被判分叉：{bad}"
        assert reading["faces"] == len(cfp.FACES)


class TestNegativeControls:
    def test_ghost_subcommand_is_named(self, faces):
        tmp, scripts, subs, body = faces
        (tmp / "README.en.md").write_text(body + "```bash\nfenjue not-a-real-sub\n```\n",
                                          encoding="utf-8")
        bad, _ = cfp.diff_faces(scripts, subs)
        assert any("假承诺" in b and "not-a-real-sub" in b for b in bad), bad

    def test_missing_entrypoint_is_named(self, faces):
        tmp, scripts, subs, body = faces
        victim = sorted(scripts)[-1]
        (tmp / "llms.txt").write_text(body.replace(victim, "REMOVED"), encoding="utf-8")
        bad, _ = cfp.diff_faces(scripts, subs)
        assert any("未声明入口点" in b and victim in b for b in bad), bad

    def test_single_face_claim_is_a_divergence(self, faces):
        tmp, scripts, subs, body = faces
        extra = sorted(subs)[-1]
        (tmp / "README.en.md").write_text(body.replace(f"\nfenjue {extra}\n", "\n"),
                                          encoding="utf-8")
        bad, _ = cfp.diff_faces(scripts, subs)
        assert any("双语子命令面分叉" in b and extra in b for b in bad), bad

    def test_appended_dash_q_is_red_even_when_both_faces_agree(self, faces):
        """两面一起写错时，"相等"不是放行条件——否则这条腿退化成一致性检查。"""
        tmp, scripts, subs, body = faces
        q = body.replace("python -m pytest\n", "python -m pytest -q\n")
        (tmp / "README.md").write_text(q, encoding="utf-8")
        (tmp / "README.en.md").write_text(q, encoding="utf-8")
        bad, _ = cfp.diff_faces(scripts, subs)
        assert any("叠了 -q" in b for b in bad), bad
        assert not any("分叉" in b for b in bad), bad

    def test_prose_line_break_does_not_fabricate_a_subcommand(self, faces):
        """回归腿：`fenjue` 在行尾、次行以 python 开头，不得被拼成一条主张（\\s+ 的旧坑）。"""
        tmp, scripts, subs, body = faces
        prose = body + "本项目命令行入口叫 fenjue\npython 只作兜底写法\n"
        (tmp / "README.md").write_text(prose, encoding="utf-8")
        (tmp / "README.en.md").write_text(prose, encoding="utf-8")
        bad, _ = cfp.diff_faces(scripts, subs)
        assert not any("假承诺" in b and "python" in b for b in bad), bad


class TestBlindSpots:
    def test_missing_face_raises_instead_of_passing(self, faces, monkeypatch):
        tmp, scripts, subs, _body = faces
        monkeypatch.setattr(cfp, "FACES", ["README.md", "README.en.md", "absent.txt"])
        with pytest.raises(cfp.PremiseError):
            cfp.diff_faces(scripts, subs)

    def test_face_without_test_command_raises(self, faces):
        tmp, scripts, subs, _body = faces
        (tmp / "README.en.md").write_text("```bash\nfenjue doctor\n```\n", encoding="utf-8")
        with pytest.raises(cfp.PremiseError):
            cfp.diff_faces(scripts, subs)

    def test_single_readme_face_raises(self, faces, monkeypatch):
        """双语对账需要两面；只挑出一面时必须报错，不得静默"没有分叉"。"""
        _tmp, scripts, subs, _body = faces
        monkeypatch.setattr(cfp, "FACES", ["README.md", "llms.txt"])
        with pytest.raises(cfp.PremiseError):
            cfp.diff_faces(scripts, subs)


class TestWiredNotJustPresent:
    def test_judge_is_registered_in_doctor_roster(self):
        import fenjue_cli
        names = [n for n, _rel in fenjue_cli.CHECKS]
        assert "command-face-parity" in names, \
            f"判据没进 doctor 名册就是半成品，名册={names}"

    def test_judge_is_wired_into_both_ci_faces(self):
        for wf in (".github/workflows/ci.yml", ".github/workflows/ci-pr.yml"):
            text = (ROOT / wf).read_text(encoding="utf-8")
            assert "eval/command_face_parity.py" in text, f"{wf} 未接本判据=受理面/合入面各漏一半"

    def test_selftest_entry_point_is_runnable_and_green(self):
        """入口必须用子进程真跑一次：只 import 纯函数不等于 `--selftest` 这条路是通的。"""
        import subprocess
        import sys
        r = subprocess.run([sys.executable, "-B", str(ROOT / "eval" / "command_face_parity.py"),
                            "--selftest"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        assert r.returncode == 0, (r.stdout[-800:] + r.stderr[-800:])
        assert "[GATE:cmd-face-parity-selftest-pass]" in r.stdout
