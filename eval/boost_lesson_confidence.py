#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""boost_lesson_confidence.py — lessons 置信度强化闭环（R199，同类问题复现自动 +0.2）

机制（与 A-get-memory SKILL.md 元字段说明衔接）：
  - 新条目初始 置信度=0.5（Step 3 模板默认）
  - 每次命中「同类问题」→ 置信度 +0.2（上限 0.9），并在 lessons_usage.jsonl 写 useful=true
  - 每 30 天未命中 → 置信度 -0.1（<0.3 进 retire 候选，retire_policy R5）——由周维护/Step 9 执行
  - 本脚本负责「同类问题自动识别 + 强化」半边（衰减半边已在 A-get-memory Step 9）

「同类问题」判定（trigger 关键词匹配，可机械执行）：
  - 本次任务描述/错误串 与 目标条目 trigger 栏 任一关键词重合（精确子串匹配，大小写不敏感）
  - 时间窗口：仅当目标条目 日期 距今 ≤ 窗口天数（默认 30）内再次触发才强化（30 天后视为新周期）

用法：
  python eval/boost_lesson_confidence.py --lesson "<文件#标题>" --query "<本次问题/错误描述>"
  python eval/boost_lesson_confidence.py --lesson "<文件#标题>" --query "<...>" --force   # 跳过关键词判定直接 +0.2
  python eval/boost_lesson_confidence.py --lesson "<文件#标题>" --query "<...>" --window 60 --dry-run

输出：
  BOOST: <条目> 置信度 0.5 → 0.7（trigger 命中: watchdog）| lessons_usage 已标记 useful=true
  SKIP:  30 天内未复现同类问题 或 置信度已达上限 0.9

与现有结构衔接（不重复/不冲突）：
  - 读：lessons.partN.md 元字段（置信度=） + lessons_usage.jsonl（历史 useful 标记）
  - 写：lessons.partN.md（置信度字段 +0.2）+ lessons_usage.jsonl（追加 useful=true 行）
  - 与 record_lessons_usage.py 分工：该脚本记「加载/使用」侧，本脚本记「同类复现强化」侧；
    两者都追加 lessons_usage.jsonl，schema 兼容（本脚本行含 action=boost_confidence 字段区分）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, date
from pathlib import Path

from config import GLOBAL_MEMORY as _GM_ROOT  # P1-6 收口: 单源引用（env 可覆盖）

GLOBAL_MEMORY = Path(_GM_ROOT)
LESSONS_DIR = GLOBAL_MEMORY / "lessons"
USAGE_PATH = GLOBAL_MEMORY / "meta" / "lessons_usage.jsonl"

# 置信度字段正则（元字段行）
CONF_RE = re.compile(r"置信度=([\d.]+)")
# 日期字段正则（元字段行，YYYY-MM-DD）
DATE_RE = re.compile(r"日期=(\d{4}-\d{2}-\d{2})")
# 默认窗口：30 天（与 retire_policy R5「>30 天未命中」衔接）
DEFAULT_WINDOW = 30
# 强化步进与上限（与 A-get-memory 元字段说明一致）
BOOST_STEP = 0.2
BOOST_MAX = 0.9


def _find_lesson_file(lesson_ref: str) -> Path | None:
    """由「文件#标题」引用定位 lessons 文件（lessons.partN.md / lessons-p1-*.md）。"""
    fname = lesson_ref.split("#")[0]
    for cand in (LESSONS_DIR / fname, LESSONS_DIR / f"{fname}.md"):
        if cand.exists():
            return cand
    # 模糊匹配（标题子串）
    for p in LESSONS_DIR.glob("*.md"):
        if fname in p.name:
            return p
    return None


def _extract_trigger(lesson_file: Path, entry_title: str | None = None) -> str:
    """提取条目 trigger 行（trigger: xxx | yyy | zzz）。

    entry_title 非空 → 按标题定位该条目（支持同文件多条目，取标题后最近的 trigger 行）；
    否则取文件首个 trigger 行（单条目文件兼容）。
    """
    content = lesson_file.read_text(encoding="utf-8", errors="replace")
    if entry_title:
        lines = content.splitlines()
        for i, ln in enumerate(lines):
            if entry_title in ln:
                for sub in lines[i + 1:]:
                    m = re.match(r"^trigger:\s*(.+)$", sub.strip(), re.I)
                    if m:
                        return m.group(1).strip()
                return ""
    m = re.search(r"^trigger:\s*(.+)$", content, re.M | re.I)
    return m.group(1).strip() if m else ""


