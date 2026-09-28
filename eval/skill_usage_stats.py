#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill_usage_stats.py — 工具/skill 使用频率统计（R196，覆盖-2 / 三.1）

聚合 route_trace.jsonl + llm_decisions.jsonl + feedback.jsonl，输出每个 skill
的调用频次，并给出「绑定表降级候选」（低频 skill 建议按需加载，不做自动修改）。

说明（P0#9 日志声明≠文件存在）：07 曾记录「eval/tool_usage_sampler.py 已新建
（fenjue-tool-usage-v1）」，磁盘实测不存在；本文件为当前唯一实现。

分母口径（轮六 D-33/D-37/D-38 三次收口，写在这里免得下一个人再猜）：
  1) `route_trace.jsonl` 只算 `src=production`（缺 src 的旧行按 production 保守计），
     adversarial/regression 为测试自流量并显式披露排除量；
  2) `llm_decisions.jsonl` 无 src 字段，且最新一行停在 2026-08-11 ⇒ 默认按**归档输入**
     排除在分母外（`--include-archive` 可回滚旧口径）；
  3) `--json` 的 stdout 只放 JSON，人读披露行进 `disclosures` 字段。

用法:
  python eval/skill_usage_stats.py [--json] [--threshold 3] [--traffic production|all]
                                   [--include-archive] [--archive-after-days 30]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from collections import Counter

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)

ROUTE_TRACE_REL = os.path.join("eval", "route_trace.jsonl")

# 只有这些 src 算测试自流量（D-38：黑名单会把 L3 真实回写 llm_decision 一起误排除）
TEST_SOURCES = frozenset({"adversarial", "regression"})
LLM_DECISIONS_REL = os.path.join("eval", "llm_decisions.jsonl")
FEEDBACK_REL = os.path.join("feedback", "feedback.jsonl")


def _read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def count_trace_rows(rows: list[dict], traffic: str = "production") -> tuple:
    """按来源过滤 route_trace 后统计 top1 次数。

    对标轮六 D-33：trace 里 adversarial/regression 是**测试自流量**（实测占 7,809 行中的
    5,526 行 = 71%），不过滤会让主线⑥的使用率分母被合成流量撑大，"低频候选"判定随之失真。
    缺 src 字段的旧行按 production 对待（宁可少排除，不可静默丢真实调用）。
    返回 (计数, 各来源被排除行数)。

    D-38 续：判定用**测试来源白名单**而非"非 production 即排除"——`unified_router.py` 里
    L3 消歧回写用的是 `src='llm_decision'`，那是真实调用；按黑名单它会被当成测试流量静默
    掉出分母，且和 adversarial 混在同一行披露里。未知新来源一律保守计入。
    """
    counter: Counter[str] = Counter()
    excluded: Counter[str] = Counter()
    for row in rows:
        src = row.get("src") or "production"
        if traffic == "production" and src in TEST_SOURCES:
            excluded[src] += 1
            continue
        top1 = row.get("top1")
        if top1:
            counter[top1] += 1
    return counter, excluded


def collect_llm_resolutions(rows: list[dict]) -> tuple:
    """汇总 L3 决策日志的 resolution，并记录每个名字的首末出现日期。

    对标轮六 D-35/D-37：`llm_decisions.jsonl` 实测**没有 src 字段**（键只有
    candidates/query/reason/resolution/ts），所以 D-33 的流量过滤对它不可用；
    注册表外名字（残影）全部来自这一路，且集中在技能退役**之前**的日期 ——
    没有日期跨度就没法区分"路由今天还在送退役名"与"昨天的合法记录今天看像鬼"。
    返回 (计数, {name: (first_day, last_day)})。
    """
    counter: Counter[str] = Counter()
    span: dict[str, tuple] = {}
    for row in rows:
        res = row.get("resolution")
        if not res:
            continue
        counter[res] += 1
        day = str(row.get("ts") or "")[:10]
        if len(day) == 10:
            lo, hi = span.get(res, (day, day))
            span[res] = (min(lo, day), max(hi, day))
    return counter, span


