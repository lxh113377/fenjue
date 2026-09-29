#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate_scope_attribution.py — 共享工作树的「他人存量红」归因（对标轮五 P0-23）。

病灶（本轮实测 4 例）：pre-commit 第 1 闸跑**全量 verify**，输入是整块磁盘当前态而非本次
改动面 ⇒ 任一 agent 的在途半成品会让所有 agent 的提交同时不可用。当晚 4 次被拦，红因
分别是并发发布 A-memory-start V10.68/69（C25 三次）与给 ican-frontend-design-system 加
绝对路径（C20 一次），**没有一次是本会话引入的**。

三条硬约束（否则"豁免"会变成新的 vacuous pass）：
  1) **认不出因就拦**（fail-closed）：FAIL detail 里提不出任何可归属标记 ⇒ 判为相关；
  2) 豁免必须**落账**（shared_red_ledger.jsonl：谁、哪项、detail、本次暂存面、时间）；
  3) 同一判据**连续豁免 > 上限**即转为**升级记账**（escalate：债务可见 + 持续计数），
     并**始终**对肇事者（命中暂存面 / 不可归因）阻断；计数唯一的释放口是 `--resolve`，
     且只有该判据当前不再 FAIL 才允许销账。CI 端始终跑全量 verify 兜底——本地放行只是
     "别替别人背锅"，不是"这条不查了"。

D-36 修订（2026-09-24 23:35→23:46 三行账本实证）：原第 3 条写的是"超限即恢复阻断"，
实测有两处失效——① `block` 行被 `streaks()` 当成归零事件，上限只生效一次，之后豁免照流
（"防永久豁免"是纸面约束）；② 超限后的阻断落在**第 6 个恰好来提交的人**头上（可能是任何
无关会话），既不指向红因制造者，也不产生任何修复动作，等于把本模块要治的病灶又造了一遍。
故改为：肇事者恒拦 + 无关方升级记账（债务持续在册、可 `--resolve` 真销）。

用法：python eval/gate_scope_attribution.py            # 读 git 暂存面 + 跑 verify 分类
      python eval/gate_scope_attribution.py --json
      python eval/gate_scope_attribution.py --resolve C20   # 真销账（该判据须已不再 FAIL）
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVAL_DIR)
LEDGER = os.path.join(EVAL_DIR, "shared_red_ledger.jsonl")
EXEMPT_CAP = 5          # 同一判据连续豁免上限，超过即恢复阻断
# D-106：注入区是**全盘累加账**（任何会话写一次记忆都算在它头上），余量薄时"再豁免 5 次"
# 等于把债滚到 runner 恢复那天一起爆。故这几条判据在余量低于阈值时**当场升级为存量红债务**，
# 不再走宽限计数。升级=只落账+可见，不阻断正常提交（阻断仍由硬顶 W3 负责）。
THIN_MARGIN_CHECKS = {"C25": 0.05}
PATH_TOKEN = re.compile(r"[A-Za-z0-9_./\\:-]*[A-Za-z0-9_.-]+\.(?:py|md|json|jsonl|yml|yaml|ps1|sh|toml|cfg)")
NAME_TOKEN = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9_.-]{4,}\b")
STOP_WORDS = {"baseline", "detail", "count", "status", "FAIL", "PASS", "SKIP", "truth_constants",
              "verify", "commit", "python", "eval", "items", "bytes", "code", "inline",
              "version", "history", "active", "index", "registry", "schema", "jsonl", "none"}


def _norm(p: str) -> str:
    return p.replace("\\", "/").strip("/").lower()


def staged_paths(paths=None, repo: str = ROOT) -> tuple:
    """本次提交的暂存面（归一化为小写正斜杠路径 + 其路径成分集合）。"""
    if paths is None:
        r = subprocess.run(["git", "-C", repo, "diff", "--cached", "--name-only", "-z"],
                           capture_output=True)
        raw = (r.stdout or b"").decode("utf-8", "replace")
        paths = [p for p in raw.split("\0") if p.strip()]
    norm = [_norm(p) for p in paths]
    comps = set()
    for p in norm:
        comps.update(seg for seg in p.split("/") if len(seg) > 3)
    return norm, comps


