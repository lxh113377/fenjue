#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""empty_baseline_ledger.py — 空基线「已初始化」台账（对标轮四 7-C / 6-B，治 vacuous pass 整族）。

病灶（第三轮 D-10 实测，本轮复核仍在）：`style_ratchet_baseline.json == {}`、
`llm_failure_cases.json == []`、`blindset_rotation.json active_version=0 / history=[]`
——三处都以"空"通过各自的闸。空有两种含义：**扫过且无违例**（合法）与**根本没扫/机制没跑**
（永不为真的通过）。二者在文件里长得一模一样，所以必须把"扫过什么、扫了多少、什么时候"外置成账。

判据（C32）：空面必须持有一条登记，含 `scanned_units>0`、`at`（≤90 天）、以及"扫面口径" `surface`；
计数器型（如轮换版本）另须 `next_due`。新增空基线未登记 = 红（同 gate_stub_runner 的
「新增判据未补桩即 FAIL」思路）。用法：
  python eval/empty_baseline_ledger.py --check      # 门禁面（C32 同源）
  python eval/empty_baseline_ledger.py --init       # 重新采集并登记（扫面实测）
"""

from __future__ import annotations

import argparse
import datetime
import json
import os

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVAL_DIR)
LEDGER_PATH = os.path.join(EVAL_DIR, "empty_baseline_ledger.json")
MAX_AGE_DAYS = 90

# 受管空基线清单（单一定义点；消费方 = C32 判据、--init 采集、桩）
# `source` = 该面所依赖的**数据源**文件（D-41）：源与基线文件都不在 ⇒ 面在本环境不可达，
# CI 上按 SKIP 处理（同 C20/C25 的 skip_external 口径）；源在而登记缺失仍一律判红，不给逃生门。
TARGETS = [
    {"id": "style-ratchet", "path": "style_ratchet_baseline.json", "kind": "dict",
     "surface": "scan_dirs_py_files", "source": "style_ratchet_baseline.json",
     "consumer": "eval/style_ratchet.py（pre-commit 第 8 闸）",
     "note": "{} = 无存量风格违例；须证明 ruff 真的扫过 eval/scripts/audit/feedback 四面"},
    {"id": "llm-failure-cases", "path": "llm_failure_cases.json", "kind": "list",
     "surface": "llm_decisions_lines", "source": "llm_decisions.jsonl",
     "consumer": "eval/llm_layer.py",
     "note": "[] = 尚无 LLM 判错样本；须证明决策流有在记录（否则是没接线而非没错）"},
    {"id": "blindset-rotation", "path": "blindset_rotation.json", "kind": "counter",
     "counter_key": "active_version", "surface": "layered_testset",
     "source": "blindset_rotation.json",
     "consumer": "eval/rotate_blindset.py（季度轮换）",
     "note": "active_version=0 + history=[] = 季度轮换从未执行；登记须给 next_due，否则永为 vacuous。"
             "面口径取 layered_testset.json（CI 实跑集，轮换的真正题源），非 blind_test_queries 的 4 条壳"},
]


def _abs(rel: str) -> str:
    return os.path.join(EVAL_DIR, rel)


def _count_py() -> int:
    n = 0
    for d in ("eval", "scripts", "audit", "feedback"):
        base = os.path.join(ROOT, d)
        for _dir, _sub, files in os.walk(base):
            n += sum(1 for f in files if f.endswith(".py"))
    return n


def _count_lines(rel: str) -> int:
    p = _abs(rel)
    if not os.path.exists(p):
        return 0
    with open(p, encoding="utf-8", errors="replace") as f:
        return sum(1 for line in f if line.strip())


def _read_json(rel):
    p = rel if os.path.isabs(rel) else _abs(rel)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def is_empty(obj, kind: str, counter_key: str = "") -> bool:
    """空 = {} / [] / 计数器为 0；其余算非空（非空无需登记）。"""
    if kind == "dict":
        return isinstance(obj, dict) and not obj
    if kind == "list":
        return isinstance(obj, list) and not obj
    if kind == "counter":
        return isinstance(obj, dict) and not obj.get(counter_key, 0)
    return False


def surface_units(target: dict) -> int:
    kind_surface = target.get("surface")
    if kind_surface == "scan_dirs_py_files":
        return _count_py()
    if kind_surface == "llm_decisions_lines":
        return _count_lines("llm_decisions.jsonl")
    if kind_surface == "layered_testset":
        # layered_testset.json 是「分层组」列表（5 组），真实题量在每组内部的用例数组里；
        # 数组数会把面写小 58 倍（实测 5 vs 291），故取每组最长列表长度求和
        data = _read_json("layered_testset.json")
        if not isinstance(data, list):
            return 0
        total = 0
        for grp in data:
            if isinstance(grp, dict):
                lists = [len(v) for v in grp.values() if isinstance(v, list)]
                total += max(lists) if lists else 0
            elif isinstance(grp, list):
                total += len(grp)
        return total
    return 0


def collect_state() -> list:
    out = []
    for t in TARGETS:
        obj = _read_json(t["path"])
        src = t.get("source", t["path"])
        out.append({"id": t["id"], "path": t["path"], "kind": t["kind"],
                    "present": obj is not None,
                    "source_present": os.path.exists(_abs(src)),
                    "empty": is_empty(obj, t["kind"], t.get("counter_key", "")),
                    "units": surface_units(t)})
    return out


def load_ledger(path: str = LEDGER_PATH) -> dict:
    data = _read_json(path)
    if not isinstance(data, dict):
        return {}
    return {e.get("id"): e for e in data.get("entries", []) if isinstance(e, dict)}


def judge(state: list, entries: dict, today: str | None = None,
          skip_external: bool = False) -> tuple:
    """纯函数判据面（供 C32 与桩复用）。返回 (status, detail)。

    `skip_external=True`（CI）只放行一类情形：**基线文件与它的数据源同时缺失**
    （面在本环境根本不存在，如 gitignored 的 llm_decisions.jsonl 及其派生件）。
    数据源在、只是登记缺失或非正数 ⇒ 照旧判红，不给"改环境标记"当逃生门。
    """
    today = today or datetime.date.today().isoformat()
    errs, notes, skipped = [], [], []
    for st in state:
        tid = st["id"]
        if not st["present"]:
            if skip_external and not st.get("source_present", True):
                skipped.append("%s（数据源亦不在本环境，面不可达）" % tid)
                continue
            errs.append("%s 基线文件缺失（判据面无从核验）" % tid)
            continue
        if not st["empty"]:
            notes.append("%s 非空" % tid)
            continue
        e = entries.get(tid)
        if not e:
            errs.append("%s 空面未登记 = 无法区分「扫过且干净」与「根本没扫」（R247）" % tid)
            continue
        if not isinstance(e.get("scanned_units"), int) or e["scanned_units"] <= 0:
            errs.append("%s 登记 scanned_units=%r 非正数（扫了 0 个对象不得判过）"
                        % (tid, e.get("scanned_units")))
        if st["present"] and st["units"] > 0 and isinstance(e.get("scanned_units"), int) \
                and e["scanned_units"] > st["units"]:
            # 上界只在实扫面可测时生效：CI 上部分源文件不入库（如 llm_decisions.jsonl），
            # 面会缩成 0——此时判"虚报"是假的，真因是面不可测（下界 scanned_units>0 仍硬拦）
            errs.append("%s 登记 scanned_units=%d 超当前实扫面 %d（口径漂移或虚报）"
                        % (tid, e["scanned_units"], st["units"]))
        at = str(e.get("at", ""))
        try:
            age = (datetime.date.fromisoformat(at) - datetime.date.fromisoformat(today)).days
            age = -age
        except ValueError:
            errs.append("%s 登记 at=%r 非 ISO 日期" % (tid, at))
            age = None
        if age is not None and age > MAX_AGE_DAYS:
            errs.append("%s 登记已过期 %d 天（>%d）——陈旧初始化不得长期吃老本" % (tid, age, MAX_AGE_DAYS))
        if st["kind"] == "counter" and not e.get("next_due"):
            errs.append("%s 计数器型空面必须给 next_due（未跑的执行类判据不得留白）" % tid)
        if not str(e.get("surface", "")).strip():
            errs.append("%s 登记缺 surface（扫面口径）" % tid)
    if errs:
        return ("FAIL", "; ".join(errs[:4]))
    if skipped and len(skipped) == len(state):
        return ("SKIP", "全部 %d 面在本环境不可达（基线与数据源均缺失）：%s"
                % (len(state), "; ".join(skipped)))
    return ("PASS", "空基线 %d 面全部登记在册（非空=%d）| 实扫面 %s%s"
            % (len(state) - len(skipped), sum(1 for s in state if not s["empty"]),
               ", ".join("%s=%d" % (s["id"], s["units"]) for s in state),
               " | 本环境不可达已跳过: " + "; ".join(skipped) if skipped else ""))


def init_ledger(path: str = LEDGER_PATH, next_due: str = "") -> dict:
    entries = load_ledger(path)
    today = datetime.date.today().isoformat()
    for st in collect_state():
        if not st["empty"]:
            continue
        tgt = next(t for t in TARGETS if t["id"] == st["id"])
        e = {"id": st["id"], "scanned_units": st["units"], "surface": tgt["surface"],
             "at": today, "note": tgt["note"]}
        if tgt["kind"] == "counter":
            e["next_due"] = next_due or ""
        entries[st["id"]] = e
    payload = {"schema": "fenjue-empty-baseline-ledger-v1",
               "_note": "空基线「已初始化」登记表（对标轮四 7-C）。空面必须能自证扫过什么、"
                        "扫了多少、什么时候扫的；新增空面未登记即 C32 红。",
               "entries": list(entries.values())}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return payload


def check(path: str = LEDGER_PATH, skip_external: bool = False) -> tuple:
    if not os.path.exists(path):
        return ("FAIL", "W0 台账文件不存在: %s（跑 --init 采集）" % path)
    return judge(collect_state(), load_ledger(path), skip_external=skip_external)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="空基线已初始化台账")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--skip-external", action="store_true",
                    help="CI 口径：基线与数据源同时缺失的面判不可达并跳过（D-41）")
    ap.add_argument("--state", action="store_true", help="打印各面实测状态（不判定）")
    ap.add_argument("--next-due", default="", help="--init 时给计数器型面的下次到期日")
    a = ap.parse_args(argv)
    if a.state:
        print(json.dumps(collect_state(), ensure_ascii=False, indent=2))
        return 0
    if a.init:
        p = init_ledger(next_due=a.next_due)
        print("已登记 %d 面 -> %s" % (len(p["entries"]), LEDGER_PATH))
        return 0
    if a.check:
        st, detail = check(skip_external=a.skip_external)
        print("[%s] %s" % (st, detail))
        return 0 if st == "PASS" else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
