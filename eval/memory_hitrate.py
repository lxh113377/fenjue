#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_hitrate.py — 焚诀记忆命中率量化追踪（R198 补漏-1 / memory.txt 四.1）

把"记忆检索命中率"从隐性变量变为可量化指标：
  命中率 = Σ(被使用条目) / Σ(被检索条目)

四类子命令：
  record    记录一次检索事件 {query, domain, retrieved[], used[]}
  report    聚合命中率（总/按域/趋势/未命中条目=遗忘候选）
  scan      静态分析 memory markdown：条目被跨文件引用次数 → 未引用=遗忘候选
  self-test 合成数据往返自检（不污染真实日志）

日志文件：与脚本同目录的 memory_hitrate_log.jsonl（*.jsonl 已被 .gitignore 忽略）

退出码：0 正常 / 1 空数据或异常 / 2 用法错误
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from config import GLOBAL_MEMORY  # P1-6 收口: 单源引用（env 可覆盖）

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
LOG_PATH = os.path.join(EVAL_DIR, "memory_hitrate_log.jsonl")

# 静态扫描时跳过的噪声目录
SKIP_DIRS = {".git", "_trash", "_temp", "_bak", "node_modules", "__pycache__",
             ".workbuddy", ".codex", "archive", "reports", "deliverables"}

# memory markdown 条目模式：## / ### 标题行
ENTRY_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")
# 跨文件引用线索：详见 / 见 `xxx.md` / 指向 partN.md
REF_RE = re.compile(r"(详见|见\s*[`']?|part\d+\.md|memory/[\w./]+\.md)")


def _now_iso():
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


def _append_log(event: dict) -> None:
    with Path(LOG_PATH).open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _load_log() -> list[dict]:
    if not os.path.exists(LOG_PATH):
        return []
    out = []
    with Path(LOG_PATH).open(encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return out


def cmd_record(args) -> int:
    query = (args.query or "").strip()
    if not query:
        print("[record] FAIL — --query 不能为空", file=sys.stderr)
        return 2
    domain = (args.domain or "unknown").strip()
    retrieved = [x.strip() for x in (args.retrieved or "").split(",") if x.strip()]
    used = [x.strip() for x in (args.used or "").split(",") if x.strip()]
    event = {
        "ts": _now_iso(),
        "query": query,
        "domain": domain,
        "retrieved": retrieved,
        "used": used,
    }
    _append_log(event)
    rate = (len(used) / len(retrieved)) if retrieved else 1.0
    print(f"[record] 已记录 domain={domain} retrieved={len(retrieved)} "
          f"used={len(used)} rate={rate:.2f}")
    return 0


def cmd_report(args) -> int:
    events = _load_log()
    if not events:
        print("[report] 无数据（先跑 record）。日志: " + LOG_PATH)
        return 1
    tot_ret, tot_used = 0, 0
    per_domain: dict[str, list[tuple[int, int]]] = {}
    all_retrieved, all_used = set(), set()
    for e in events:
        r, u = e.get("retrieved", []), e.get("used", [])
        tot_ret += len(r)
        tot_used += len(u)
        per_domain.setdefault(e.get("domain", "unknown"), []).append((len(r), len(u)))
        all_retrieved.update(r)
        all_used.update(u)
    overall = (tot_used / tot_ret) if tot_ret else 1.0
    # 从未被 used 命中过的检索条目 = 遗忘候选
    never_used = sorted(all_retrieved - all_used)
    out = {
        "schema": "fenjue-memory-hitrate-v1",
        "events": len(events),
        "retrieved_total": tot_ret,
        "used_total": tot_used,
        "overall_hit_rate": round(overall, 4),
        "per_domain": {
            d: {
                "events": len(v),
                "hit_rate": round(sum(u for _, u in v) / sum(r for r, _ in v), 4)
                if sum(r for r, _ in v) else 1.0,
            } for d, v in per_domain.items()
        },
        "never_used_candidates": never_used,
        "never_used_count": len(never_used),
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"[report] 事件数={out['events']}  检索条目={tot_ret}  使用条目={tot_used}")
        print(f"[report] 总体命中率 = {overall:.2%}")
        print("[report] 按域命中率:")
        for d, v in out["per_domain"].items():
            print(f"    - {d}: {v['hit_rate']:.2%}（{v['events']} 事件）")
        print(f"[report] 遗忘候选（检索过但从未被使用，{len(never_used)} 条）:")
        for x in never_used[:20]:
            print(f"    - {x}")
        if len(never_used) > 20:
            print(f"    ... 还有 {len(never_used) - 20} 条")
    return 0


def cmd_scan(args) -> int:
    roots = list(args.root or [])
    if args.project:
        roots.append(os.path.join(args.project, "memory"))
    if not roots:
        roots = [
            os.path.join(PROJECT_DIR, "memory"),
            GLOBAL_MEMORY,
        ]
    roots = [os.path.abspath(r) for r in roots if os.path.isdir(r)]
    if not roots:
        print("[scan] 无可用 memory 根目录", file=sys.stderr)
        return 1

    # 收集所有条目（标题）及其所属文件
    entries: list[tuple[str, str]] = []  # (heading_text, file_path)
    file_texts: dict[str, str] = {}
    for root in roots:
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in SKIP_DIRS]
            for f in fn:
                if not f.endswith(".md"):
                    continue
                fp = os.path.join(dp, f)
                try:
                    txt = Path(fp).read_text(encoding="utf-8")
                except OSError:
                    continue
                file_texts[fp] = txt
                for m in ENTRY_RE.finditer(txt):
                    entries.append((m.group(1).strip(), fp))

    # 判定每个条目是否被其他文件引用（标题文本出现在别处）
    cited = set()
    for heading, fp in entries:
        for other_fp, other_txt in file_texts.items():
            if other_fp == fp:
                continue
            if heading and heading in other_txt:
                cited.add(heading)
                break
    total = len(entries)
    uncited = [h for h, _ in entries if h not in cited]
    unused_ratio = (len(uncited) / total) if total else 0.0
    out = {
        "schema": "fenjue-memory-scan-v1",
        "roots": roots,
        "entries_total": total,
        "cited": len(cited),
        "uncited": len(uncited),
        "unused_ratio": round(unused_ratio, 4),
        "uncited_samples": uncited[:20],
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"[scan] 扫描根: {', '.join(roots)}")
        print(f"[scan] 条目总数={total}  被跨文件引用={len(cited)}  "
              f"未引用(遗忘候选)={len(uncited)}  未引用率={unused_ratio:.2%}")
        print("[scan] 未引用样本:")
        for h in uncited[:20]:
            print(f"    - {h}")
    return 0