def tokens_from_detail(detail: str) -> list:
    """从 FAIL detail 抽可归属标记；抽不出即返回空（调用方按 fail-closed 处理）。"""
    toks = {t.strip("./").lower() for t in PATH_TOKEN.findall(detail or "")}
    toks |= {t.lower() for t in NAME_TOKEN.findall(detail or "") if t.lower() not in STOP_WORDS}
    return sorted(t for t in toks if len(t) > 3)


def is_related(detail: str, staged: tuple) -> bool:
    norm, comps = staged
    toks = tokens_from_detail(detail)
    if not toks:
        return True          # 认不出因 ⇒ 一律算我引入的
    for t in toks:
        base = t.split("/")[-1]
        if any(t in p or base in p.split("/") for p in norm):
            return True
        if base in comps or t in comps:
            return True
    return False


def streaks(ledger_path: str = LEDGER) -> dict:
    """连续豁免计数。**只有 resolve 能归零**（D-36：block 行不再自我抹账）。"""
    counts = {}
    try:
        with open(ledger_path, encoding="utf-8") as f:
            rows = [json.loads(ln) for ln in f if ln.strip()]
    except (OSError, ValueError):
        return counts
    for r in rows:
        cid = r.get("check")
        if r.get("action") in ("exempt", "escalate"):
            counts[cid] = counts.get(cid, 0) + 1
        elif r.get("action") == "resolve":
            counts[cid] = 0     # 唯一释放口：该判据已实测不再 FAIL
    return counts


def headroom_ratio(detail: str, baseline: int | None = None):
    """从判据文案里取实测字节数，基线优先取 truth_constants 单一事实源。

    两种真实文案都要能读：FAIL 的「W4 总字节 64604 > 棘轮基线 63336」与 PASS 的
    「注入区 63120 B / 基线 63336 B（余量 216）」—— 薄余量的价值恰恰在**还绿着的时候**就看见。
    取不到任一数字返回 None：没有数就不许冒充"余量充足"继续宽限（R247）。
    """
    m = re.search(r"(?:总字节|注入区)\s*([0-9_]+)", detail or "")
    if not m:
        return None
    total = int(m.group(1).replace("_", ""))
    if baseline is None:
        try:
            if EVAL_DIR not in sys.path:
                sys.path.insert(0, EVAL_DIR)
            import truth_constants as tc
            obj = getattr(tc, "INJECT_BUDGET", None) or getattr(tc, "inject_budget", None) or {}
            baseline = obj.get("baseline_bytes")
        except Exception:
            baseline = None
    if not baseline:
        mb = re.search(r"(?:棘轮)?基线\s*([0-9_]+)", detail or "")
        baseline = int(mb.group(1).replace("_", "")) if mb else None
    if not baseline or int(baseline) <= 0:
        return None
    return (int(baseline) - total) / float(baseline)


def classify(results: list, staged: tuple, cap: int = EXEMPT_CAP, prior: dict | None = None):
    """纯函数判据面（桩/测试注入夹具用）。返回 (allow, [(cid, why, detail)], banner)。"""
    fails = [r for r in results if r.get("status") == "FAIL"]
    if not fails:
        return True, [], ""
    prior = prior or {}
    items, mine = [], 0
    for f in fails:
        cid = f.get("id") or "?"
        detail = f.get("detail") or ""
        if is_related(detail, staged):
            mine += 1
            items.append((cid, "本次改动面命中或不可归因", detail))
        elif cid in THIN_MARGIN_CHECKS and (
                _hr := headroom_ratio(detail)) is not None                 and _hr < THIN_MARGIN_CHECKS[cid]:
            items.append((cid, "注入面余量仅 %.1f%%（低于 %.0f%% 阈值）→ 当场升级为存量红债务，"
                               "不再走 %d 次宽限；真销账只有两条路：精简注入面，或经 "
                               "eval/inject_ledger.py --record --decision applied 留痕"
                               % (_hr * 100, THIN_MARGIN_CHECKS[cid] * 100, cap), detail))
        elif prior.get(cid, 0) >= cap:
            items.append((cid, "连续豁免已达上限 %d → 升级为存量红债务（非本次改动面仍放行，"
                               "账不销红不消；真销账走 --resolve %s）" % (cap, cid), detail))
        else:
            items.append((cid, "与本次暂存面无因果 → 判为他人存量红，豁免并落账", detail))
    allow = mine == 0
    banner = "\n".join("  ⚠ [%s] %s | %s" % (c, w, d[:90]) for c, w, d in items)
    return allow, items, banner


