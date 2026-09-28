#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""faces.py —— 所有"数量类断言"的**结构性枚举**唯一入口（对标轮十四 D-77）。

立规缘由（本人连续两轮实测翻车，都是同一形状）：
  ① 用 `git ls-files | grep -E '\\.partN\\.md$'` 数分卷件：默认 `core.quotepath=true` 把中文路径
     输出成带引号的八进制转义串，行尾多一个引号 ⇒ `$` 锚定全失配，实测 109 个只数到 79 个（D-69）；
  ② 用 `grep -l install_hooks ci.yml hooks/*` 判"这把锁有没有接线"：漏掉第 16 闸实际是
     `check_push_health() → push_health.hook_health()` 这条**函数调用**路径，据此写下"0 处引用"
     的结论是错的（D-74 自查）。
⇒ 计数不许用"关键词命中数"，必须来自结构枚举：git NUL 分隔清单 / YAML 步骤块 / 函数定义表 /
   注册表名单。本模块把这四类枚举收在一处，任何锁要数东西都从这里取，分母只有一个真相源。
"""
from __future__ import annotations

import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CI_YML = os.path.join(ROOT, ".github", "workflows", "ci.yml")
PRE_COMMIT = os.path.join(ROOT, "eval", "pre_commit_hooks.py")
VERIFY = os.path.join(ROOT, "eval", "verify_truth_consistency.py")


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def tracked_files(*patterns: str) -> list:
    """仓内 tracked 文件清单（NUL 分隔 + quotepath=off；中文路径不再漏）。"""
    args = ["git", "-c", "core.quotepath=off", "ls-files", "-z"]
    if patterns:
        args += ["--", *patterns]
    out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(f"git ls-files 失败: {(out.stderr or '').strip()[:120]}")
    return sorted(n.replace(os.sep, "/") for n in out.stdout.split("\0") if n)


def ci_expect_slugs() -> list:
    """`run_gate.py --expect` 名单（阻断链的正式分母，不是 grep 出来的闸名）。"""
    txt = _read(CI_YML)
    # 只认真那行 `--verdict ... --expect <slug 列表>`。注释段里也出现 --expect，
    # 先前按首次匹配抓到中文注释，得到 ['校验包装闸门均有记录文件——硬崩未落', ...] 这种垃圾
    # —— 本模块存在的意义正是让这类"枚举姿势错"变成可见的数（D-77 自照）。
    m = re.search(r"--verdict[^\n]*?--expect\s+([A-Za-z0-9 ._-]+)", txt)
    return sorted({s for s in m.group(1).split()
                   if re.fullmatch(r"[a-z0-9][a-z0-9-]*", s)}) if m else []


def ci_gate_slugs() -> list:
    """ci.yml 里实际调用 `run_gate.py <slug>` 的全部 slug（含观察档）。"""
    return sorted(set(re.findall(r"run_gate\.py\s+(?:--\S+\s+\S+\s+)?([a-z0-9][a-z0-9-]*)\s+\"python",
                                 _read(CI_YML))))


def local_gate_fns() -> list:
    """本地提交链的闸门函数名（结构 = `def check_*(...)`）。"""
    return sorted(set(re.findall(r"^def (check_[a-z0-9_]+)\(", _read(PRE_COMMIT), re.M)))


def local_gate_wired(fn: str, chain_files: dict | None = None) -> bool:
    """某把工具/函数是否真被链调用：按**调用表达式**判，不按工具名字面 grep。

    例：`install_hooks` 的接线证据是 `push_health.hook_health()`，而非 "install_hooks" 字样。
    所以传进来的 `needle` 允许是 lambda（对每条链文件正文做结构化判断），默认按标识符调用式匹配。
    """
    files = chain_files or {"ci.yml": _read(CI_YML), "pre_commit_hooks.py": _read(PRE_COMMIT),
                            "hooks/pre-commit": _read(os.path.join(ROOT, "eval", "hooks", "pre-commit"))}
    return any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(fn) + r"\s*\(", body or "")
               for body in files.values())


def verify_gate_ids() -> list:
    """verify 门禁 C1..Cn（结构 = GATES 表里逐行的 `'C%d'` 字面量）。"""
    return sorted({int(m) for m in re.findall(r"\('C(\d+)'", _read(VERIFY))})


def eval_tools() -> list:
    """`eval/` 下带 `main()` 的可执行判据（含 scripts/ 里的治理工具），作为接线率的分母。"""
    out = []
    for rel in tracked_files("eval/*.py", "scripts/*.py"):
        base = os.path.basename(rel)
        if base.startswith("test_") or rel.endswith("__init__.py"):
            continue
        p = os.path.join(ROOT, rel.replace("/", os.sep))
        try:
            if re.search(r"^def main\(", _read(p), re.M):
                out.append(rel)
        except OSError:
            continue
    return out


def summary() -> dict:
    return {"ci_expect": len(ci_expect_slugs()), "ci_gate_steps": len(ci_gate_slugs()),
            "local_gates": len(local_gate_fns()), "verify_gates": len(verify_gate_ids()),
            "eval_tools": len(eval_tools())}