def cmd_self_test(args) -> int:
    tmp = os.path.join(tempfile.gettempdir(), "mhr_selftest_log.jsonl")
    global LOG_PATH
    saved, LOG_PATH = LOG_PATH, tmp
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        # 模拟两次检索事件
        _append_log({"ts": _now_iso(), "query": "q1", "domain": "memory",
                     "retrieved": ["a", "b", "c"], "used": ["a", "c"]})
        _append_log({"ts": _now_iso(), "query": "q2", "domain": "code",
                     "retrieved": ["x", "y"], "used": ["x"]})
        events = _load_log()
        assert len(events) == 2, "事件数异常"
        tot_ret = sum(len(e["retrieved"]) for e in events)
        tot_used = sum(len(e["used"]) for e in events)
        assert tot_ret == 5 and tot_used == 3, "计数异常"
        rate = tot_used / tot_ret
        assert abs(rate - 0.6) < 1e-9, f"命中率计算异常: {rate}"
        all_ret = set().union(*[set(e["retrieved"]) for e in events])
        all_use = set().union(*[set(e["used"]) for e in events])
        never = all_ret - all_use
        assert never == {"b", "y"}, f"遗忘候选异常: {never}"
        print(f"[self-test] PASS ✅  事件=2 检索=5 使用=3 命中率={rate:.2%} "
              f"遗忘候选={sorted(never)}")
        return 0
    except AssertionError as e:
        print(f"[self-test] FAIL ❌ {e}", file=sys.stderr)
        return 1
    finally:
        LOG_PATH = saved
        if os.path.exists(tmp):
            os.remove(tmp)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="焚诀记忆命中率量化追踪（R198 补漏-1）")
    sub = p.add_subparsers(dest="cmd")

    pr = sub.add_parser("record", help="记录一次检索事件")
    pr.add_argument("--query", required=True)
    pr.add_argument("--domain", default="unknown")
    pr.add_argument("--retrieved", required=True, help="逗号分隔的检索条目 id")
    pr.add_argument("--used", default="", help="逗号分隔的被使用条目 id")

    sub.add_parser("report", help="聚合命中率报告").add_argument("--json", action="store_true")

    ps = sub.add_parser("scan", help="静态扫描记忆条目引用情况")
    ps.add_argument("--root", action="append", help="额外扫描根（可重复）")
    ps.add_argument("--project", default="")
    ps.add_argument("--json", action="store_true")

    sub.add_parser("self-test", help="合成数据往返自检")

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help(sys.stderr)
        return 2
    if args.cmd == "record":
        return cmd_record(args)
    if args.cmd == "report":
        return cmd_report(args)
    if args.cmd == "scan":
        return cmd_scan(args)
    if args.cmd == "self-test":
        return cmd_self_test(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