def _action_of(why: str) -> str:
    if "升级" in why:
        return "escalate"
    if "豁免" in why:
        return "exempt"
    return "block"


def resolve(cid: str, results: list | None = None, ledger_path: str = LEDGER):
    """计数唯一释放口：该判据当前实测不再 FAIL 才写 resolve 行（红还在即拒绝）。"""
    if results is None:
        results = verify_results()
    still = [r for r in results if r.get("id") == cid and r.get("status") == "FAIL"]
    if still:
        return False, "[%s] 仍 FAIL，拒绝销账：%s" % (cid, (still[0].get("detail") or "")[:80])
    if not any(r.get("id") == cid for r in results):
        return False, "[%s] 不在 verify 判据面里（判据名写错也算 fail-closed）" % cid
    row = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "check": cid,
           "action": "resolve", "why": "该判据当前不再 FAIL ⇒ 连续豁免计数归零",
           "detail": "", "staged": []}
    try:
        with open(ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        return False, "账本不可写，拒绝归零"
    return True, "[%s] 已销账（连续豁免计数归零）" % cid


def verify_results():
    """跑一次真 verify --json；解析失败返回 None（调用方按 fail-closed 处理）。"""
    r = subprocess.run([sys.executable, os.path.join(EVAL_DIR, "verify_truth_consistency.py"),
                        "--json"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return None
    return data.get("results", data if isinstance(data, list) else [])


def record(items, staged_paths_list, ledger_path: str = LEDGER) -> None:
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with open(ledger_path, "a", encoding="utf-8") as f:
            for cid, why, detail in items:
                act = _action_of(why)
                f.write(json.dumps({"ts": ts, "check": cid, "action": act, "why": why[:60],
                                    "detail": detail[:160], "staged": staged_paths_list[:12]},
                                   ensure_ascii=False) + "\n")
    except OSError:
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="共享工作树红项归因")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", default=ROOT, help="取暂存面的仓（GM hook 传 GM 根，判据仍在焚诀跑）")
    ap.add_argument("--resolve", metavar="CHECK_ID", help="真销账：该判据当前不再 FAIL 才归零计数")
    a = ap.parse_args(argv)
    if a.resolve:
        results = verify_results()
        if results is None:
            print("[attribution] verify --json 不可解析 ⇒ fail-closed，拒绝销账")
            return 1
        ok, msg = resolve(a.resolve, results=results)
        print("[attribution] " + msg)
        return 0 if ok else 1
    results = verify_results()
    if results is None:
        print("[attribution] verify --json 不可解析 ⇒ fail-closed 阻断")
        return 1
    prior = streaks()
    staged = staged_paths(repo=a.repo)
    allow, items, banner = classify(results, staged, prior=prior)
    record(items, list(staged[0]))
    debt = ["%s×%d" % (c, n) for c, n in sorted(prior.items()) if n >= EXEMPT_CAP]
    if debt:
        print("[attribution] 在册存量红债务（连续豁免 ≥ 上限 %d）：%s；真销账 --resolve <ID>"
              % (EXEMPT_CAP, " ".join(debt)))
    if a.json:
        print(json.dumps({"allow": allow, "items": items}, ensure_ascii=False))
    else:
        print(banner or "  （无 FAIL）")
    return 0 if allow else 1


if __name__ == "__main__":
    sys.exit(main())
