#!/usr/bin/env python3
r"""clear_cache.py — scorecard .cache/ 安全清理 (P1-2 落地产物)

设计:
  - 默认 dry-run: 列出会清的文件, 不真删 (老大已确认)
  - 写锁互斥: 检测 .cache/scorecard.lock, 锁存在则拒绝 (防 scorecard 跑到一半被清)
  - 真删留痕: 清单写 archive/cache-cleanup-YYYY-MM-DD.log, 可追
  - 不递归子目录: 只清 .cache/*.json, 不动 eval/.memory_pread_cache/

用法:
  python eval/scripts/clear_cache.py                       # dry-run, 列出会清的 1 个文件
  python eval/scripts/clear_cache.py --yes                 # 真清
  python eval/scripts/clear_cache.py --tag triple_diff     # 选清 (单 tag)
  python eval/scripts/clear_cache.py --tag A --tag B       # 选清 (多 tag, OR 关系)
  python eval/scripts/clear_cache.py --older-than 7d       # 清 7 天前的 (按 mtime)
  python eval/scripts/clear_cache.py --yes --older-than 7d # 真清 7 天前

退出码:
  0  - 成功 (dry-run 列完 或 真删完成)
  1  - 写锁被占, 拒绝
  2  - 参数错
  3  - 删失败 (部分文件删不动)
"""

import argparse
import datetime as _dt
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent  # eval/scripts/ -> eval/ -> repo
CACHE_DIR = REPO / ".cache"
LOCK_FILE = CACHE_DIR / "scorecard.lock"
ARCHIVE_DIR = REPO / "archive"


def _acquire_lock_or_die() -> None:
    """写锁互斥 — 锁存在且 < 30 分钟则拒绝, 避免清到一半被 scorecard 写入.
    P1-2 设计: 复用 R193 教训的 30 分钟心跳窗口."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        age_min = (time.time() - LOCK_FILE.stat().st_mtime) / 60.0
        if age_min < 30:
            print(f"[clear_cache] REFUSE: 写锁被占 ({LOCK_FILE}, {age_min:.1f} 分钟前).", file=sys.stderr)
            print("             30 分钟内拒绝清, 防 scorecard 跑到一半被清.", file=sys.stderr)
            print("             强清请先删 .cache/scorecard.lock.", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"[clear_cache] WARN: 锁存在 {age_min:.1f} 分钟, 视为 stale 强清.")
            LOCK_FILE.unlink(missing_ok=True)


def _parse_older_than(spec: str) -> float:
    """支持 7d / 24h / 60m 格式, 返回 cutoff 时间戳 (早于这个的会被清)."""
    spec = spec.strip().lower()
    if not spec:
        return 0.0
    unit = spec[-1]
    try:
        n = int(spec[:-1])
    except ValueError as exc:
        raise ValueError(f"无效 --older-than 格式: {spec!r} (期望 7d / 24h / 60m)") from exc
    now = time.time()
    if unit == "d":
        return now - n * 86400
    if unit == "h":
        return now - n * 3600
    if unit == "m":
        return now - n * 60
    raise ValueError(f"无效单位 {unit!r} (期望 d/h/m)")


def _list_targets(tags: list[str], cutoff: float) -> list[Path]:
    """列出会清的文件: .cache/*.json, 满足 tag 过滤 AND mtime > cutoff.
    空 tags = 不过滤 tag."""
    if not CACHE_DIR.is_dir():
        return []
    targets: list[Path] = []
    for p in sorted(CACHE_DIR.glob("*.json")):
        if p.name == "scorecard.lock":  # 锁文件永远不清
            continue
        if tags:
            # 文件名格式: {tag}-{key}.json, tag 是第一个 - 前的部分
            stem = p.stem  # 去掉 .json
            tag = stem.split("-", 1)[0] if "-" in stem else stem
            if tag not in tags:
                continue
        if cutoff > 0 and p.stat().st_mtime > cutoff:
            continue
        targets.append(p)
    return targets


def _archive_log(deleted: list[Path]) -> Path:
    """把真删清单写到 archive/cache-cleanup-YYYY-MM-DD.log."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()
    log_path = ARCHIVE_DIR / f"cache-cleanup-{today}.log"
    ts = _dt.datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"\n--- {ts} (clear_cache.py) ---\n")
        for p in deleted:
            f.write(f"  {p.relative_to(REPO)}\n")
    return log_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="scorecard .cache/ 安全清理 (默认 dry-run, --yes 才真删)"
    )
    parser.add_argument("--yes", action="store_true", help="真删, 默认 dry-run")
    parser.add_argument(
        "--tag", action="append", default=[], help="只清指定 tag (可多次, OR 关系)"
    )
    parser.add_argument(
        "--older-than", default="", help="清 mtime 早于这个时长的 (例 7d / 24h / 60m)"
    )
    args = parser.parse_args(argv)

    # 参数校验
    try:
        cutoff = _parse_older_than(args.older_than)
    except ValueError as exc:
        print(f"[clear_cache] ERROR: {exc}", file=sys.stderr)
        return 2

    # 写锁互斥
    _acquire_lock_or_die()

    # 列目标
    targets = _list_targets(args.tag, cutoff)
    if not targets:
        print("[clear_cache] 无目标文件 (.cache/ 为空 或 tag/mtime 过滤后为空)")
        return 0

    # 输出
    print(f"[clear_cache] 找到 {len(targets)} 个文件:")
    for p in targets:
        size = p.stat().st_size
        mtime = _dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
        print(f"  {p.name}  ({size} bytes, mtime={mtime})")

    if not args.yes:
        print("")
        print("[clear_cache] DRY-RUN: 未真删. 加 --yes 真正执行.")
        return 0

    # 真删
    print("")
    print(f"[clear_cache] 真删 {len(targets)} 个文件...")
    deleted: list[Path] = []
    failed: list[Path] = []
    for p in targets:
        try:
            p.unlink()
            deleted.append(p)
            print(f"  [OK] 删 {p.name}")
        except OSError as exc:
            failed.append(p)
            print(f"  [FAIL] {p.name}: {exc}", file=sys.stderr)

    if failed:
        print(f"[clear_cache] {len(failed)} 个文件删失败", file=sys.stderr)
        return 3

    # 归档
    log = _archive_log(deleted)
    print(f"[clear_cache] 归档: {log.relative_to(REPO)}")
    print(f"[clear_cache] DONE: 删 {len(deleted)}, 留 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
