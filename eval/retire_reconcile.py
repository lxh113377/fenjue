#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retire_reconcile.py — 退役 skill 防回滚对账（R198.6）

常驻门禁：核对「退役黑名单」是否被批量入库流程重新拉回注册表/索引。
根治 build_registry.py「磁盘→注册表无脑补齐」导致的删除失效（2026-08-16 事故）。

三方数据源：
  ① 退役黑名单  = truth_constants.json.retired_skills（权威，owner 登记）
  ② 注册表现状  = skill/registry/unified-skills-index.json.skills（磁盘补齐后状态）
  ③ 索引现状    = <MEMORY_ROOT>\\skill_content\\skill_ids.json（BGE/TF-IDF 派生）

对账逻辑：
  - 注册表回滚：黑名单项出现在注册表 skills → 回滚（批量入库无脑补齐）
  - 索引回滚：黑名单项出现在 skill_ids.json → 派生件残留（build_indexes 未排除）

可配置（truth_constants.json.retire_policy）：
  - threshold:   允许的回滚数量阈值（0=零容忍，>0 容忍少量过渡项）
  - block_ingest: true=回滚时阻断入库流程（退出码 1 拦截）/ false=仅告警不阻断
  - frequency:   建议对账频率（文档化，供周维护调度参考）

用法:
  python eval/retire_reconcile.py            # 文本报告
  python eval/retire_reconcile.py --json     # JSON 输出（门禁消费）
  python eval/retire_reconcile.py --repair   # 移除注册表/索引中的回滚项（需确认）
  python eval/retire_reconcile.py --log-savepoint  # 结果落盘 savepoint-gate.jsonl（周维护 4i）
退出码: 0 = PASS（无回滚或 ≤阈值）/ 1 = FAIL（回滚超阈值且 block_ingest）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
REGISTRY_DIR = os.path.join(PROJECT_DIR, "skill", "registry")
REGISTRY_FILE = os.path.join(REGISTRY_DIR, "unified-skills-index.json")
TC_JSON = os.path.join(EVAL_DIR, "truth_constants.json")
SAVEPOINT_GATE = os.path.join(PROJECT_DIR, "memory", "sessions", "savepoint-gate.jsonl")
# P1-6 收口: 单源引用（env 可覆盖）
from config import SKILL_CONTENT  # noqa: E402

sys.path.insert(0, EVAL_DIR)


from io_utils import load_json  # P1-5: 读写原语唯一实现


def log(step: str, msg: str, ok: bool = True):
    icon = "OK " if ok else "FAIL"
    print(f"[{icon}] {step}: {msg}")


class TruthSourceError(Exception):
    """P0-5: 真相源不可读 —— 禁止 fail-open，必须 fail-closed。"""


def get_retired() -> set[str]:
    """① 退役黑名单（权威源 truth_constants.json）。"""
    try:
        tc = load_json(TC_JSON)
        return set(tc.get("retired_skills", []))
    except Exception as e:
        # P0-5: 读失败返回空集 = 黑名单消失 = 静默放行 → 改为抛错 fail-closed
        print(f'[retire_reconcile] FAIL 真相源不可读，拒绝 fail-open: {TC_JSON} '
              f'({type(e).__name__}: {e})', file=sys.stderr)
        raise TruthSourceError(f'真相源不可读: {TC_JSON}') from e


def get_policy() -> dict:
    """对账策略（可配置，缺省零容忍+阻断）。"""
    try:
        tc = load_json(TC_JSON)
        pol = tc.get("retire_policy", {})
        return {
            "threshold": int(pol.get("threshold", 0)),
            "block_ingest": bool(pol.get("block_ingest", True)),
            "frequency": str(pol.get("frequency", "monthly")),
        }
    except Exception as e:
        # P0-5: 同上 —— 缺省策略不可代替不可读的真相源
        print(f'[retire_reconcile] FAIL 策略源不可读，拒绝缺省放行: {TC_JSON} '
              f'({type(e).__name__}: {e})', file=sys.stderr)
        raise TruthSourceError(f'策略源不可读: {TC_JSON}') from e


def get_registry_skills() -> set[str]:
    """② 注册表现状（**跟踪件：读不到就是瞎了，不许当成"零回滚"放过**，D-101 / R247）。

    旧实现 `except Exception: return set()` ⇒ 注册表损坏/改名/被误删时黑名单对账静默判 PASS，
    而这闸存在的理由恰恰是 2026-08-16「磁盘→注册表无脑补齐」把退役 skill 拉回去。
    """
    try:
        reg = load_json(REGISTRY_FILE)
    except Exception as e:
        print(f'[retire_reconcile] FAIL 注册表面不可读，拒绝按"零回滚"放行: {REGISTRY_FILE} '
              f'({type(e).__name__}: {e})', file=sys.stderr)
        raise TruthSourceError(f'注册表面不可读: {REGISTRY_FILE}') from e
    skills = reg.get("skills")
    if not isinstance(skills, dict) or not skills:
        raise TruthSourceError(f'注册表面形状异常或为空: {REGISTRY_FILE}')
    return set(skills.keys())


def get_index_skills() -> set[str]:
    """③ 索引现状（skill_ids.json）。"""
    try:
        idx = load_json(os.path.join(SKILL_CONTENT, "skill_ids.json"))
        if isinstance(idx, list):
            names = set()
            for s in idx:
                if isinstance(s, dict):
                    names.add(s.get("id") or s.get("name") or "")
                else:
                    names.add(str(s))
            return names
        return set(idx.keys())
    except Exception:
        return set()


