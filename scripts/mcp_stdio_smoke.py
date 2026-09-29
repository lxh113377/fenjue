#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_stdio_smoke.py — 对一个 MCP stdio 服务做真握手探针（CI 装面与本地自查共用）。

为什么要有这个文件而不是在 shell 里 `printf ... | fenjue-mcp > out.json`：
  run 36478129692 的 install-face 就是红在那种写法上——printf 写完那一刻 stdin 就 EOF，
  服务端在应答 tools/list 之前退出，`grep -q` 拿到空文件判 rc=1；而同一条命令在
  Windows 本机（IOCP 时序不同）能拿到 1,304 字节完整回包。⇒ **同一段 shell 在两个面上
  行为不同**，用它当判据就是造一把"忽红忽绿"的尺子。
  本脚本用 Popen + 读线程 + 显式等待条件（等到收齐期望 id 或超时），
  与 eval/tests/test_mcp_server.py::TestStdioHandshake 同一套机制——那套在 Linux runner 上实测绿。

用法:
  python scripts/mcp_stdio_smoke.py --server /path/to/fenjue-mcp
  python scripts/mcp_stdio_smoke.py --server "python eval/mcp_server.py"   # 带空格的命令串
退出码: 0=握手与工具齐全 / 1=缺应答或缺工具（打印 stderr 尾部与回包字节数供归因）/ 2=参数或启动问题
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import threading
import time

EXPECTED_TOOLS = {"route_skill", "list_skills", "hitrate_report"}
INIT = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "smoke", "version": "0"}}})
READY = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
LIST = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})


def _frames(cmd: str) -> list[str]:
    """拆命令串。Windows 必须用 posix=False：默认 posix 模式会把反斜杠当转义符吃掉，
    一个绝对解释器路径进去，出来就成了一段丢了所有分隔符的连写串
    （实测 doctor 因此起不来服务）。这不是格式化偏好而是平台语义差异，
    所以按平台分档而不是硬写一种。此处刻意不写盘符字面量：本仓的 path-hygiene 棘轮
    会拦跟踪文件里的盘符路径，而这条注释不需要它也能讲清发生了什么。"""
    return shlex.split(cmd, posix=(sys.platform != "win32")) if " " in cmd.strip() else [cmd]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True, help="MCP 服务可执行文件路径，或带参数的命令串")
    ap.add_argument("--server-arg", action="append", default=[],
                    help="追加给服务的参数，可重复；优先用它而不是把参数拼进 --server 字符串"
                         "（拼接要过 shlex，路径里的空格与反斜杠在两个平台上语义不同，实测会吞）")
    ap.add_argument("--wait", type=float, default=60.0, help="收齐应答的等待上限（秒）")
    args = ap.parse_args()

    argv = _frames(args.server) + list(args.server_arg)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace")
    except OSError as exc:
        print(f"[FATAL] 起不来服务：{argv}（{exc}）", file=sys.stderr)
        return 2

    replies: dict = {}
    stderr_tail: list[str] = []

    def pump(stream, is_stdout):
        for raw in stream:
            if not is_stdout:
                stderr_tail.append(raw)
                continue
            raw = raw.strip()
            if raw.startswith("{"):
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if obj.get("id") is not None:
                    replies[obj["id"]] = obj

    threads = [threading.Thread(target=pump, args=(proc.stdout, True), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, False), daemon=True)]
    for t in threads:
        t.start()

    why = []
    try:
        for frame in (INIT, READY, LIST):
            proc.stdin.write(frame + "\n")
            proc.stdin.flush()
        deadline = time.time() + args.wait
        while time.time() < deadline and 1 not in replies:
            time.sleep(0.2)
        if 1 in replies:
            deadline = time.time() + args.wait
            while time.time() < deadline and 2 not in replies:
                time.sleep(0.2)
    except (BrokenPipeError, ValueError) as exc:
        why.append(f"写帧失败：{exc}")
    finally:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    fail = "".join(stderr_tail)[-500:]
    if 1 not in replies:
        print(f"[FATAL] initialize 无应答（服务没回 protocolVersion）。stderr 尾部：{fail}", file=sys.stderr)
        return 1
    if "protocolVersion" not in json.dumps(replies[1]):
        print("[FATAL] initialize 应答里没有 protocolVersion，握手未成立", file=sys.stderr)
        return 1
    if 2 not in replies:
        print(f"[FATAL] tools/list 无应答。stderr 尾部：{fail}", file=sys.stderr)
        return 1
    names = {t.get("name") for t in replies[2].get("result", {}).get("tools", [])}
    if not EXPECTED_TOOLS <= names:
        print(f"[FATAL] 工具不齐：期望 {sorted(EXPECTED_TOOLS)}，实测 {sorted(n for n in names if n)}",
              file=sys.stderr)
        return 1
    print(f"[GATE:mcp-smoke-pass] 工具 {len(names)} 个、握手往返齐全（server={args.server}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