def _extract_meta(content: str) -> tuple[float | None, str | None]:
    """提取首个条目的 置信度 与 日期。"""
    conf = CONF_RE.search(content)
    dt = DATE_RE.search(content)
    return (float(conf.group(1)) if conf else None,
            dt.group(1) if dt else None)


def _trigger_hits(trigger: str, query: str) -> list[str]:
    """同类问题判定：query 与 trigger 关键词精确子串匹配（大小写不敏感）。"""
    q_low = query.lower()
    hits = []
    for part in re.split(r"[|｜]", trigger):
        kw = part.strip()
        if not kw or len(kw) < 2:
            continue
        if kw.lower() in q_low:
            hits.append(kw)
    return hits


def _within_window(entry_date: str, today: date, window: int) -> bool:
    """时间窗口：条目日期距今天 ≤ window 天。"""
    try:
        d = datetime.strptime(entry_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    return (today - d).days <= window


def _mark_usage(lesson_ref: str, query: str, trigger_hits: list[str]) -> None:
    """lessons_usage.jsonl 追加 useful=true 强化记录（action=boost_confidence 区分）。"""
    row = {
        "date": today_iso(),
        "session": "boost-confidence",
        "query": query[:200],
        "loaded": [lesson_ref],
        "used": [lesson_ref],
        "useful": "true",
        "improved_output": "yes",
        "action": "boost_confidence",
        "trigger_hits": trigger_hits,
    }
    USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(USAGE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def today_iso() -> str:
    return date.today().isoformat()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="lessons 置信度强化闭环（R199）：同类问题复现自动 +0.2 + useful 标记",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--lesson", required=True, help="条目引用（文件#标题）")
    ap.add_argument("--query", required=True, help="本次问题/错误描述（同类判定用）")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, help=f"时间窗口天数（默认 {DEFAULT_WINDOW}）")
    ap.add_argument("--force", action="store_true", help="跳过关键词判定直接 +0.2")
    ap.add_argument("--dry-run", action="store_true", help="只报告不写盘")
    args = ap.parse_args(argv)

    lesson_file = _find_lesson_file(args.lesson)
    if lesson_file is None:
        print(f"SKIP: 未找到条目文件（{args.lesson}）")
        return 1

    content = lesson_file.read_text(encoding="utf-8", errors="replace")
    conf, entry_date = _extract_meta(content)
    if conf is None:
        print(f"SKIP: 条目无置信度字段（{lesson_file.name}）——需先 backfill_confidence 归一化")
        return 1

    # 同类问题判定（#标题 → 定位该条目的 trigger，支持同文件多条目）
    title = args.lesson.split("#", 1)[1].strip() if "#" in args.lesson else None
    trigger = _extract_trigger(lesson_file, entry_title=title)
    hits = _trigger_hits(trigger, args.query) if not args.force else ["<force>"]
    if not hits:
        print("SKIP: 30 天窗口内未复现同类问题（query 未命中 trigger 关键词）")
        return 0

    # 时间窗口：30 天内再次触发才强化
    if entry_date and not _within_window(entry_date, date.today(), args.window):
        print(f"SKIP: 条目日期 {entry_date} 距今 >{args.window} 天（新周期，不再强化旧条目）")
        return 0

    # 上限保护
    if conf >= BOOST_MAX:
        print(f"SKIP: 置信度已达上限 {BOOST_MAX}（当前 {conf}）")
        return 0

    new_conf = round(min(conf + BOOST_STEP, BOOST_MAX), 1)
    if args.dry_run:
        print(f"DRY-RUN: {lesson_file.name} 置信度 {conf} → {new_conf}（trigger 命中: {hits}）")
        return 0

    # 写回置信度（元字段行原地替换）
    new_content = CONF_RE.sub(f"置信度={new_conf}", content, count=1)
    lesson_file.write_text(new_content, encoding="utf-8")
    # 写 useful 标记
    _mark_usage(args.lesson, args.query, hits)
    print(f"BOOST: {lesson_file.name} 置信度 {conf} → {new_conf}（trigger 命中: {hits}）| lessons_usage 已标记 useful=true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