def reconcile() -> dict:
    try:
        retired = get_retired()
        reg = get_registry_skills()
        idx = get_index_skills()
        policy = get_policy()
    except TruthSourceError as e:
        # P0-5: 真相源不可读 → 整单 FAIL（fail-closed），下游 exit 1 阻断
        return {
            "retired_count": -1,
            "registry_rollback": [],
            "index_rollback": [],
            "rollback_total": -1,
            "threshold": 0,
            "block_ingest": True,
            "frequency": "unknown",
            "passed": False,
            "error": str(e),
        }
    reg_rollback = sorted(retired & reg)
    idx_rollback = sorted(retired & idx)
    threshold = policy["threshold"]
    total_rollback = len(reg_rollback) + len(idx_rollback)
    passed = total_rollback <= threshold
    return {
        "retired_count": len(retired),
        "registry_rollback": reg_rollback,
        "index_rollback": idx_rollback,
        "rollback_total": total_rollback,
        "threshold": threshold,
        "block_ingest": policy["block_ingest"],
        "frequency": policy["frequency"],
        # 派生索引面允许缺席（CI/异机没有 skill_content），但缺席必须写进结果，
        # 不许与"有索引且索引干净"同形（否则面塌了没人知道）
        "index_available": bool(idx),
        "passed": passed,
    }


def repair(result: dict) -> list[str]:
    """移除注册表/索引中的回滚项（--repair，可恢复：git 历史有源）。"""
    changes = []
    for name in result["registry_rollback"]:
        try:
            reg = load_json(REGISTRY_FILE)
            if name in reg.get("skills", {}):
                del reg["skills"][name]
                reg["last_updated"] = "2026-08-16T02:40:00"
                Path(REGISTRY_FILE).write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
                changes.append(f"注册表移除 {name}")
        except Exception as e:
            changes.append(f"注册表移除失败 {name}: {e!r}")
    for name in result["index_rollback"]:
        changes.append(f"索引需重建移除 {name}（请跑 build_indexes.py --apply）")
    return changes


def log_savepoint(result: dict) -> None:
    """对账结果落盘 memory/sessions/savepoint-gate.jsonl（R198.6，可追溯证据链）。

    schema 与 workflow_gate 的 savepoint-gate.jsonl 兼容（schema_v=2），
    gate 字段标识为 "retire-reconcile" 便于 trace_view 统计。
    """
    try:
        os.makedirs(os.path.dirname(SAVEPOINT_GATE), exist_ok=True)
        record = {
            "ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "project": PROJECT_DIR,
            "gate": "retire-reconcile",
            "exit": 0 if result["passed"] else 1,
            "schema_v": 2,
            "failure_cost": {
                "gate_fails": 0 if result["passed"] else len(result["registry_rollback"]),
                "rollbacks": len(result["registry_rollback"]),
                "est_wasted_minutes": 0,
                "failure_budget": result["threshold"],
            },
            "schema": "fenjue-retire-reconcile-v1",
            "stage": "retire-reconcile",
            "platform": "auto",
            "all_pass": result["passed"],
            "retired_count": result["retired_count"],
            "registry_rollback": result["registry_rollback"],
            "index_rollback": result["index_rollback"],
            "rollback_total": result["rollback_total"],
            "threshold": result["threshold"],
            "block_ingest": result["block_ingest"],
        }
        with Path(SAVEPOINT_GATE).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        log("落盘", f"对账结果已追加 {SAVEPOINT_GATE}")
    except Exception as e:
        log("落盘", f"savepoint-gate.jsonl 写入失败: {e!r}", ok=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="退役 skill 防回滚对账")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repair", action="store_true", help="移除注册表/索引中的回滚项")
    ap.add_argument("--log-savepoint", action="store_true",
                    help="对账结果落盘 memory/sessions/savepoint-gate.jsonl（周维护 Step 4i 用）")
    args = ap.parse_args()

    result = reconcile()
    repair_changes: list[str] = []
    if args.repair and not result["passed"]:
        repair_changes = repair(result)
        result = reconcile()  # 复算
    if args.log_savepoint:
        log_savepoint(result)

    if args.json:
        print(json.dumps({
            "schema": "fenjue-retire-reconcile-v1",
            "ts": __import__("datetime").datetime.now().isoformat(),
            "all_pass": result["passed"],
            "repair_changes": repair_changes,
            **result,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"退役黑名单: {result['retired_count']} 项")
        print(f"注册表回滚: {len(result['registry_rollback'])} → {result['registry_rollback'][:5]}")
        print(f"索引回滚:   {len(result['index_rollback'])} → {result['index_rollback'][:5]}")
        print(f"阈值: {result['threshold']} | block_ingest: {result['block_ingest']} | 频率: {result['frequency']}")
        print("PASS 无回滚" if result["passed"] else f"FAIL 回滚 {result['rollback_total']} 项（超阈值 {result['threshold']}）")
        if repair_changes:
            for c in repair_changes:
                print(f"  [repair] {c}")

    return 0 if result["passed"] else (1 if result["block_ingest"] else 0)


if __name__ == "__main__":
    sys.exit(main())
