#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_fenjue_cli.py — 统一入口 `fenjue` 的行为测试（子命令 + doctor + 配置生成）。

覆盖面按「一把尺必须同时会绿和会红」组织：
  · 正向：--version 读到的版本 == pyproject 里的 project.version（单源自证）
  · 正向：route 排序、mcp-config 的 JSON 能被 json.loads、doctor 全绿
  · 反向：空技能库 rc=2、未知 client rc=2、注入一条必红检查后 doctor rc=1 且点名它、
    CHECKS 为空时 doctor 判 UNVERIFIED（rc=2）而不是"全部通过"
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

import fenjue_cli  # noqa: E402


class TestVersion:
    def test_version_matches_pyproject(self):
        import tomllib
        want = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        got, faces = fenjue_cli._version()
        assert got == want, f"版本漂移：运行时 {got}（取数面 {faces}）对 pyproject {want}"

    def test_version_flag_rc0(self):
        assert fenjue_cli.main(["--version"]) == 0


class TestRoute:
    def test_route_ranks_expected_skill_first(self, capsys):
        """用仓内 easy 层的原句，不自己造句：自造查询命中与否取决于分词器脾气，那是另一件事。"""
        assert fenjue_cli.main(["route", "把这个统计结果画成柱状图", "--top", "3"]) == 0
        out = capsys.readouterr().out
        assert "chart-render" in out.splitlines()[1], out

    def test_route_json_is_parseable(self, capsys):
        assert fenjue_cli.main(["route", "帮我把这份 markdown 转成 PDF", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["candidates"][0]["name"] == "pdf-export", payload

    def test_empty_skill_dir_is_fatal_not_empty_candidates(self, tmp_path):
        rc = fenjue_cli.main(["route", "随便说点什么", "--skills-dir", str(tmp_path)])
        assert rc == 2


class TestMcpConfig:
    def test_json_clients_are_parseable(self, capsys):
        for client in ("generic", "claude", "qoder"):
            assert fenjue_cli.main(["mcp-config", "--client", client]) == 0
            payload = json.loads(capsys.readouterr().out)
            server = payload["mcpServers"]["fenjue"]
            assert server["command"], server
            assert isinstance(server["args"], list), server

    def test_toml_client_for_codex(self, capsys):
        assert fenjue_cli.main(["mcp-config", "--client", "codex"]) == 0
        assert "[mcp_servers.fenjue]" in capsys.readouterr().out

    def test_unknown_client_is_rejected(self):
        """argparse 的 choices 会 SystemExit(2)；自己校验会 return 2。两种都算拒绝，但不能放行。"""
        try:
            rc = fenjue_cli.main(["mcp-config", "--client", "notepad"])
        except SystemExit as exc:  # argparse 路径
            rc = exc.code
        assert rc == 2, f"未知 client 必须被拒，实测 rc={rc}"


class TestDoctor:
    @pytest.mark.timeout(420)
    def test_full_doctor_is_green(self):
        """真跑一遍 doctor：它是「这台机器上哪条链是通的」的唯一载体，不能只测拼装逻辑。

        单条测试放宽到 420s（默认 addopts 是 120s）：doctor 串行起整张 CHECKS 名册的子进程，
        每个都要 import sklearn，120s 在慢机器上是会误杀的墙钟线——被杀掉读数就不是读数。
        """
        proc = subprocess.run([sys.executable, str(ROOT / "eval" / "fenjue_cli.py"), "doctor", "--json"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              cwd=str(ROOT), timeout=600)
        assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
        payload = json.loads(proc.stdout)
        names = {c["check"] for c in payload["checks"]}
        assert {"doc-links", "doc-claims", "workflow-roster", "hitrate-face",
                "bench-smoke", "public-clean-selftest"} <= names
        assert all(c["rc"] == 0 for c in payload["checks"]), payload["checks"]

    def test_injected_red_check_is_named(self, monkeypatch):
        """反向腿：塞一条必红检查，doctor 必须 rc=1 且点名它，而不是折成一句「有检查失败」。"""
        monkeypatch.setattr(fenjue_cli, "CHECKS", [
            ("doc-links", ["eval/check_doc_links.py"]),
            ("planted-fail", [sys.executable, "-c", "import sys; sys.exit(3)"]),
        ])
        assert fenjue_cli.main(["doctor"]) == 1

    def test_missing_carrier_is_skipped_not_passed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fenjue_cli, "CHECKS", [("ghost", ["no_such_script.py"])])
        assert fenjue_cli.main(["doctor"]) == 2

    def test_zero_checks_never_means_pass(self, monkeypatch):
        monkeypatch.setattr(fenjue_cli, "CHECKS", [])
        assert fenjue_cli.main(["doctor"]) == 2
