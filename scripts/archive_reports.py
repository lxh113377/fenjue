#!/usr/bin/env python3
"""reports/ 留存期治理脚本（对应 CODE_REVIEW_MASTER §8.4 留存期治理）。

背景
----
`reports/` 根目录只允许保留「当月」报告（.md/.json），跨月报告必须按月归档到
`reports/YYYY-MM/` 子目录，避免根级平铺堆积（2026-08-09 实测根级 100+ 文件）。

本脚本即该「月度归档」节奏的执行工具：
- 文件名内嵌日期（2026-07-11 / 20260711 / 2026_07）优先解析；
- 文件名无日期时按文件 mtime 的月份兜底；
- 只处理 reports/ 根级的 .md/.json（子目录不动、非目标扩展名不动）。

安全设计
--------
默认 dry-run：只打印将移动的文件清单，不做任何移动。
只有显式传入 ``--apply`` 才会真正执行移动；``--check`` 供门禁断言使用，
根级存在非当月 .md/.json 时返回非 0（fail-closed 判红）。
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path

#: 仓库根目录（本文件位于 <repo>/scripts/archive_reports.py）
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

#: 受治理的报告目录
REPORTS_DIR: Path = REPO_ROOT / "reports"

#: 目标扩展名（.partN 分卷后缀仍以 .md/.json 结尾，天然覆盖）
TARGET_SUFFIXES: tuple[str, ...] = (".md", ".json")

#: 文件名内嵌日期：2026-07-11 / 20260711 / 2026_07 均可命中
DATE_IN_NAME_RE: re.Pattern[str] = re.compile(r"(20\d{2})[-_.]?(\d{1,2})")


def month_from_name(name: str) -> str | None:
    """从文件名解析月份；无合法日期返回 None。"""
    match = DATE_IN_NAME_RE.search(name)
    if match is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if 1 <= month <= 12:
        return f"{year:04d}-{month:02d}"
    return None


def root_report_files(reports_dir: Path) -> list[Path]:
    """返回 reports/ 根级全部目标文件（.md/.json，含分卷 .partN）。"""
    if not reports_dir.is_dir():
        return []
    return sorted(p for p in reports_dir.iterdir() if p.is_file() and p.suffix in TARGET_SUFFIXES)


def target_month(path: Path, current_month: str) -> str:
    """解析文件归属月份（文件名优先，mtime 兜底）。"""
    month = month_from_name(path.name)
    if month is not None:
        return month
    try:
        return date.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m")
    except OSError:
        # 无法读取 mtime 时视为当月，避免误移动不可读文件
        return current_month


def collect_pending(reports_dir: Path, current_month: str) -> list[tuple[Path, str]]:
    """返回 [(文件, 目标月份)]，仅含需要归档的非当月根级文件。"""
    pending: list[tuple[Path, str]] = []
    for path in root_report_files(reports_dir):
        month = target_month(path, current_month)
        if month != current_month:
            pending.append((path, month))
    return pending


def cmd_check(reports_dir: Path, current_month: str) -> int:
    """门禁断言：根级存在非当月 .md/.json 时返回 1。"""
    pending = collect_pending(reports_dir, current_month)
    if not pending:
        print(f"OK: reports/ 根级无非当月 .md/.json（当前月 {current_month}）")
        return 0
    print(f"reports/ 根级存在 {len(pending)} 个非当月文件（当前月 {current_month}）:")
    for path, month in pending:
        print(f"  [{month}] {path.name}")
    print("处置: python scripts/archive_reports.py   # dry-run 预览")
    print("      python scripts/archive_reports.py --apply")
    return 1


def cmd_apply(reports_dir: Path, current_month: str, dry_run: bool) -> int:
    """执行归档（dry_run=True 时只预览）。"""
    pending = collect_pending(reports_dir, current_month)
    if not pending:
        print("无需归档：reports/ 根级无非当月 .md/.json")
        return 0
    for path, month in pending:
        dest = reports_dir / month / path.name
        if dry_run:
            print(f"  [预览:移动] {path.name} -> reports/{month}/")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        print(f"  [移动] {path.name} -> reports/{month}/")
    if dry_run:
        print("\ndry-run：未移动任何文件（加 --apply 才真正归档）")
    else:
        print(f"\n已归档 {len(pending)} 个文件")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="archive_reports.py",
        description=(
            "reports/ 留存期治理：根级非当月 .md/.json 按月归档到 "
            "reports/YYYY-MM/。默认 dry-run，--apply 才真正移动。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python scripts/archive_reports.py           # 预览，只看不移动\n"
            "  python scripts/archive_reports.py --apply   # 真正归档\n"
            "  python scripts/archive_reports.py --check   # 门禁断言（非0=有积压）\n"
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="门禁断言模式：有非当月文件返回 1（fail-closed）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="真正执行归档（默认只 dry-run 预览）",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=REPORTS_DIR,
        help="指定 reports 目录（默认: <repo>/reports）",
    )
    parser.add_argument(
        "--current-month",
        default=date.today().strftime("%Y-%m"),
        help="当前月份（默认取系统日期，格式 YYYY-MM）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """脚本入口。"""
    args = build_parser().parse_args(argv)
    reports_dir: Path = args.reports_dir.resolve()
    current_month: str = args.current_month
    if args.check:
        return cmd_check(reports_dir, current_month)
    return cmd_apply(reports_dir, current_month, dry_run=not args.apply)


if __name__ == "__main__":
    sys.exit(main())