def newest_day(rows: list[dict]) -> str:
    """输入面最新日期（YYYY-MM-DD）；无可用 ts 返回空串。

    对标轮六 D-38：`llm_decisions.jsonl` 实测 3,286 行全部停在 2026-08-11（已被
    `route_trace.jsonl` 的 `src=llm_decision` 通道取代），**45 天没再被写过**，却仍占着
    使用率分母的 70%。一个死掉的历史面继续参与"哪些技能该降级"的判定，与 D-34 的
    vacuous 指标同族——所以要按新鲜度分箱，而不是把归档当现役。
    """
    days = [str(r.get("ts") or "")[:10] for r in rows]
    days = [d for d in days if len(d) == 10]
    return max(days) if days else ""


def is_archived(newest: str, today: str, after_days: int) -> bool:
    """最新一行距今超过 after_days ⇒ 判为归档输入（无日期信息按归档处理，宁保守）。"""
    if not newest:
        return True
    try:
        d1 = datetime.date.fromisoformat(newest)
        d2 = datetime.date.fromisoformat(today)
    except ValueError:
        return True
    return (d2 - d1).days > after_days


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="skill 使用频率统计（R196）")
    p.add_argument("--json", action="store_true")
    p.add_argument("--threshold", type=int, default=3,
                   help="低于该次数视为低频（降级候选），默认 3")
    p.add_argument("--traffic", choices=("production", "all"), default="production",
                   help="route_trace 来源口径：默认只算 production；all 仅供排查自流量占比")
    p.add_argument("--include-archive", action="store_true",
                   help="把归档输入（如已停写的 llm_decisions.jsonl）算回分母，回滚 D-38 前旧口径")
    p.add_argument("--archive-after-days", type=int, default=30,
                   help="输入面最新一行超过该天数即判为归档，默认 30")
    args = p.parse_args(argv)

    counter: Counter[str] = Counter()
    per_source: Counter[str] = Counter()
    notes: list[str] = []          # 人读披露行；--json 时一条都不许进 stdout（D-37）
    trace_counter, excluded = count_trace_rows(
        _read_jsonl(os.path.join(PROJECT_DIR, ROUTE_TRACE_REL)), args.traffic)
    counter.update(trace_counter)
    per_source["route_trace"] = sum(trace_counter.values())
    trace_ghost = dict(trace_counter)   # 未过滤副本：判定残影是否来自**生产路由**的唯一依据
    if excluded:
        total = sum(excluded.values())
        notes.append("[skill_usage] 已排除测试自流量 %d 行（占该文件 %.1f%%）: %s"
                     % (total, 100.0 * total / max(total + sum(trace_counter.values()), 1),
                        ", ".join("%s=%d" % kv for kv in sorted(excluded.items()))))
    llm_rows = _read_jsonl(os.path.join(PROJECT_DIR, LLM_DECISIONS_REL))
    llm_counter, llm_span = collect_llm_resolutions(llm_rows)
    llm_newest = newest_day(llm_rows)
    llm_archived = (not args.include_archive) and is_archived(
        llm_newest, datetime.date.today().isoformat(), args.archive_after_days)
    if llm_archived:
        per_source["llm_decisions_archive"] = sum(llm_counter.values())
        notes.append("[skill_usage] 分母按输入拆分: route_trace=%d（traffic=%s）；"
                     "llm_decisions=%d 行**已归档排除**（最新一行 %s，超 %d 天未再被写过；"
                     "该文件无 src 字段⇒自流量本不可辨识，D-37）；回滚旧口径用 --include-archive"
                     % (per_source["route_trace"], args.traffic,
                        per_source["llm_decisions_archive"], llm_newest or "无 ts",
                        args.archive_after_days))
    else:
        counter.update(llm_counter)
        per_source["llm_decisions"] = sum(llm_counter.values())
        notes.append("[skill_usage] 分母按输入拆分: route_trace=%d（traffic=%s）/ llm_decisions=%d"
                     "%s（该文件无 src 字段 ⇒ 自流量不可辨识，D-37，仅供残影审计）"
                     % (per_source["route_trace"], args.traffic, per_source["llm_decisions"],
                        "" if not llm_newest else "（最新 %s）" % llm_newest))
    feedback_rows = _read_jsonl(os.path.join(PROJECT_DIR, FEEDBACK_REL))
    feedback_categories = Counter(r.get("category", "其他") for r in feedback_rows)

    # R218 口径卫生：只统计注册表内技能。日志中的注册表外名字（已退役残影、
    # 解析坏值如 'A'/'NONE'）不进 seen 也不进低频候选；ghost 名单保留审计可见。
    # 注意 ghost 走 audit_counter（含已归档输入）而非 live counter：D-38 把归档踢出分母，
    # 但残影审计的价值恰恰在历史面，不能跟着一起失明。
    audit_counter: Counter[str] = Counter(trace_ghost)
    audit_counter.update(llm_counter)
    registry_path = os.path.join(PROJECT_DIR, "skill", "registry", "unified-skills-index.json")
    registry_filtered = False
    ghost_names: list[dict] = []

    def src_of(name: str) -> str:
        """残影出自哪路输入（两路都算到就标 both）——D-35 的归因结论靠这一列，不再靠猜。"""
        in_trace = bool(trace_ghost.get(name))
        in_llm = bool(llm_counter.get(name))
        return "both" if (in_trace and in_llm) else ("llm_decisions" if in_llm else "route_trace")
    try:
        with open(registry_path, encoding="utf-8") as fh:
            reg = set(json.load(fh).get("skills", {}))
        if reg:
            registry_filtered = True
            ghost = sorted(
                ((s, c) for s, c in audit_counter.items() if s not in reg),
                key=lambda t: (-t[1], t[0]))
            ghost_names = [{"name": s, "count": c, "source": src_of(s),
                            "in_live_denominator": s in counter,
                            "first_ts": (llm_span.get(s) or ("", ""))[0],
                            "last_ts": (llm_span.get(s) or ("", ""))[1]}
                           for s, c in ghost]
            counter = Counter({s: c for s, c in counter.items() if s in reg})
        else:
            print("[skill_usage] 警告: 注册表 skills 为空，保持未过滤口径", file=sys.stderr)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[skill_usage] 警告: 注册表不可读({exc})，保持未过滤口径", file=sys.stderr)

    low_freq = sorted(
        [s for s, c in counter.items() if c < args.threshold],
        key=lambda s: (counter[s], s))
    report = {
        "schema": "fenjue-skill-usage-v1",
        "threshold": args.threshold,
        "total_calls": sum(counter.values()),
        "skills_seen": len(counter),
        "per_skill": dict(counter.most_common()),
        "low_frequency_candidates": low_freq,
        "feedback_categories": dict(feedback_categories),
        "registry_filtered": registry_filtered,
        "per_source_calls": dict(per_source),
        "archived_inputs": {"llm_decisions": {
            "rows": sum(llm_counter.values()), "newest_ts_day": llm_newest,
            "excluded_from_denominator": llm_archived,
            "after_days": args.archive_after_days}},
        "disclosures": notes,
        "ghost_names": ghost_names,
        "note": ("低频候选仅供绑定表降级参考；绑定表改动需人工确认"
                 if registry_filtered else
                 "低频候选仅供绑定表降级参考；绑定表改动需人工确认；⚠️注册表不可读，未过滤口径（残影可能混入）"),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for line in notes:
            print(line)
        print(f"[skill_usage] 调用 {report['total_calls']} 次 / 涉及 {report['skills_seen']} 个 skill")
        for name, count in counter.most_common(15):
            print(f"  {name}: {count}")
        print(f"[skill_usage] 低频（<{args.threshold}）降级候选 {len(low_freq)} 个:")
        for name in low_freq[:20]:
            print(f"  - {name} ({counter[name]})")
        if ghost_names:
            print(f"[skill_usage] 已过滤注册表外名字 {len(ghost_names)} 个"
                  f"（共 {sum(g['count'] for g in ghost_names)} 次调用）:")
            for g in ghost_names[:10]:
                span = f" [{g['first_ts']}~{g['last_ts']}]" if g["first_ts"] else ""
                print(f"  ~ {g['name']} ({g['count']}) 来源={g['source']}{span}")
        print(f"[skill_usage] 反馈类别: {dict(feedback_categories)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
