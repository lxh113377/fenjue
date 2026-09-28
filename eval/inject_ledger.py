#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inject_ledger.py — L1 注入硬预算的归因台账（对标轮四 7-E，治 D-22/D-28）。

为什么需要：C25 只判「实测和 ≤ 基线」，而基线本身是 `truth_constants.inject_budget` 里的
一个裸数字——任何人改一行就能让它"绿"。且注入面的**增长源在 global_skills 仓**（该仓无
pre-commit），消费面在焚诀仓，于是出现"我没动任何东西，门禁却红了且无法归因"。
本台账把基线移动变成**必须署名 + 必须给因由 + 硬顶不得随迁**的追加式账本；`--check`
即 verify 的 C31 判据面。

用法：
  python eval/inject_ledger.py --show
  python eval/inject_ledger.py --check
  python eval/inject_ledger.py --record --actor-repo global_skills --actor-commit 22990da \
      --cause "..." --decision pending            # 记账不抬基线（增长事件）
  python eval/inject_ledger.py --record ... --decision applied --baseline-after 64472
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EVAL_DIR)
from config import GLOBAL_SKILLS, GLOBAL_MEMORY  # noqa: E402
ROOT = os.path.dirname(EVAL_DIR)
LEDGER_PATH = os.path.join(EVAL_DIR, "inject_budget_ledger.jsonl")
INITIAL_HARD_CAP = 65536  # 立规即封死的天花板；台账任何条目不得高于它
MIN_CAUSE = 10
HEADROOM_WARN_RATIO = 0.05
# applied（改基线）的署名必须是可解析的历史提交 sha：实测台账里出现过 actor_commit="HEAD"，
# 那种署名在校验时点会指向任意提交，等于没有署名（P0-21 抽验清单的机制侧根治）
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}(\+[0-9a-fA-F]{7,40})*$")
# actor_repo -> 本地仓根（署名可核验）；不在表内的 repo 只查格式不查内容
ACTOR_REPO_DIRS = {"global_skills": GLOBAL_SKILLS, "global_memory": GLOBAL_MEMORY,
                   "fenjue": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}
# 注入面文件 basename（署名提交必须至少碰过其中之一，否则是"引了个无关 hash 过账"）
INJECT_BASENAMES = ("skill.md", "contract.md", "behavior_core.md", "agents.md",
                    "truth_constants.json", "inject_budget_ledger.jsonl")


