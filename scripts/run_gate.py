#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_gate.py — CI 闸门包装器（item 9 可观测性的数据来源）

功能:
  1) 运行一条 shell 命令，把 {slug, command, exit_code, status, ts} 落到
     ci-results/<slug>.json（即使命令失败也落盘，供 summary 聚合）。
  2) 保留命令原始退出码 -> CI 步骤仍按 fail-closed 失败。
  3) --verdict 模式: 检查 ci-results/ 是否存在 status=fail，有则 exit 1。
     R212: 支持 --expect slug... 声明「必须跑过的闸门」——缺失记录文件
     （闸门硬崩/未落 json）同样判 FAIL，杜绝「闸门根本没跑但绿」的假绿。

用法（在 ci.yml `run:` 中，命令整体用引号包裹）:
  python scripts/run_gate.py pytest "python -m pytest eval/tests -q -p no:cacheprovider --junit-xml=pytest-report.xml"
  python scripts/run_gate.py --verdict --expect pytest truth
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RESULTS = os.path.join(REPO_ROOT, "ci-results")

# 无人值守入口（Windows 计划任务）要跑的闸门登记表。登记两处作用，都是本轮实测逼出来的：
#   1) 命令串只写一份，ps1 侧不再和这里各抄一遍（抄两遍必漂移）；
#   2) `eval/wiring_census.py` 认 `python (eval|scripts)/x.py` 这条形态 ⇒ 只被计划任务
#      拉起的工具，原先在接线率普查里永远是"未接线"（链闭包里看不到 .ps1 的调用串）。
# 执行时开头的 `python` 换成 sys.executable：计划任务的 PATH ≠ 交互 shell 的 PATH，
# 裸 python 会无人值守地失败（同仓 snapshot_global_memory.ps1:31 已按此教训钉绝对路径）。
TASK_CMDS = {
    "ci-panel": "python scripts/ci_panel_report.py",
}


def task_tokens(slug: str) -> list:
    import shlex
    tokens = shlex.split(TASK_CMDS[slug])
    if tokens and tokens[0].split(os.path.sep)[-1].startswith("python"):
        tokens[0] = sys.executable
    return tokens


def main() -> int:
    ap = argparse.ArgumentParser(description="CI gate wrapper")
    ap.add_argument("slug", nargs="?")
    ap.add_argument("command", nargs="*")
    ap.add_argument("--verdict", action="store_true", help="只检查 ci-results 是否有 fail")
    ap.add_argument("--results-dir", default=DEFAULT_RESULTS)
    ap.add_argument("--expect", nargs="*", default=None,
                    help="必须存在记录文件的闸门 slug（缺失记录 → 判 FAIL）")
    ap.add_argument("--task", choices=sorted(TASK_CMDS), default=None,
                    help="跑 TASK_CMDS 登记的无人值守闸门（计划任务入口，命令串只此一份）")
    args = ap.parse_args()

    os.makedirs(args.results_dir, exist_ok=True)
    task_cmd = task_tokens(args.task) if args.task else None
    if args.task:
        args.slug = args.task

    if args.verdict:
        fails = []
        present: set[str] = set()
        for fn in sorted(os.listdir(args.results_dir)):
            if not fn.endswith(".json"):
                continue
            try:
                d = json.loads(Path(os.path.join(args.results_dir, fn)).read_text(encoding="utf-8"))
            except Exception:
                continue
            slug = d.get("slug", fn[:-5])
            present.add(slug)
            if d.get("status") == "fail":
                fails.append(slug)
        if args.expect is not None:
            missing = sorted(set(args.expect) - present)
            if missing:
                fails.append(f"缺失闸门记录: {', '.join(missing)}")
        if fails:
            print(f"[VERDICT] FAIL — {'; '.join(fails)}")
            return 1
        print("[VERDICT] PASS — 所有记录闸门通过")
        return 0

    if not args.slug or (not args.command and task_cmd is None):
        ap.error("需要 slug 与 command（command 用引号包裹），或 --task <已登记 slug>")
    slug = args.slug
    cmd = " ".join(task_cmd) if task_cmd else " ".join(args.command)
    out_path = os.path.join(args.results_dir, f"{slug}.json")

    # R206-02: 关闭 shell 解释面——shlex 拆分后以 list 形式执行（shell=False），
    # 消除 shell 元字符注入（cli.yml 传入的命令/参数不再被 shell 二次解释）。
    # ci.yml 现有 8 处调用均为无复合符的简单命令；如需 shell 复合（&&/||/变量
    # 展开），请在 ci.yml 侧拆步执行，不在本包装器重新打开 shell。
    import shlex
    # D-81（对标轮十五）：闸门必须自带"全文输出可被指到"的出口。
    # 病根实测：pre-commit 只 tail -25，闸链在 pytest 之后还打印自己的汇总，FAILED 摘要被挤出
    # 窗口 ⇒ 我连续三轮把"钩子说红却指不出红在哪"当成环境噪声，做了 3×20 分钟的上下文对照
    # 实验，而真凶一直安静地躺在 /tmp/fenjue_pch.log 里。规则写在人脑里等于没写，落成产物字段。
    log_dir = Path(args.results_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{slug}.log"
    try:
        # 任务入口直接吃已解析好的 token：`" ".join` 再 `shlex.split` 会把带空格的解释器
        # 绝对路径（C:\Program Files\...）劈成两段 —— 这类往返拼接正是路径被吞的成因。
        cmd_tokens = task_cmd if task_cmd else shlex.split(cmd)
        proc = subprocess.run(cmd_tokens, shell=False, timeout=1800,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace")  # P1-6: 兜底 timeout
        rc, output = proc.returncode, proc.stdout or ""
    except ValueError as e:
        rc, output = 2, f"命令解析失败已拒绝执行: {e}"
    except subprocess.TimeoutExpired as e:
        rc, output = 124, f"闸链超时被终止（>1800s）: {(e.stdout or '')[-2000:]}"
    # 全文落盘（尾部 2MB 足够定位），并保留在 stdout 上原样回显，CI/人工都能直接看
    try:
        log_path.write_text(output[-2_000_000:], encoding="utf-8")
    except OSError:
        pass
    sys.stdout.write(output)
    sys.stdout.flush()
    result = {
        "slug": slug,
        "command": cmd,
        "exit_code": rc,
        "status": "pass" if rc == 0 else "fail",
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "log": str(log_path),
        "log_bytes": len(output.encode("utf-8", "replace")),
    }
    Path(out_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[GATE {slug}] {'PASS' if rc == 0 else 'FAIL'} (exit={rc})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
