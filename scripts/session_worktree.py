#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session_worktree.py — 给单个会话开一块隔离工作树（对标轮五 P0-23 的 P1 配套）。

为什么需要：本仓是**多会话共享工作树**。pre-commit 第 1 闸跑的是全量 verify，输入是磁盘
当前态而不是本次改动面 ⇒ 任一会话的在途半成品都会让别人同时不可用（轮五实测 4 例，
当晚全靠归因器 `gate_scope_attribution.py` 记账放行）。归因器治的是"别替别人背锅"，
真正的隔离是**各干各的工作树**——`git worktree` 共享同一个 .git 对象库，成本是一个目录。

用法（脚本不替你 cd，只打印可直接执行的命令）：
    python scripts/session_worktree.py new --name r7-metric      # 建 + 打印进仓命令
    python scripts/session_worktree.py list
    python scripts/session_worktree.py rm --name r7-metric       # 有未提交改动会拒绝

安全边界（刻意为之）：
- 工作树建在**仓库同级**（`../<仓名>.wt/<name>`），不落在仓内，避免被噪声门禁判散落；
- 名字只允许 `[A-Za-z0-9._-]`，防路径穿越；
- `rm` 不带 `--force` 时先查 `git status --porcelain`，脏就不删；
- 不碰分支：默认 `--detach`，要固定分支用 `--branch`。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")


def wt_root(repo: str = REPO) -> str:
    """工作树总目录：仓库同级的 `<仓名>.wt`（在仓外，不进任何判据面）。"""
    parent = os.path.dirname(os.path.normpath(repo))
    return os.path.join(parent, os.path.basename(os.path.normpath(repo)) + ".wt")


def target(name: str, repo: str = REPO) -> str:
    """解析并校验工作树路径；名字非法或越界直接拒。"""
    if not NAME_RE.match(name or ""):
        raise ValueError("非法工作树名（只允许字母数字与 . _ -，1-40 字符，首字符非符号）: %r" % name)
    root = os.path.normpath(wt_root(repo))
    path = os.path.normpath(os.path.join(root, name))
    if os.path.commonpath([root, path]) != root or path == root:
        raise ValueError("工作树路径越出隔离根目录: %s" % path)
    return path


def _git(args, cwd=REPO):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def existing(repo: str = REPO) -> dict:
    """`git worktree list --porcelain` -> {path: branch}。"""
    r = _git(["worktree", "list", "--porcelain"], cwd=repo)
    out, path = {}, None
    for line in (r.stdout or "").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
            out[path] = ""
        elif line.startswith("branch ") and path:
            out[path] = line[len("branch "):].replace("refs/heads/", "")
    return out


def cmd_new(a) -> int:
    path = target(a.name, a.repo)
    if os.path.exists(path):
        print("[worktree] 已存在：%s" % path)
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if a.branch:
        args = ["worktree", "add", "-b", a.branch, path, a.base]
    else:
        args = ["worktree", "add", "--detach", path, a.base]
    r = _git(args, cwd=a.repo)
    if r.returncode != 0:
        print("[worktree] 创建失败：%s" % (r.stderr or r.stdout).strip()[:300])
        return 1
    print("[worktree] 已建：%s" % path)
    print("  cd \"%s\"" % path)
    print("  # 钩子经共用 .git 生效；本树里 junction 目录（memory/ 等）与 CI 产物不存在，")
    print("  # pre-commit 第 1 闸会自动按 --skip-external 降级运行（实测隔离树 24 PASS/0 FAIL/9 SKIP，")
    print("  # 主树全量 32 PASS/0 FAIL）。降级只在这棵树内生效，主工作树与 CI 仍跑全量判据。")
    return 0


def cmd_list(a) -> int:
    rows = existing(a.repo)
    if not rows:
        print("[worktree] 无工作树")
        return 0
    for path, branch in sorted(rows.items()):
        tag = "主仓" if os.path.normpath(path) == os.path.normpath(a.repo) else (branch or "detached")
        print("  %-10s %s" % (tag, path))
    return 0


def cmd_rm(a) -> int:
    path = target(a.name, a.repo)
    if not os.path.isdir(path):
        print("[worktree] 不存在：%s" % path)
        return 1
    if not a.force:
        r = _git(["status", "--porcelain"], cwd=path)
        if (r.stdout or "").strip():
            print("[worktree] 该工作树有未提交改动，拒绝删除（确认后用 --force）：")
            print("\n".join("  " + l for l in r.stdout.strip().splitlines()[:10]))
            return 1
    r = _git(["worktree", "remove", path], cwd=a.repo)
    if r.returncode != 0:
        print("[worktree] 删除失败：%s" % (r.stderr or r.stdout).strip()[:300])
        return 1
    _git(["worktree", "prune"], cwd=a.repo)
    print("[worktree] 已删除：%s" % path)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="会话隔离工作树（P0-23 配套）")
    p.add_argument("--repo", default=REPO)
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("--name", required=True)
    n.add_argument("--base", default="HEAD", help="起点 ref，默认 HEAD")
    n.add_argument("--branch", default="", help="要固定分支名时给定（会新建分支）")
    sub.add_parser("list")
    r = sub.add_parser("rm")
    r.add_argument("--name", required=True)
    r.add_argument("--force", action="store_true")
    a = p.parse_args(argv)
    return {"new": cmd_new, "list": cmd_list, "rm": cmd_rm}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
