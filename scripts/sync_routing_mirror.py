#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""sync_routing_mirror.py — 构建仓库内可挂载的路由体检镜像目录（item 13）

把 <MEMORY_ROOT>（或 FENJUE_GM_SOURCE / --source）中的「路由体检所需子集」
同步到仓库内 <dest>（默认 global_memory_mirror/），使 routing_health.py 不再依赖
本地绝对路径，可在 CI 中通过挂载/同步该目录周期化执行。

同步内容（仅子集，排除模型权重/字节码/归档）：
  skill_routing.md (+ .partN.md)
  skill_content/*.json
  meta/memory_index*.md (+ memory_index_full.md / path_index.md)
  meta/VERSION_LOCK*.md
  sync_health.json

用法:
  python scripts/sync_routing_mirror.py                      # 默认 source=junction, dest=global_memory_mirror
  python scripts/sync_routing_mirror.py --source <MEMORY_ROOT> --dest global_memory_mirror
  python scripts/sync_routing_mirror.py --dry-run            # 仅打印将复制的文件
"""
import argparse
import os
import shutil
import sys

DEFAULT_SOURCE = os.environ.get(
    "FENJUE_GM_SOURCE",
    r"<USER_HOME>\.workbuddy\memory_content",
)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sync_file(src, dst, dry_run):
    if dry_run:
        print(f"[dry] {src} -> {dst}")
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def main():
    ap = argparse.ArgumentParser(description="构建路由体检镜像目录")
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--dest", default=os.path.join(REPO, "global_memory_mirror"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = args.source
    if not os.path.isdir(src):
        print(f"[error] source 不存在: {src}")
        sys.exit(1)
    print(f"source={src}\ndest={args.dest}")

    copied = 0

    # skill_routing.md + 分卷
    for f in ["skill_routing.md"] + sorted(
        os.path.join(src, n) for n in os.listdir(src)
        if n.startswith("skill_routing.part") and n.endswith(".md")
    ):
        p = os.path.join(src, os.path.basename(f)) if not os.path.isabs(f) else f
        if os.path.exists(p):
            sync_file(p, os.path.join(args.dest, os.path.basename(p)), args.dry_run)
            copied += 1

    # skill_content/*.json（排除权重/索引副产物）
    sc = os.path.join(src, "skill_content")
    if os.path.isdir(sc):
        os.makedirs(os.path.join(args.dest, "skill_content"), exist_ok=True)
        for bn in os.listdir(sc):
            if bn.endswith(".json") and bn not in (
                "embeddings.npy", "skill_ids.json", "tfidf_matrix.npz", "tfidf_vectorizer.pkl"
            ):
                sync_file(os.path.join(sc, bn),
                          os.path.join(args.dest, "skill_content", bn), args.dry_run)
                copied += 1

    # meta 索引/版本文件
    meta = os.path.join(src, "meta")
    if os.path.isdir(meta):
        os.makedirs(os.path.join(args.dest, "meta"), exist_ok=True)
        for bn in os.listdir(meta):
            if (bn.startswith("memory_index") or bn.startswith("VERSION_LOCK")
                    or bn == "path_index.md") and bn.endswith(".md"):
                sync_file(os.path.join(meta, bn),
                          os.path.join(args.dest, "meta", bn), args.dry_run)
                copied += 1

    # sync_health.json（顶层）
    sh = os.path.join(src, "sync_health.json")
    if os.path.exists(sh):
        sync_file(sh, os.path.join(args.dest, "sync_health.json"), args.dry_run)
        copied += 1

    print(f"完成：将复制 {copied} 个文件" + ("（dry-run）" if args.dry_run else ""))
    if not args.dry_run:
        print(f"随后运行: python scripts/routing_health.py --root {args.dest}")


if __name__ == "__main__":
    main()
