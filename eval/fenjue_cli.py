#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fenjue_cli.py — 统一入口 `fenjue`（易用性轴：一个命令、子命令、自检、可粘贴接入配置）。

为什么要有这个文件（第三轮对标取证结论 2026-09-29）：赛道官方描述明确「尤其关注**工具易用性**、
文档完善程度与实际使用案例」。本仓此前是三个分立的 console script（`fenjue-hitrate` /
`fenjue-bench` / `fenjue-mcp`），这是 gptme 那类样板仓的反面：它们有一个总命令 + `doctor` 自检 +
可复制的配置生成，用户装完不需要读源码就能问「我这台机器上到底哪条链是通的」。

子命令：
  fenjue --version                    版本（单源，见 _version）
  fenjue route "<原话>" [--top N]      一句查询的候选技能排序
  fenjue eval|bench|mcp                直接转调既有三个入口（参数原样透传）
  fenjue doctor [--json]               把随包分发的自检全部跑一遍，逐条给 rc
  fenjue mcp-config [--client X]       生成可直接粘贴的 agent 接入配置（JSON/TOML）

退出码：0=成功 / 1=有检查判红 / 2=前提缺失或零检查（零检查不得当成通过）
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def _version() -> tuple[str, str]:
    """版本单源：装了读分布元数据，源码树读 pyproject.toml；两处都有就必须相等。

    写成函数而不是常量，是因为本仓刚吃过一次同族的亏：同一个事实存两份（pyproject 里一份、
    模块里一份），改一处漏一处，最后由判据在 CI 上抓出来。这里宁可返回 UNVERIFIED 也不猜。
    """
    found: list[tuple[str, str]] = []
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            found.append(("dist-info", version("fenjue")))
        except PackageNotFoundError:
            pass
    except Exception as exc:  # 元数据后端本身坏掉也要如实报，不静默
        found.append(("dist-info-error", type(exc).__name__))
    pp = ROOT / "pyproject.toml"
    if pp.is_file():
        try:
            import tomllib

            found.append(("pyproject", tomllib.loads(pp.read_text(encoding="utf-8"))["project"]["version"]))
        except Exception as exc:
            found.append(("pyproject-error", type(exc).__name__))
    good = [(k, v) for k, v in found if not k.endswith("-error")]
    if not good:
        return "UNVERIFIED", found
    if len({v for _, v in good}) > 1:
        return "DRIFT:" + "|".join(f"{k}={v}" for k, v in found), found
    return good[0][1], found


def _run(argv: list[str], timeout: int = 150) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT), timeout=timeout)


def cmd_route(args) -> int:
    try:
        from .hitrate_cli import load_skills, score_matrix
    except ImportError:
        from hitrate_cli import load_skills, score_matrix
    skills = load_skills(args.skills_dir)
    if not skills:
        print(f"[FATAL] 技能清单为空（取数面 {args.skills_dir}）：零输入不返回空候选", file=sys.stderr)
        return 2
    sims = score_matrix(skills, [args.query])[0]
    ranked = sorted(({"name": s["name"], "score": round(float(v), 4)} for s, v in zip(skills, sims)),
                    key=lambda d: -d["score"])[: args.top]
    if args.json:
        print(json.dumps({"query": args.query, "candidates": ranked}, ensure_ascii=False, indent=2))
        return 0
    print(f"查询：{args.query}    技能库：{args.skills_dir}（{len(skills)} 个）")
    for i, c in enumerate(ranked, 1):
        print(f"  {i}. {c['name']}  score={c['score']}")
    return 0


def cmd_delegate(rest: list[str], script: str) -> int:
    proc = _run([PY, str(ROOT / "eval" / script), *rest], timeout=600)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-800:])
    print(f"[{script}] rc={proc.returncode}")
    return proc.returncode


def cmd_mcp(rest: list[str]) -> int:
    proc = _run([PY, str(ROOT / "eval" / "mcp_server.py"), *rest], timeout=600)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr[-800:])
    return proc.returncode


CHECKS = [
    ("public-clean-selftest", ["scripts/public_clean_check.py", "--selftest"]),
    ("doc-links", ["eval/check_doc_links.py"]),
    ("doc-claims", ["eval/doc_claim_face.py"]),
    ("command-face-parity", ["eval/command_face_parity.py"]),
    ("workflow-roster", ["scripts/ci_workflow_spec_check.py"]),
    ("hitrate-face", ["eval/hitrate_cli.py", "--skills-dir", "examples/skills",
                      "--queries", "examples/queries.json", "--top", "3"]),
    ("skills-md-face", ["eval/hitrate_cli.py", "--skills-dir", "examples/agent-skills/skills",
                        "--queries", "examples/agent-skills/queries.json", "--top", "3"]),
    ("bench-smoke", ["eval/bench_router.py", "--sizes", "12", "--queries", "4"]),
    ("mcp-handshake", ["scripts/mcp_stdio_smoke.py", "--server", PY,
                       "--server-arg", "eval/mcp_server.py"]),
]


