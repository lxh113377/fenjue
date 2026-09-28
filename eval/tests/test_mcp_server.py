#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_mcp_server.py — MCP 服务面的行为回执（不是"文件在场"回执）。

为什么必须有一路子进程真握手：`eval/mcp_server.py` 对外宣称"agent 可以直接调"。
只看模块能 import、只看工具函数返回值，证明的是 Python 层可用，证明不了
**协议帧能过**（SDK 版本改名、stdio 分帧、工具注册时机都能让一个"能 import
的服务"对真实 agent 一句应答都不回）。所以本文件三条腿：
  A 直接调用工具函数（业务读数正确）
  B 拒绝路径（空 query / top 越界必须抛，不得静默返回空清单）
  C 真 stdio JSON-RPC 握手（initialize → tools/list → tools/call）

C 腿在没装可选依赖 `mcp` 时判 **SKIP 且写明缺什么**，不判 PASS。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

mcp_sdk = pytest.importorskip(
    "mcp.server.mcpserver",
    reason="未安装可选依赖 mcp（pip install \"mcp>=2.2,<3\"）；缺依赖判 SKIP 不判 PASS",
)

sys.path.insert(0, str(ROOT / "eval"))
import mcp_server  # noqa: E402


class TestToolFunctions:
    def test_list_skills_reports_actual_roster(self):
        out = mcp_server.list_skills()
        assert out["count"] == len(out["skills"]) > 0
        assert {s["name"] for s in out["skills"]} >= {"code-review", "chart-render"}

    def test_route_skill_returns_scored_candidates(self):
        out = mcp_server.route_skill("帮我把这组数据画成柱状图", top=3)
        assert len(out["candidates"]) == 3
        assert out["candidates"][0]["name"] == "chart-render"
        assert out["candidates"][0]["score"] >= out["candidates"][-1]["score"]

    def test_hitrate_report_matches_cli_face(self):
        """服务面与 CLI 面必须同数：两处各测一套等于没有单源。"""
        from hitrate_cli import evaluate, load_skills
        skills = load_skills(mcp_server.SKILLS_DIR)
        cases = json.loads(mcp_server.QUERIES_FILE.read_text(encoding="utf-8"))
        expected = evaluate(skills, cases, top=3)["overall"]["top1"]
        assert mcp_server.hitrate_report(top=3)["overall"]["top1"] == expected


class TestRejections:
    def test_empty_query_raises_not_empty_candidates(self):
        with pytest.raises(ValueError):
            mcp_server.route_skill("   ")

    @pytest.mark.parametrize("bad_top", [0, 11])
    def test_out_of_range_top_raises(self, bad_top):
        with pytest.raises(ValueError):
            mcp_server.route_skill("画个图", top=bad_top)

    def test_empty_roster_raises(self, tmp_path, monkeypatch):
        empty = tmp_path / "skills"
        empty.mkdir()
        monkeypatch.setattr(mcp_server, "SKILLS_DIR", empty)
        with pytest.raises(ValueError):
            mcp_server.list_skills()


def _rpc(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class TestStdioHandshake:
    """真握手：向子进程 stdin 逐条写 JSON-RPC，另起线程读 stdout 的应答。

    第一版用 `subprocess.run(input=全部三行)` 写回后立刻 EOF，服务端在 stdin
    关闭时直接退出，tools/call 那条应答根本没发出来（实测 StopIteration）。
    正解＝双向都保持打开：写一条读一条，收齐期望 id 后再 terminate。
    """

    PROC = [sys.executable, str(ROOT / "eval" / "mcp_server.py")]
    _INIT = _rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "pytest", "version": "0"}}})
    _READY = _rpc({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def _exchange(self, requests: list[str], expect_ids: list[int]) -> dict:
        import threading
        import time

        proc = subprocess.Popen(
            self.PROC, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            cwd=str(ROOT),
        )
        replies: dict = {}
        err_lines: list[str] = []

        def reader(stream, sink):
            for raw in stream:
                if sink is None:
                    err_lines.append(raw)
                    continue
                raw = raw.strip()
                if raw.startswith("{"):
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("id") is not None:
                        replies[obj["id"]] = obj
                else:
                    err_lines.append(raw)

        threads = [
            threading.Thread(target=reader, args=(proc.stdout, replies), daemon=True),
            threading.Thread(target=reader, args=(proc.stderr, None), daemon=True),
        ]
        for t in threads:
            t.start()

        try:
            for line in [self._INIT, self._READY] + requests:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
            deadline = time.time() + 60
            while time.time() < deadline and not all(i in replies for i in expect_ids):
                time.sleep(0.2)
        finally:
            for s in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    s.close()
                except Exception:
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

        missing = [i for i in expect_ids if i not in replies]
        assert not missing, (
            f"服务端未应答 id={missing}；stderr 尾部={(''.join(err_lines))[-500:]}"
        )
        return replies

    def test_initialize_and_tools_list(self):
        replies = self._exchange(
            [_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})], [1, 2])
        assert "protocolVersion" in replies[1].get("result", {}), replies[1]
        names = {t["name"] for t in replies[2]["result"]["tools"]}
        assert {"list_skills", "route_skill", "hitrate_report"} <= names, names

    def test_tools_call_over_stdio(self):
        replies = self._exchange(
            [_rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                   "params": {"name": "route_skill",
                              "arguments": {"query": "这段报错日志帮我定位根因", "top": 2}}})],
            [3])
        called = replies[3]
        assert "error" not in called, called
        text = "".join(c.get("text", "") for c in called["result"].get("content", []))
        assert "log-triage" in text, text[:300]