def commit_touches_injection(actor_repo: str, actor_commit: str) -> bool | None:
    """True=该提交确实碰过注入面；False=引了无关 hash；None=无法核验（未知仓/复合标注/异机）。

    存在理由（2026-09-24 实测）：台账要求 actor_commit 非空，但**非空不等于相关**——
    一笔 applied 移动基线时引了只改日志的提交，判据当时全绿。故补此校验。
    """
    import subprocess
    sha = (actor_commit or "").strip()
    repo = ACTOR_REPO_DIRS.get(actor_repo)
    if repo is None or not os.path.isdir(repo) or "+" in sha or not sha:
        return None
    if not os.path.exists(os.path.join(repo, ".git")):
        return None
    try:
        r = subprocess.run(["git", "-C", repo, "show", "--name-only", "--format=", sha],
                           capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        return None
    if r.returncode != 0:
        return None  # hash 取不到（浅克隆/异机）不作判定，交 staleness 与人工抽验
    files = [f.strip() for f in (r.stdout or "").splitlines() if f.strip()]
    return any(f.replace("\\", "/").rsplit("/", 1)[-1].lower() in INJECT_BASENAMES for f in files)


def load(path: str = LEDGER_PATH) -> list:
    """追加式 JSONL，逐行容错（坏行/BOM/空行跳过），不合法条目不污染判据面。"""
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.readlines()
    except OSError:
        return out
    for line in raw:
        line = line.strip().lstrip("\ufeff")
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and "decision" in rec:
            out.append(rec)
    return out


def _attribution_errors(rec: dict) -> list:
    errs = []
    for k in ("actor_repo", "actor_commit", "cause"):
        if not str(rec.get(k, "")).strip():
            errs.append("缺 %s" % k)
    if len(str(rec.get("cause", ""))) < MIN_CAUSE:
        errs.append("cause 不足 %d 字" % MIN_CAUSE)
    return errs


def append_entry(path: str, rec: dict) -> None:
    """applied（抬/改基线）必须署名给因；pending（仅记增长事件）同样要可归因。"""
    errs = _attribution_errors(rec)
    if errs:
        raise ValueError("台账拒收（无归因即无移动）: " + ", ".join(errs))
    if rec.get("decision") == "applied":
        if not isinstance(rec.get("baseline_after"), int):
            raise ValueError("applied 条目必须带 baseline_after(int)")
        if not SHA_RE.match(str(rec.get("actor_commit", "")).strip()):
            raise ValueError("applied 的 actor_commit 必须是 7-40 位十六进制 sha（多个用 + 连接）；"
                             "HEAD/分支名/中文占位一律拒收——那种署名在校验时点指向任意提交")
        if rec.get("hard_cap", INITIAL_HARD_CAP) > INITIAL_HARD_CAP:
            raise ValueError("硬顶 %s > 天花板 %d，拒绝" % (rec.get("hard_cap"), INITIAL_HARD_CAP))
    rec.setdefault("ts", datetime.datetime.now().isoformat(timespec="seconds"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def validate(records: list, baseline=None, hard_cap=None, ledger_path: str = LEDGER_PATH,
             initial_hard_cap: int = INITIAL_HARD_CAP, measured_total=None,
             verify_actor: bool = True):
    """纯函数判据面（供 C31 与桩复用）。返回 (status, detail)。"""
    if not records:
        return ("FAIL", "W1 台账不存在或为空 = 未初始化（R247：空面不得静默 PASS）: %s" % ledger_path)
    applied = [r for r in records if r.get("decision") == "applied"]
    errs = []
    for i, r in enumerate(records):
        cap = r.get("hard_cap", initial_hard_cap)
        if cap > initial_hard_cap:
            errs.append("第 %d 条 硬顶 cap=%s 超天花板 %d" % (i + 1, cap, initial_hard_cap))
        if r.get("decision") == "applied":
            errs.extend(["第 %d 条 %s" % (i + 1, e) for e in _attribution_errors(r)])
    if errs:
        return ("FAIL", "W2 归因/上限不合规: " + "; ".join(errs[:4]))
    last = applied[-1] if applied else None
    if baseline is not None:
        actual = last["baseline_after"] if last else None
        if actual != baseline:
            return ("FAIL", "W3 基线裸改：truth_constants=%s 而台账末条 applied=%s"
                            "（须经 inject_ledger --record --decision applied 移动）"
                            % (baseline, actual))
    # W4 署名相关性：非空不等于相关（实测有 applied 引了只改日志的提交）。
    # 只对**生效的那条**（末条 applied）硬拦，历史误标以 ⚠ 显式列出不追溯致红——
    # 否则台账每加一条新规则就会把昨天的自己判红（存量红风暴）。
    irrelevant, unverifiable, stale_irrelevant = [], [], []
    if verify_actor and applied:
        for i, r in enumerate(applied):
            hit = commit_touches_injection(str(r.get("actor_repo", "")),
                                           str(r.get("actor_commit", "")))
            tag = "#%d %s" % (i + 1, r.get("actor_commit"))
            if hit is False:
                (irrelevant if i == len(applied) - 1 else stale_irrelevant).append(tag)
            elif hit is None:
                unverifiable.append(tag)
    if irrelevant:
        return ("FAIL", "W4 生效基线的署名提交未触及任何注入面文件（引无关 hash 过账）: "
                        + ", ".join(irrelevant[:3]))
    pending = [r for r in records if r.get("decision") == "pending"]
    # 关闭规则（追加式台账不改写历史行）：pending 之后出现「处置结论」（applied=移动基线 /
    # absorbed=增长已消化）即视为已裁决；基线一致性 W3 仍只看 applied（absorbed 不动基线）
    conclusion_at = max((i for i, r in enumerate(records)
                         if r.get("decision") in ("applied", "absorbed")), default=-1)
    open_pending = [r for i, r in enumerate(records)
                    if r.get("decision") == "pending" and i > conclusion_at]
    head = len(applied)
    bits = ["台账 %d 条（applied=%d/pending=%d）/ 基线 %s / 硬顶 %s"
            % (len(records), head, len(pending), baseline, hard_cap)]
    if measured_total is not None and hard_cap:
        room = hard_cap - measured_total
        bits.append("实测 %d（余量 %d，%.1f%%）" % (measured_total, room, 100.0 * room / hard_cap))
        if room / float(hard_cap) < HEADROOM_WARN_RATIO:
            bits.append("⚠ 余量 <%.0f%%，再有一次技能增长即破硬顶" % (HEADROOM_WARN_RATIO * 100))
    if open_pending:
        bits.append("待裁决 %d 条：最近=%s"
                    % (len(open_pending), str(open_pending[-1].get("cause", ""))[:60]))
    if unverifiable:
        bits.append("⚠ 署名不可核验 %d 条（复合标注/浅克隆/异机）需抽验: %s"
                    % (len(unverifiable), ", ".join(unverifiable[:3])))
    if stale_irrelevant:
        bits.append("⚠ 历史 applied 署名与注入面无涉 %d 条（不追溯致红，请补更正条目或人工确认）: %s"
                    % (len(stale_irrelevant), ", ".join(stale_irrelevant[:3])))
    return ("PASS", " | ".join(bits))


def check(path: str = LEDGER_PATH) -> tuple:
    sys.path.insert(0, EVAL_DIR)
    import truth_constants as t
    b = t.INJECT_BUDGET
    total = 0
    for f in b["files"]:
        # 相对路径锚在治理仓根（判据面不随 cwd 漂移，与 C25/C31 同口径）
        p = f["path"] if os.path.isabs(f["path"]) else os.path.join(ROOT, f["path"])
        if os.path.exists(p):
            total += os.path.getsize(p)
        else:
            return ("SKIP", "注入文件缺失（非本机环境）: %s" % p)
    return validate(load(path), baseline=b["baseline_bytes"], hard_cap=b["hard_cap_bytes"],
                    ledger_path=path, measured_total=total)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="注入预算归因台账")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--actor-repo", default="")
    ap.add_argument("--actor-commit", default="")
    ap.add_argument("--cause", default="")
    ap.add_argument("--scope", default="growth_event")
    ap.add_argument("--delta-bytes", type=int, default=0)
    ap.add_argument("--baseline-before", type=int, default=0)
    ap.add_argument("--baseline-after", type=int, default=0)
    ap.add_argument("--hard-cap", type=int, default=INITIAL_HARD_CAP)
    ap.add_argument("--decision", default="pending", choices=["pending", "applied", "absorbed"])
    ap.add_argument("--ledger", default=LEDGER_PATH)
    a = ap.parse_args(argv)
    if a.show:
        for r in load(a.ledger):
            print(json.dumps(r, ensure_ascii=False))
        return 0
    if a.record:
        append_entry(a.ledger, {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                "actor_repo": a.actor_repo, "actor_commit": a.actor_commit,
                                "cause": a.cause, "scope": a.scope, "delta_bytes": a.delta_bytes,
                                "baseline_before": a.baseline_before, "baseline_after": a.baseline_after,
                                "hard_cap": a.hard_cap, "decision": a.decision})
        print("已记账 decision=%s -> %s" % (a.decision, a.ledger))
        return 0
    if a.check:
        st, detail = check(a.ledger)
        print("[%s] %s" % (st, detail))
        return 0 if st in ("PASS", "SKIP") else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
