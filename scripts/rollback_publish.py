#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rollback_publish.py — 发布回滚（item 10 失败预算/回滚点）

删除指定 GitHub Release（fail-closed：删除失败即 exit 1），释放 nightly 预发布
回滚点。配合 ci.yml 的 `rollback` job（workflow_dispatch 输入 tag）使用。
重新发布历史良好版本：手动/dispatch 再跑一次 deploy（从对应 commit/tag）。

依赖: gh CLI（GitHub 运行环境自带）+ GH_TOKEN。
"""
import argparse
import subprocess
import sys


def run(cmd):
    """R206-02: list 形式执行（shell=False）——tag 等 CLI/CI dispatch 输入只作
    字面参数传递，shell 元字符注入面归零（workflow_dispatch 输入可达此路径）。"""
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, shell=False, timeout=300).returncode  # P1-6: 兜底 timeout


def main() -> int:
    ap = argparse.ArgumentParser(description="发布回滚")
    ap.add_argument("--tag", required=True, help="要删除的 release 标签")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        print(f"[dry-run] 将删除 release: {args.tag}")
        return 0

    rc = run(["gh", "release", "delete", args.tag, "--yes"])
    if rc != 0:
        print("[rollback] 删除 release 失败")
        return 1
    # 删除远端 tag（保留 commit 历史，可重新基于该 commit 部署）
    # 原 shell 串里的 '|| true' 语义 = 删除失败不阻断回滚主流程，此处直接忽略返回码
    run(["git", "push", "--delete", "origin", args.tag])
    print(f"[rollback] 已删除 release {args.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
