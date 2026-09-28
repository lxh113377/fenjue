#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""decay_lessons.py — lessons 置信度衰减执行器（R211-1）。

补齐遗忘机制的缺失环节：A-get-memory 元字段定义了「30 天未命中 −0.1」衰减
规则，但此前无执行器（规则从未运转）。本脚本补上**只列不删**的衰减计算：
  - 默认 dry-run：输出衰减明细 + <0.3 遗忘候选清单，不写盘
  - --apply：把新置信度写回 lessons md（仅改置信度数字，条目永不删除）
  - 真删除仍走 T1（audit forget）/T3（周维护批量 retire）人工确认

衰减规则（与 A-get-memory 元字段口径一致）：
  - 初始 0.5；useful 命中 +0.2（上限 0.9，由 boost/record 侧负责，本脚本只减不加）
  - 自「最后命中日」起算，每满 30 天未命中 −0.1
  - 最后命中日来源：meta/lessons_usage.jsonl 的 loaded/used 记录（file#标题 前缀匹配）
  - 无 usage 记录的条目以条目自身「日期=」字段为基线起点

数据容错：usage 文件 utf-8-sig + 跳过 # 注释行与空行（schema 头实测混入）。

用法:
  python eval/decay_lessons.py                 # dry-run：只输出衰减报告
  python eval/decay_lessons.py --apply         # 写回置信度数字（条目永不删）
  python eval/decay_lessons.py --json          # 机器可读（周维护消费）
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path
from truth_constants import GLOBAL_MEMORY_ROOT  # noqa: E402

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(EVAL_DIR)
# 路径由单一定义点拼装（truth_constants.GLOBAL_MEMORY_ROOT），禁写盘符字面量（path_hygiene ratchet）
GM = os.environ.get("FENJUE_GLOBAL_MEMORY") or GLOBAL_MEMORY_ROOT
LESSONS_DIR = os.path.join(GM, "lessons")
USAGE_PATH = os.path.join(GM, "meta", "lessons_usage.jsonl")

WINDOW_DAYS = 30
STEP = 0.1
CANDIDATE_BELOW = 0.3

ENTRY_RE = re.compile(r"^### \[(\d{4}-\d{2}-\d{2})\] ([^\n]+)")
CONF_RE = re.compile(r"(置信度=)([0-9.]+)")
DATE_RE = re.compile(r"日期=(\d{4}-\d{2}-\d{2})")


def _lesson_files() -> list[str]:
    out = []
    for fn in sorted(os.listdir(LESSONS_DIR)):
        if fn.endswith(".md") and (fn.startswith("lessons.") or fn.startswith("lessons-")):
            if "archive" in fn or "index" in fn:
                continue
            out.append(os.path.join(LESSONS_DIR, fn))
    return out


def parse_entries() -> list[dict]:
    """扫描全部分卷，返回 [{file, line_no, date, title, confidence, entry_key}]。"""
    entries = []
    for path in _lesson_files():
        fn = os.path.basename(path)
        cur = None
        with Path(path).open(encoding="utf-8", errors="replace") as _f:
            for i, line in enumerate(_f, 1):
                m = ENTRY_RE.match(line)
                if m:
                    cur = {"file": fn, "line_no": i, "date": m.group(1),
                           "title": m.group(2).strip(), "confidence": None,
                           "entry_key": f"{fn}#{m.group(2).strip()}"}
                    entries.append(cur)
                    continue
                if cur is not None:
                    cm = CONF_RE.search(line)
                    if cm and cur["confidence"] is None:
                        cur["confidence"] = float(cm.group(2))
                        cur["conf_line_no"] = i
                        cur["conf_line"] = line.rstrip("\n")
                        dm = DATE_RE.search(line)
                        if dm and not cur.get("meta_date"):
                            cur["meta_date"] = dm.group(1)
    return entries


def last_hit_dates() -> dict[str, str]:
    """从 usage.jsonl 汇总每条目的最后命中日期（entry_key 前缀匹配）。"""
    last: dict[str, str] = {}
    if not os.path.exists(USAGE_PATH):
        return last
    raw = Path(USAGE_PATH).read_bytes().decode("utf-8-sig", errors="replace")
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            rec = json.loads(s)
        except json.JSONDecodeError:
            continue
        date = rec.get("date", "")
        if not date:
            continue
        for key in (rec.get("loaded") or []) + (rec.get("used") or []):
            k = str(key)
            if k not in last or date > last[k]:
                last[k] = date
    return last


def _match_last(entry_key: str, last: dict[str, str]) -> str | None:
    if entry_key in last:
        return last[entry_key]
    prefix = entry_key.split("#", 1)[-1][:12]
    for k, d in last.items():
        if k.split("#", 1)[-1].startswith(prefix):
            return d
    return None


def decay_report(apply: bool = False) -> dict:
    today = datetime.date.today()
    entries = parse_entries()
    last = last_hit_dates()
    report = {"decayed": [], "candidates": [], "untracked": 0, "total": len(entries)}
    for e in entries:
        if e.get("confidence") is None:
            report["untracked"] += 1
            continue
        hit = _match_last(e["entry_key"], last) or e.get("meta_date") or e["date"]
        try:
            hit_d = datetime.date.fromisoformat(hit)
        except ValueError:
            continue
        idle = (today - hit_d).days
        steps = idle // WINDOW_DAYS
        if steps <= 0:
            continue
        new_conf = round(max(0.0, e["confidence"] - steps * STEP), 2)
        if new_conf >= e["confidence"]:
            continue
        item = {"entry": e["entry_key"], "idle_days": idle, "steps": steps,
                "old": e["confidence"], "new": new_conf,
                "last_hit": hit, "candidate": new_conf < CANDIDATE_BELOW}
        report["decayed"].append(item)
        if item["candidate"]:
            report["candidates"].append(item)
        if apply and e.get("conf_line_no"):
            new_line = CONF_RE.sub(f"置信度={new_conf}", e["conf_line"], count=1)
            path = os.path.join(LESSONS_DIR, e["file"])
            with Path(path).open(encoding="utf-8") as _f:
                all_lines = _f.readlines()
            all_lines[e["conf_line_no"] - 1] = new_line + "\n"
            # P1-6: 原子写（tmp+os.replace）——中途崩溃不再留下截断的 lessons 分卷
            tmp = Path(path + ".decaytmp")
            tmp.write_text("".join(all_lines), encoding="utf-8", newline="")
            os.replace(tmp, path)
    return report


def main() -> int:
    apply = "--apply" in sys.argv
    as_json = "--json" in sys.argv
    rep = decay_report(apply=apply)
    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0
    mode = "APPLY（已写回置信度）" if apply else "DRY-RUN（未写盘）"
    print(f"[decay-lessons] {mode} | 条目 {rep['total']} | 无置信度字段 {rep['untracked']}")
    for d in rep["decayed"]:
        tag = " 🗑️候选" if d["candidate"] else ""
        print(f"  - {d['entry'][:64]} 闲置{d['idle_days']}天 → {d['old']}→{d['new']}{tag}")
    print(f"[decay-lessons] 衰减 {len(rep['decayed'])} 条 | 遗忘候选(<0.3) {len(rep['candidates'])} 条"
          + ("（仅列出不删，删除走 T1 audit forget / T3 周维护）" if rep["candidates"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
