#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inject_source_guard.py — L1 注入预算「源头侧」快检（对标轮四 P0-17，治 D-28）。

病灶：C25 在**下游焚诀仓**判总量，但增长源在 `<SKILLS_ROOT>` 仓，而该仓 `.git/hooks`
只有 post-commit 没有 pre-commit ⇒ 一次技能版本发布（V10.68.0/V10.69.0，+3000B）在提交
当时零校验，红只在下游爆且不可归因。本快检把校验搬到写入点：谁的提交把预算推过线，谁当场被拦。

不误伤并行会话的语义纪律：**只拦「让预算变差的那一次提交」**。
  · 与注入文件无关的提交（总量不变）→ 放行
  · 瘦身提交（总量下降）→ 放行，即使当前已处于存量红中（否则没人能修好它）
  · 把总量从基线内推过基线 / 已在基线上仍继续叠加 → 拒，并给出经台账留痕的出路
  · 破硬顶（65536）→ 无条件拒（天花板不随基线移动）
用法（供 global_skills 等增长源仓的 pre-commit 调用）：
  python "C:/.../焚诀/eval/inject_source_guard.py" --repo "$(git rev-parse --show-toplevel)"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVAL_DIR)
HEADROOM_WARN_RATIO = 0.05
DISABLE_ENV = "FENJUE_SOURCE_GUARD"


def _norm(path: str) -> str:
    return os.path.normpath(path).replace("\\", "/").rstrip("/").lower()


_WIN_ABS = re.compile(r"^[A-Za-z]:[\\/]")


def _is_abs(path: str) -> bool:
    """D-42：`D:/...` 在 Windows 上是绝对路径，在 POSIX 上 `os.path.isabs` 判 False
    ⇒ 同一份注入清单在 CI（ubuntu）会被当成"相对治理仓根"再拼一次前缀，
    `_in_repo` 两侧口径不再一致，本仓文件被误判成外仓文件（blob 态 → 盘面态）。
    驱动器号形式在两个平台都必须当绝对路径处理。"""
    return bool(os.path.isabs(path) or _WIN_ABS.match(path))


def _abs(repo_root: str, path: str) -> str:
    """truth_constants 里的相对路径一律相对焚诀治理仓根（与 C25 同一解析口径）。"""
    return path if _is_abs(path) else os.path.join(ROOT, path)


def _in_repo(repo_root: str, path: str) -> bool:
    """判断注入文件是否属于本次提交所在仓（只有本仓文件才随提交态变化）。
    两侧必须过同一个 `_abs` 归一，否则跨平台口径漂移（D-42）。"""
    root = _norm(_abs(repo_root, repo_root))
    p = _norm(_abs(repo_root, path))
    return p == root or p.startswith(root + "/")


def _rel(repo_root: str, path: str) -> str:
    return os.path.relpath(_abs(repo_root, path), repo_root).replace("\\", "/")


def decide(head_total: int, staged_total: int, baseline: int, hard_cap: int):
    """返回 (allow, level, detail)。纯函数，供桩与测试直接注入夹具。"""
    room = hard_cap - staged_total
    pct = 100.0 * room / hard_cap if hard_cap else 0.0
    tail = " | 基线 %d / 硬顶 %d / 余量 %d（%.1f%%）" % (baseline, hard_cap, room, pct)
    if staged_total > hard_cap:
        return (False, "block-cap",
                "破硬顶：HEAD %d → staged %d > hard_cap %d（天花板不随基线移动）"
                % (head_total, staged_total, hard_cap))
    worse = staged_total > head_total
    if staged_total > baseline and worse:
        return (False, "block-baseline",
                "本次提交把 L1 注入区推过/继续叠加于棘轮基线：HEAD %d → staged %d > baseline %d。"
                "出路二选一：①瘦身/拆 references 侧车；②确属必要增长则留痕移动基线 "
                "`python eval/inject_ledger.py --record --decision applied --actor-repo <仓> "
                "--actor-commit <sha> --cause <因由> --baseline-before %d --baseline-after <新值>`"
                % (head_total, staged_total, baseline, baseline))
    warn = "" if pct >= HEADROOM_WARN_RATIO * 100 else " | ⚠ 余量 <5%，再有一次增长即破硬顶"
    level = "ok" if staged_total == head_total else ("shrink" if staged_total < head_total else "grow")
    return (True, level,
            "源头快检通过：%s HEAD %d → staged %d%s" % (level, head_total, staged_total, tail + warn))


def _git_blob_size(repo_root: str, rev: str, rel: str):
    r = subprocess.run(["git", "-C", repo_root, "cat-file", "-s", "%s:%s" % (rev, rel)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None  # 该态下不存在（首提交新增文件）
    try:
        return int(r.stdout.strip())
    except ValueError:
        return None


def measure(repo_root: str, files: list, rev: str, blob_size=None, disk_size=None) -> int:
    """按某一提交态汇总注入区字节：本仓文件取该态 blob，外仓文件读盘面（本次提交改不到）。"""
    blob_size = blob_size or (lambda rv, rl: _git_blob_size(repo_root, rv, rl))
    disk_size = disk_size or (lambda p: os.path.getsize(p) if os.path.exists(p) else 0)
    total = 0
    for f in files:
        path = f["path"]
        if _in_repo(repo_root, path):
            size = blob_size(rev, _rel(repo_root, path))
            total += int(size or 0)
        else:
            total += int(disk_size(path))
    return total


def run(repo_root: str) -> int:
    if os.environ.get(DISABLE_ENV, "").strip().lower() in ("0", "false", "no", "off"):
        print("[source-guard] 已由 %s=0 关闭，跳过" % DISABLE_ENV)
        return 0
    sys.path.insert(0, EVAL_DIR)
    try:
        import json as _json
        cfg = _json.load(open(os.path.join(EVAL_DIR, "truth_constants.json"), encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print("[source-guard] 读不到 truth_constants（非治理仓环境）→ 放行：%s" % e)
        return 0
    b = cfg.get("inject_budget") or {}
    files, baseline, cap = b.get("files") or [], b.get("baseline_bytes"), b.get("hard_cap_bytes")
    if not files or not baseline or not cap:
        print("[source-guard] 配置缺失（files=%d baseline=%r cap=%r）→ 放行" % (len(files), baseline, cap))
        return 0
    head = measure(repo_root, files, "HEAD")
    staged = measure(repo_root, files, ":0")
    allow, level, detail = decide(head, staged, baseline, cap)
    print("[source-guard] %s | %s" % ("PASS" if allow else "REJECT", detail))
    return 0 if allow else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="L1 注入预算源头侧快检")
    ap.add_argument("--repo", default=os.getcwd())
    ap.add_argument("--json", action="store_true", help="仅打印配置摘要")
    a = ap.parse_args(argv)
    if a.json:
        sys.path.insert(0, EVAL_DIR)
        cfg = json.load(open(os.path.join(EVAL_DIR, "truth_constants.json"), encoding="utf-8"))
        print(json.dumps(cfg.get("inject_budget", {}), ensure_ascii=False)[:400])
        return 0
    return run(os.path.abspath(a.repo))


if __name__ == "__main__":
    sys.exit(main())
