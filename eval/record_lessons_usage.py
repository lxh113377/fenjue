# -*- coding: utf-8 -*-
"""record_lessons_usage.py — lessons 读侧使用自动记录（R170 真实使用闭环）

用法:
  python eval/record_lessons_usage.py --session <id> [--query "<本轮消息>"] \
      --loaded "lessons.partN.md#条目标题" [--loaded ...] \
      [--used "lessons.partN.md#条目标题"] [--useful true|false|unused] \
      [--improved yes|partial|no|unknown] \
      [--dry-run]

落盘: <MEMORY_ROOT>\\meta\\lessons_usage.jsonl（不存在则创建）
Schema: date/session/query/loaded/used/useful/improved_output
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from config import GLOBAL_MEMORY  # P1-6 收口: 单源引用（env 可覆盖）

USAGE_PATH = os.path.join(GLOBAL_MEMORY, "meta", "lessons_usage.jsonl")

# R219(R216-03 收尾): G5 声明行机器兜底——落账后往焚诀当日日志 append 声明行，
# 格式锚定 lessons_pread_audit.RE_PREAD/RE_SKILL/RE_MEM；日志不存在则跳过（零副作用）。
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def append_declaration(date_str, loaded, skills, mem_files):
    """R219: 声明行机器兜底落日志（行为断链治本，用户拍板方案 a）。

    - 三行独立判断：有内容才写对应行，格式严格匹配 audit 正则
    - 日志不存在 → 跳过并返回 False（不创建，不越界代开日志）
    - 追加前检查文件尾换行，防粘连（A-get-memory V4.22 Add-Content 教训）
    """
    log_path = os.path.join(PROJECT_DIR, ".workbuddy", "memory", date_str + ".md")
    if not os.path.exists(log_path):
        print(f"INFO: 当日日志不存在，跳过声明行落盘: {log_path}")
        return False
    lines = []
    if loaded:
        domains = sorted({p.split("#", 1)[0].replace("lessons-", "").replace(".md", "")
                          for p in loaded})
        lines.append(f"lessons预读: 命中{len(loaded)}条 (领域: {', '.join(domains)})")
    if skills:
        names = [s.strip() for s in skills if s.strip()]
        lines.append(f"skill加载: {len(names)}个 (清单: {', '.join(names)})")
    if mem_files:
        names = [m.strip() for m in mem_files if m.strip()]
        lines.append(f"记忆加载: 命中{len(names)}个 (文件: {', '.join(names)})")
    if not lines:
        return False
    try:
        _log = Path(log_path)
        tail = _log.read_text(encoding="utf-8")[-1:]
        with _log.open("a", encoding="utf-8") as f:
            if tail and tail != "\n":
                f.write("\n")
            f.write("\n".join(lines) + "\n")
    except OSError as e:
        print(f"WARN: 声明行写入失败（jsonl 主流程不受影响）: {e}")
        return False
    print(f"声明行已落日志: {log_path}（{len(lines)} 行）")
    return True


def main():
    ap = argparse.ArgumentParser(description="记录 lessons 读侧使用事件")
    ap.add_argument("--session", required=True, help="会话标识")
    ap.add_argument("--query", default="", help="本轮用户消息原文")
    ap.add_argument("--loaded", action="append", default=[], help="加载的条目（可多次）")
    ap.add_argument("--used", action="append", default=[], help="实际用上的条目（可多次）")
    ap.add_argument("--useful", choices=["true", "false", "unused"], default=None)
    ap.add_argument(
        "--improved",
        choices=["yes", "partial", "no", "unknown"],
        default=None,
        help="注入改善度自评（A-get-memory Step 1.5）：yes=直接指导决策/避免坑；"
             "partial=被参考但影响不明确；no=加载但未影响输出；unknown=未评估（历史回填默认）",
    )
    ap.add_argument("--dry-run", action="store_true", help="只打印不写入")
    ap.add_argument("--skills", default="",
                    help="R219: 本轮加载的 skill 清单（逗号分隔），非空则往当日日志落 skill加载 声明行")
    ap.add_argument("--mem-files", default="",
                    help="R219: 本轮加载的记忆文件（逗号分隔），非空则往当日日志落 记忆加载 声明行")
    args = ap.parse_args()

    useful = args.useful
    if useful is None:
        useful = "true" if args.used else "unused"
    if not args.loaded:
        print("WARN: --loaded 为空，本事件无加载条目（跳过写入）")
        return 0

    improved = args.improved or "unknown"
    record = {
        "date": date.today().isoformat(),
        "session": args.session,
        "query": args.query,
        "loaded": args.loaded,
        "used": args.used,
        "useful": useful,
        "improved_output": improved,
    }
    print("记录:", json.dumps(record, ensure_ascii=False))
    if args.dry_run:
        print("DRY-RUN: 未写入")
        return 0

    os.makedirs(os.path.dirname(USAGE_PATH), exist_ok=True)  # external-write-ok: lessons 读侧使用记录写 <MEMORY_ROOT>\meta\lessons_usage.jsonl（R170 读侧闭环，追加式）
    with open(USAGE_PATH, "a", encoding="utf-8") as f:  # external-write-ok: 同上
        f.write(json.dumps(record, ensure_ascii=False) + "\n")  # external-write-ok: 同上
    total = sum(1 for _ in open(USAGE_PATH, encoding="utf-8") if _.strip())
    print(f"已追加: {USAGE_PATH}（累计 {total} 条）")
    skills = [s for s in args.skills.split(",")] if args.skills else []
    mem_files = [m for m in args.mem_files.split(",")] if args.mem_files else []
    append_declaration(record["date"], args.loaded, skills, mem_files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
