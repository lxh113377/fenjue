#!/usr/bin/env python3
"""Temp/ 临时沙盒目录清理脚本（对应 CODE_REVIEW.md §8 临时目录治理）。

背景
----
`Temp/` 被定义为**一次性实验沙盒**：禁止进入任何 PR（由 CI job
`block-temp-changes` 强制拦截），并需要**每月整体清空**，避免实验性代码
（`eval` / 基于 shell 解释器的子进程调用 / 系统命令执行 等高危写法）长期沉淀、
腐化仓库并误导后续审查。

本脚本即该「月度清空」节奏的执行工具。

安全设计
--------
默认 **dry-run**：只统计并打印待清理文件数与总体积，不做任何删除。
只有显式传入 ``--confirm`` 才会真正执行删除，且**只清空 `Temp/` 的内容，
保留 `Temp/` 目录本身**（保证沙盒随时可用、路径不失效）。

用法
----
    python scripts/cleanup_temp.py              # 预演：只看不删
    python scripts/cleanup_temp.py --confirm    # 真正清空 Temp/ 内容
    python scripts/cleanup_temp.py --help       # 查看帮助
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

#: 仓库根目录（本文件位于 <repo>/scripts/cleanup_temp.py）
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

#: 受治理的临时沙盒目录名
TEMP_DIR_NAME: str = "Temp"


def human_size(num_bytes: int) -> str:
    """把字节数格式化为人类可读字符串。

    Args:
        num_bytes: 字节数，非负整数。

    Returns:
        形如 ``"1.23 MB"`` 的字符串；小于 1 KB 时以 ``B`` 为单位。
    """
    size: float = float(max(num_bytes, 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{size:.2f} TB"


def scan_temp(temp_dir: Path) -> tuple[list[Path], int]:
    """递归统计 `Temp/` 下的全部文件及总大小。

    Args:
        temp_dir: `Temp/` 目录的绝对路径。

    Returns:
        二元组 ``(files, total_bytes)``：
        ``files`` 为目录下所有普通文件的路径列表（已排序，便于稳定输出）；
        ``total_bytes`` 为这些文件的字节数之和。无法读取大小的文件按 0 计。
    """
    files: list[Path] = []
    total_bytes: int = 0
    if not temp_dir.is_dir():
        return files, total_bytes

    for path in sorted(temp_dir.rglob("*")):
        if not path.is_file():
            continue
        files.append(path)
        try:
            total_bytes += path.stat().st_size
        except OSError:
            # 符号链接失效 / 权限不足等：计入文件数但不计体积，不中断统计。
            continue
    return files, total_bytes


def purge_temp(temp_dir: Path) -> tuple[int, list[str]]:
    """清空 `Temp/` 内的所有条目，但保留 `Temp/` 目录本身。

    Args:
        temp_dir: `Temp/` 目录的绝对路径。

    Returns:
        二元组 ``(removed_count, errors)``：
        ``removed_count`` 为成功删除的顶层条目数（文件或子目录各计 1）；
        ``errors`` 为删除失败的描述信息列表。
    """
    removed_count: int = 0
    errors: list[str] = []

    for entry in sorted(temp_dir.iterdir()):
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            removed_count += 1
        except OSError as exc:
            errors.append(f"{entry}: {exc}")
    return removed_count, errors


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。

    Returns:
        已配置好 ``--confirm`` / ``--temp-dir`` 选项的解析器实例。
    """
    parser = argparse.ArgumentParser(
        prog="cleanup_temp.py",
        description=(
            "清理 Temp/ 一次性实验沙盒（CODE_REVIEW.md §8 月度清空节奏）。"
            "默认 dry-run 只统计不删除，加 --confirm 才真正清空。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("示例:\n  python scripts/cleanup_temp.py            # 预演，只打印统计\n"),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="真正执行删除（清空 Temp/ 内容，保留 Temp/ 目录本身）",
    )
    parser.add_argument(
        "--temp-dir",
        type=Path,
        default=REPO_ROOT / TEMP_DIR_NAME,
        help=f"指定临时目录路径（默认: <repo>/{TEMP_DIR_NAME}）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    Args:
        argv: 命令行参数列表（不含程序名）。为 ``None`` 时取 ``sys.argv[1:]``。

    Returns:
        进程退出码：0 表示成功（含 dry-run 与目录不存在），1 表示删除过程出错。
    """
    args = build_parser().parse_args(argv)
    temp_dir: Path = args.temp_dir.resolve()

    # GA-16: 防止 --temp-dir 指向仓库之外的路径导致误删系统文件
    if temp_dir == REPO_ROOT or not temp_dir.is_relative_to(REPO_ROOT):
        print(
            f"[拒绝] --temp-dir 必须位于仓库内且不能是仓库根本身: {temp_dir}",
            file=sys.stderr,
        )
        return 2

    print(f"目标目录: {temp_dir}")

    if not temp_dir.is_dir():
        print("目录不存在或不是目录，无需清理。")
        return 0

    files, total_bytes = scan_temp(temp_dir)
    top_level_count: int = len(list(temp_dir.iterdir()))

    print(f"待清理文件数: {len(files)}")
    print(f"顶层条目数:   {top_level_count}")
    print(f"总大小:       {human_size(total_bytes)}")

    if not args.confirm:
        print("\n[dry-run] 未做任何删除。")
        return 0

    if top_level_count == 0:
        print("\nTemp/ 已为空，无需清理。")
        return 0

    removed_count, errors = purge_temp(temp_dir)
    print(f"\n已删除顶层条目: {removed_count}")

    if errors:
        print(f"删除失败 {len(errors)} 项:")
        for message in errors:
            print(f"  - {message}")
        return 1

    print("Temp/ 已清空（目录本身保留）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
