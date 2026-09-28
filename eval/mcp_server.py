#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_server.py — 把本仓的路由与评估能力做成 Agent 可直接调用的 MCP 服务。

为什么要有这个文件（对标轮 2026-09-29 的实测缺口）：
  同类仓里 mem0 有 `integrations/`（395 个 blob）、basic-memory 自带 MCP 服务，
  装完就能被 Claude/其它 agent 当工具调；本仓此前**只有 CLI**，agent 想用这套路由
  必须自己 shell 出去解析 stdout。一个 agent 记忆系统自己接不进 agent 工作流，
  是形态上的自相矛盾。

能力面（三个工具，全部离线、零网络、零私有语料）:
  route_skill(query, top)  四层里 L2 语义层的打分与排序（TF-IDF 字符 n-gram）
  list_skills()            当前技能清单（名称 + 描述摘要）
  hitrate_report(top)      按难度分层跑一遍查询集，返回命中率读数

取数面由环境变量指定，默认指向仓内合成示例（保证 clone 完就能跑）:
  FENJUE_SKILLS_DIR   默认 <仓根>/examples/skills
  FENJUE_QUERIES_FILE 默认 <仓根>/examples/queries.json

启动（stdio）:
  python -m pip install "mcp>=2.2,<3"      # 可选依赖，见 pyproject [project.optional-dependencies]
  python eval/mcp_server.py

协议实现走官方 SDK（mcp 2.x 的 `mcp.server.mcpserver.MCPServer`），
不自造 JSON-RPC 帧——按本仓纪律，能用现成库就不造轮子。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from mcp.server.mcpserver import MCPServer
except ModuleNotFoundError as exc:  # 入口级失败要给得出路，不给栈
    sys.stderr.write(
        "[FATAL] 需要 MCP SDK：python -m pip install \"mcp>=2.2,<3\"\n"
        f"（原始错误：{exc}）\n"
    )
    raise SystemExit(2)

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "eval"))

try:  # 包内用相对导入（防同一模块双实例），直接跑脚本时退回绝对导入
    from .hitrate_cli import evaluate, load_skills, score_matrix
except ImportError:
    from hitrate_cli import evaluate, load_skills, score_matrix  # noqa: E402

SKILLS_DIR = Path(os.environ.get("FENJUE_SKILLS_DIR", _ROOT / "examples" / "skills"))
QUERIES_FILE = Path(os.environ.get("FENJUE_QUERIES_FILE", _ROOT / "examples" / "queries.json"))

mcp = MCPServer(
    "fenjue",
    instructions="多 Agent 技能路由与命中率评估。所有读数以仓内实际打分为准，不返回推测值。",
)


def _require_skills() -> list[dict]:
    skills = load_skills(SKILLS_DIR)
    if not skills:
        raise ValueError(f"技能清单为空（取数面 {SKILLS_DIR}）；零输入不得当成没有命中返回")
    return skills


@mcp.tool()
def list_skills() -> dict:
    """返回当前可路由的技能名与描述，供 agent 判断能力边界。"""
    skills = _require_skills()
    return {
        "skills_dir": str(SKILLS_DIR),
        "count": len(skills),
        "skills": [{"name": s["name"], "profile_head": s["profile"][:120]} for s in skills],
    }


@mcp.tool()
def route_skill(query: str, top: int = 3) -> dict:
    """给一句用户原话，返回按相似度排序的候选技能（含分数）。

    query 为用户查询原文；top 取 1..10，越界直接拒绝而不是静默截断。
    """
    if not query.strip():
        raise ValueError("query 为空，无法路由：返回空候选会被调用方读成没有合适技能")
    if not 1 <= top <= 10:
        raise ValueError(f"top 必须在 1..10，实测传入 {top}")
    skills = _require_skills()
    sims = score_matrix(skills, [query])[0]
    ranked = sorted(
        ({"name": s["name"], "score": round(float(v), 4)} for s, v in zip(skills, sims)),
        key=lambda d: -d["score"],
    )[:top]
    return {"query": query, "candidates": ranked, "n_skills": len(skills)}


@mcp.tool()
def hitrate_report(top: int = 3) -> dict:
    """在仓内查询集上跑一遍分层命中率评估，返回可直接引用的读数。"""
    if not QUERIES_FILE.is_file():
        raise ValueError(f"查询集不存在：{QUERIES_FILE}")
    import json
    cases = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    skills = _require_skills()
    res = evaluate(skills, cases, top=top)
    return {"skills_dir": str(SKILLS_DIR), "queries_file": str(QUERIES_FILE), **res}


def main() -> int:
    """stdio 服务入口（console script `fenjue-mcp` 指到这里）。阻塞至 stdin 关闭。"""
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
