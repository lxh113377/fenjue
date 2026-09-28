#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_path_index_due.py — path_index 季度实测校验逾期检测 CLI（R199 机器强制化，2026-08-17）

定位：将周维护 Step 4m 的「季度状态逾期检测」从文档检查项升级为可机器强制的 CLI——
读取 `<MEMORY_ROOT>\\meta\\path_index.md` 的「季度实测校验状态」字段，与当前日期对比，
逾期即返回非零退出码，挂入 pre-commit 第 10 闸 `path-index-due`，使「逾期」在提交阶段即被拦截，
而非仅靠周维护报告事后发现（V3 式数据漂移潜伏 40 天的教训）。

退出码约定：
  0 = 未逾期（合规，或 == 下次日期当天——当天可执行校验，不算逾期）
  1 = 逾期（当前日期 > 下次日期，须执行 Step 4m 校验并更新状态字段）
  2 = 配置错误（状态字段缺失 / 日期无法解析 / path_index.md 不存在——需先修复，不静默通过）

逾期判定时间阈值：
  逾期 ⟺ 当前日期 > 下次日期（严格大于；等于下次日期当天允许执行校验，不拦截提交）

降级策略（缺失/损坏状态字段）：
  - 状态行缺失（无「季度实测校验状态」）→ exit 2，提示先建立状态（见 Step 4m）
  - 上次/下次日期缺失或格式非法（非 YYYY-MM-DD）→ exit 2，提示修复状态字段
  - path_index.md 不存在 → exit 2，提示路径表缺失
  降级一律 fail-closed（exit 2 拦截），防止「状态没建好却放行一切提交」。

用法：
  python eval/check_path_index_due.py            # 逾期检测（exit 0/1/2）
  python eval/check_path_index_due.py --json     # 机器可读（schema fenjue-check-path-index-due-v1）
  python eval/check_path_index_due.py --path <f> # 指定 path_index.md（测试/多环境）

回归测试：
  python -m pytest eval/tests/test_check_path_index_due.py -q
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

DEFAULT_PATH_INDEX = Path(r"<MEMORY_ROOT>\meta\path_index.md")
# 状态行锚点（path_index.md 顶部「季度实测校验状态」）
STATUS_ANCHOR = "季度实测校验状态"
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def parse_status(path: Path) -> dict:
    """解析 path_index.md 季度校验状态；返回 {ok, last, next, error}。

    - ok=False + error 说明：字段缺失 / 日期非法 / 文件不存在（降级 exit 2）。
    """
    if not path.exists():
        return {"ok": False, "last": None, "next": None,
                "error": f"path_index.md 不存在: {path}"}
    text = path.read_text(encoding="utf-8", errors="replace")
    if STATUS_ANCHOR not in text:
        return {"ok": False, "last": None, "next": None,
                "error": "状态字段缺失：path_index.md 未声明「季度实测校验状态」"
                         "（建立方法见周维护 Step 4m）"}
    line = next(ln for ln in text.splitlines() if STATUS_ANCHOR in ln)
    # 锚定「上次 =」/「下次 =」后的日期（findall 会误取「建立日期/V4 日期」等杂项）
    last_m = re.search(r"上次\s*=\s*(\d{4}-\d{2}-\d{2})", line)
    next_m = re.search(r"下次\s*=\s*(\d{4}-\d{2}-\d{2})", line)
    if not last_m or not next_m:
        return {"ok": False, "last": None, "next": None,
                "error": f"状态字段缺「上次 = / 下次 = YYYY-MM-DD」锚点: {line.strip()[:80]}"}
    last = datetime.date(*map(int, last_m.group(1).split("-")))
    nxt = datetime.date(*map(int, next_m.group(1).split("-")))
    return {"ok": True, "last": last, "next": nxt, "error": None}


def check_due(path: Path, today: datetime.date | None = None) -> dict:
    """逾期判定。返回 {status: ok|overdue|misconfig, exit_code, days, last, next, error}。"""
    today = today or datetime.date.today()
    st = parse_status(path)
    if not st["ok"]:
        return {"status": "misconfig", "exit_code": 2,
                "last": None, "next": None, "error": st["error"]}
    overdue = today > st["next"]  # 严格大于；=下次日期当天不算逾期（当天可校验）
    return {
        "status": "overdue" if overdue else "ok",
        "exit_code": 1 if overdue else 0,
        "last": st["last"].isoformat(),
        "next": st["next"].isoformat(),
        "days": (today - st["next"]).days if overdue else 0,
        "error": None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="path_index 季度实测校验逾期检测（R199 机器强制化）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--path", default=str(DEFAULT_PATH_INDEX),
                    help=f"指定 path_index.md（默认 {DEFAULT_PATH_INDEX}）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    r = check_due(Path(args.path))
    if args.json:
        print(json.dumps({
            "schema": "fenjue-check-path-index-due-v1",
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "status": r["status"],
            "exit_code": r["exit_code"],
            "last": r["last"],
            "next": r["next"],
            "days_overdue": r["days"],
            "error": r["error"],
        }, ensure_ascii=False, indent=2))
    else:
        if r["status"] == "ok":
            print(f"✅ path_index 季度校验未逾期（上次 {r['last']}，下次 {r['next']}）")
        elif r["status"] == "overdue":
            print(f"🔴 path_index 季度校验已逾期 {r['days']} 天（上次 {r['last']}，"
                  f"下次 {r['next']}）——须执行周维护 Step 4m 实测校验并更新状态字段")
        else:
            print(f"⚠️ {r['error']}")
    return r["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