def cmd_doctor(args) -> int:
    rows, skipped = [], []
    for name, rel in CHECKS:
        target = ROOT / rel[0]
        if not target.is_file():
            skipped.append((name, f"载体不在场：{rel[0]}"))
            continue
        if not str(rel[0]).endswith(".py"):
            argv = list(rel)
        else:
            argv = [PY, str(target)] + list(rel[1:])
        if name == "mcp-handshake" and not _has_mcp():
            skipped.append((name, '未安装可选依赖 mcp（pip install "mcp>=2.2,<3"）'))
            continue
        try:
            proc = _run(argv, timeout=200)
            rc = proc.returncode
            line = (proc.stdout.strip().splitlines() or [proc.stderr.strip()])[-1][:88]
        except subprocess.TimeoutExpired:
            rc, line = 124, "超时（>200s）未返回"
        rows.append({"check": name, "rc": rc, "output": line})
    if not rows:
        print("[FATAL] doctor 一条检查都没跑到：零检查不得当成通过", file=sys.stderr)
        for name, why in skipped:
            print(f"  跳过 {name}：{why}", file=sys.stderr)
        return 2
    bad = [r for r in rows if r["rc"] != 0]
    if args.json:
        print(json.dumps({"version": _version()[0], "checks": rows,
                          "skipped": [{"check": n, "reason": w} for n, w in skipped]},
                         ensure_ascii=False, indent=2))
    else:
        print(f"fenjue doctor · 版本={_version()[0]} · 取数面={ROOT}")
        for r in rows:
            flag = "ok " if r["rc"] == 0 else "FAIL"
            print(f"  [{flag}] {r['check']:<22} rc={r['rc']}  {r['output']}")
        for name, why in skipped:
            print(f"  [skip] {name:<22} {why}")
        print(f"合计：跑 {len(rows)} 项，红 {len(bad)} 项，跳过 {len(skipped)} 项（跳过带原因，不计入通过）")
    if bad:
        print("[GATE:doctor-fail] 有检查判红，逐条见上", file=sys.stderr)
        return 1
    # --json 时结论行走 stderr：stdout 必须是单一 JSON 文档，否则机器读者拿到的是
    # "JSON + 一行尾巴"，json.loads 报 Extra data —— 判据的回执不能自毁自己的解析面。
    print("[GATE:doctor-pass]", file=sys.stderr if args.json else sys.stdout)
    return 0


def _has_mcp() -> bool:
    try:
        import mcp.server.mcpserver  # noqa: F401
        return True
    except Exception:
        return False


CLIENTS = {"claude": "json", "generic": "json", "qoder": "json", "codex": "toml"}


def cmd_mcp_config(args) -> int:
    """输出可直接粘贴的配置，并如实说明这条命令是按「装好的」还是「源码树」生成的。

    两种形态的命令面不同（`fenjue-mcp` vs `python -m eval.mcp_server`），
    给一份不注明来源的配置就是让人照着跑不通。
    """
    if args.client not in CLIENTS:
        print(f"[FATAL] 未知 client={args.client!r}，可选：{sorted(CLIENTS)}", file=sys.stderr)
        return 2
    installed = shutil.which("fenjue-mcp")
    if installed:
        cmd, cargs, origin = installed, [], "装好的 console script fenjue-mcp"
    else:
        cmd, cargs, origin = PY, ["-m", "eval.mcp_server"], "源码树（python -m eval.mcp_server）"
    if CLIENTS[args.client] == "toml":
        rendered = '[mcp_servers.fenjue]\ncommand = "%s"\nargs = %s\n' % (cmd, json.dumps(cargs))
    else:
        rendered = json.dumps({"mcpServers": {"fenjue": {"command": cmd, "args": cargs}}},
                              ensure_ascii=False, indent=2) + "\n"
    sys.stdout.write(rendered)
    print(f"# 生成来源：{origin}；client={args.client}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="fenjue",
        description="记忆焚诀：技能路由与门禁的统一入口",
        epilog='示例：fenjue route "帮我把日志里的根因找出来" | fenjue doctor | fenjue mcp-config --client claude',
    )
    ap.add_argument("--version", action="store_true", help="打印版本（单源：分布元数据或 pyproject）")
    sub = ap.add_subparsers(dest="command")
    p_route = sub.add_parser("route", help="一句查询的候选技能排序")
    p_route.add_argument("query")
    p_route.add_argument("--top", type=int, default=3)
    p_route.add_argument("--skills-dir", type=Path, default=ROOT / "examples" / "skills")
    p_route.add_argument("--json", action="store_true")
    p_doctor = sub.add_parser("doctor", help="把随包自检全跑一遍，逐条给 rc（需仓树：载体在 scripts/ 与 examples/ 里）")
    p_doctor.add_argument("--json", action="store_true")
    p_cfg = sub.add_parser("mcp-config", help="生成可直接粘贴的 agent 接入配置")
    p_cfg.add_argument("--client", default="generic", choices=sorted(CLIENTS))
    for name in ("eval", "bench", "mcp", "hitrate"):
        sub.add_parser(name, help=f"转调 eval/ 下的既有入口 {name}")

    argv = list(sys.argv[1:] if argv is None else argv)
    args = ap.parse_args(argv)
    if args.version:
        ver, faces = _version()
        print(f"fenjue {ver}")
        print("# 取数面：" + ", ".join(f"{k}={v}" for k, v in faces), file=sys.stderr)
        return 0 if not ver.startswith(("UNVERIFIED", "DRIFT")) else 2
    if args.command == "route":
        return cmd_route(args)
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "mcp-config":
        return cmd_mcp_config(args)
    if args.command in ("eval", "hitrate"):
        return cmd_delegate(argv[1:], "hitrate_cli.py")
    if args.command == "bench":
        return cmd_delegate(argv[1:], "bench_router.py")
    if args.command == "mcp":
        return cmd_mcp(argv[1:])
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
