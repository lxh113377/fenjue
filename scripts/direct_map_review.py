#!/usr/bin/env python3
"""
direct_map_review.py — DIRECT_MAP 人工确认 + apply + 回滚（T04）
==============================================================
阶段④⑤：CLI 逐条 y/n/s 或离线 md 勾选确认；apply 双写 direct_map.json +
direct_layer.py 的 _DIRECT_MAP_FALLBACK（零逻辑改动，仅文本 append，preserve 注释）；
守恒校验 + 备份 + 回滚。

铁律（设计 §2.4/§7）:
  - 只有 status=approved 的候选可被 apply；
  - apply 必须显式 --apply-ids 或 --apply-all-approved（后者仍二次确认）；
  - 无人工确认路径下，生产文件内容不变。

用法:
  python scripts/direct_map_review.py --list [--status pending] [--limit 50]
  python scripts/direct_map_review.py --review                     # 交互 y/n/s
  python scripts/direct_map_review.py --from-review <md>           # 解析离线勾选
  python scripts/direct_map_review.py --apply-ids C0001,C0002 [--dry-run]
  python scripts/direct_map_review.py --apply-all-approved [--dry-run] [--yes]
  python scripts/direct_map_review.py --rollback [<backup_json>]
  python scripts/direct_map_review.py --verify-sync
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"
PROJECT_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = PROJECT_DIR / "Temp"

sys.path.insert(0, str(EVAL_DIR))

import direct_map_budget  # noqa: E402
from direct_map_candidates import (  # noqa: E402
    load_candidates,
    now_iso,
    save_candidates,
)
from save_direct_map import extract_fallback  # noqa: E402


def _paths() -> dict[str, Path]:
    """路径可经 env 覆盖（测试隔离生产文件）。"""
    return {
        "json": Path(os.environ.get("FENJUE_DIRECT_MAP_JSON") or EVAL_DIR / "direct_map.json"),
        "layer": Path(os.environ.get("FENJUE_DIRECT_LAYER_PY") or EVAL_DIR / "direct_layer.py"),
        "candidates": Path(
            os.environ.get("FENJUE_CANDIDATES_PATH") or EVAL_DIR / "direct_map_candidates.jsonl"
        ),
        "temp": Path(os.environ.get("FENJUE_TEMP_DIR") or TEMP_DIR),
    }


def _atomic_write_text(path: Path, text: str) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
    from io_utils import write_text_atomic  # P1-5: 读写原语唯一实现
    write_text_atomic(path, text, newline="\n")


def _atomic_write_json(path: Path, obj: Any) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
    from io_utils import write_json_atomic  # P1-5: 读写原语唯一实现
    write_json_atomic(path, obj)


def load_production(path: Path | None = None) -> list[list[str]]:
    p = path or _paths()["json"]
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    if not (
        isinstance(data, list)
        and all(
            isinstance(i, list) and len(i) == 2 and isinstance(i[0], str) and isinstance(i[1], str)
            for i in data
        )
    ):
        raise SystemExit(f"ERROR: {p} 结构非法")
    return data


def list_candidates(status: str = "pending", limit: int = 50) -> None:
    """展示候选列表。"""
    cands = load_candidates(_paths()["candidates"])
    if status:
        cands = [c for c in cands if c.get("status") == status]
    if limit:
        cands = cands[:limit]
    for c in cands:
        high = " [HIGH_RISK]" if (c["skill"] == "NONE" or c.get("duplicate_of")) else ""
        print(
            f"{c['candidate_id']} [{c['status']}] {c['pattern']!r} -> {c['skill']}"
            f" | {c['source_query'][:40]}{high}"
        )
    print(f"共 {len(cands)} 条")


def review_interactive(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """逐条展示, 输入 y(approve)/n(reject)/s(skip), 写回 reviewed_at。"""
    now = now_iso()
    pending = [c for c in cands if c.get("status") == "pending"]
    print(f"待确认 {len(pending)} 条（y=approve / n=reject / s=skip / q=quit）")
    for c in pending:
        while True:
            print("-" * 70)
            print(f"[{c['candidate_id']}] {c['pattern']!r}")
            print(f"    skill={c['skill']} | 来源query: {c['source_query'][:60]}")
            print(
                f"    来源={c['source']} | 生成={c['created_at'][:10]} | 失效={c['expires_at'][:10]}"
            )
            if c.get("duplicate_of"):
                print(f"    警告: 与生产规则重复 -> {c['duplicate_of']}")
            if c["skill"] == "NONE":
                print("    警告: NONE 候选 high_risk")
            ans = input("    y/n/s: ").strip().lower()
            if ans in ("y", "n", "s"):
                break
            if ans == "q":
                return cands
        if ans == "y":
            c["status"] = "approved"
        elif ans == "n":
            c["status"] = "rejected"
        else:
            continue
        c["reviewed_at"] = now
        c["review_note"] = c.get("review_note") or (
            "interactive_approve" if ans == "y" else "interactive_reject"
        )
    return cands


def parse_review_md(md_path: str | Path) -> list[str]:
    """解析离线确认清单中勾选 [x] 的候选 ID。"""
    p = Path(md_path)
    if not p.exists():
        raise SystemExit(f"ERROR: {p} 不存在")
    ids: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*(C\d{4})\s*\|.*\[\s*x\s*\]\s*\|", line)
        if m:
            ids.append(m.group(1))
    return ids


def confirm_from_review(md_path: str | Path) -> int:
    """把离线勾选 ID 标记 approved。"""
    ids = parse_review_md(md_path)
    if not ids:
        print("没有勾选任何候选")
        return 0
    cands = load_candidates(_paths()["candidates"])
    now = now_iso()
    id_set = set(ids)
    n = 0
    for c in cands:
        if c["candidate_id"] in id_set and c.get("status") == "pending":
            c["status"] = "approved"
            c["reviewed_at"] = now
            c["review_note"] = "offline_review"
            n += 1
    if n:
        save_candidates(cands, _paths()["candidates"])
    print(f"from-review: {n} 条 -> approved")
    return n


def _fallback_insert(src: str, entries: list[tuple[str, str]]) -> str:
    """在 _DIRECT_MAP_FALLBACK 列表结尾前 append 新条目（preserve 全部既有注释/内容）。"""
    m = re.search(re.escape("_DIRECT_MAP_FALLBACK = ["), src)
    if not m:
        raise SystemExit("ERROR: direct_layer.py 未找到 _DIRECT_MAP_FALLBACK")
    start = m.end()
    close = re.search(r"\n\]\n{2,}def direct_route", src[start:])
    if not close:
        raise SystemExit("ERROR: 找不到 fallback 列表结尾（def direct_route 前置）")
    insert_pos = start + close.start()  # 指向 "\n]" 的换行
    block = "".join(
        f"    ({json.dumps(p, ensure_ascii=False)}, {json.dumps(s, ensure_ascii=False)}),\n"
        for p, s in entries
    )
    if not block:
        return src
    return src[:insert_pos] + "\n" + block + src[insert_pos + 1 :]


def verify_sync() -> dict[str, Any]:
    """对比 direct_map.json 与 fallback 提取结果, 返回差异报告。"""
    paths = _paths()
    json_entries = load_production(paths["json"])
    fallback_entries = [tuple(e) for e in extract_fallback(paths["layer"])]
    json_tuples = [tuple(e) for e in json_entries]
    diff: list[dict[str, Any]] = []
    if len(json_tuples) != len(fallback_entries):
        diff.append(
            {
                "type": "count",
                "json_count": len(json_tuples),
                "fallback_count": len(fallback_entries),
            }
        )
    else:
        for i, (a, b) in enumerate(zip(json_tuples, fallback_entries, strict=True)):
            if a != b:
                diff.append({"type": "entry", "index": i, "json": a, "fallback": b})
    return {
        "json_count": len(json_tuples),
        "fallback_count": len(fallback_entries),
        "diff_count": len(diff),
        "diff": diff[:20],
        "ok": not diff,
    }


def _backup(entries: list[list[str]]) -> dict[str, Path]:
    """apply 前备份 JSON + direct_layer.py + meta，返回备份路径。"""
    paths = _paths()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp = paths["temp"]
    temp.mkdir(parents=True, exist_ok=True)
    backup_json = temp / f"direct_map_backup_{ts}.json"
    backup_py = temp / f"direct_map_backup_{ts}.direct_layer.py"
    backup_meta = temp / f"direct_map_backup_{ts}.meta.json"
    _atomic_write_json(backup_json, entries)
    shutil.copy2(paths["layer"], backup_py)
    _atomic_write_json(
        backup_meta,
        {
            "ts": ts,
            "applied_ids": [],
            "json_path": str(paths["json"]),
            "layer_path": str(paths["layer"]),
            "candidates_path": str(paths["candidates"]),
        },
    )
    return {"json": backup_json, "py": backup_py, "meta": backup_meta}


def _enforce_budget(cands: list[dict[str, Any]]) -> None:
    """预算门禁前置：usage > limit 即拒绝并提示淘汰。"""
    usage = direct_map_budget.budget_usage(cands=cands)
    if usage["used"] > usage["limit"]:
        prune_ids = direct_map_budget.maybe_prune(cands=cands, dry_run=True)
        raise SystemExit(
            f"预算门禁拒绝 apply: used={usage['used']} > limit={usage['limit']}\n"
            f"请先执行淘汰: python eval/direct_map_budget.py --evict {','.join(prune_ids)}"
        )


def _dual_write(new_entries: list[list[str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """JSON append + fallback 文本 append + 守恒校验，返回 (sync, backup)。

    返回类型修正（#mypy-historical-debt-2026-08-11）: 原签名写 -> dict[str, Any]
    但实际返回 (sync, backup) tuple, 跟调用方解构一致. 修正后 caller 拿到的
    backup 就是 dict, 不会推断成 str, 链式 attr/index 错一并消失.
    """
    paths = _paths()
    production = load_production(paths["json"])
    backup = _backup(production)
    _atomic_write_json(paths["json"], production + new_entries)
    src = paths["layer"].read_text(encoding="utf-8")
    new_src = _fallback_insert(src, [tuple(e) for e in new_entries])  # type: ignore[misc]  # mypy-historical-debt: tuple[str, ...] vs tuple[str, str]
    _atomic_write_text(paths["layer"], new_src)
    sync = verify_sync()
    if not sync["ok"]:
        raise SystemExit(f"守恒校验失败, 中止（用 --rollback 恢复）: {sync['diff'][:5]}")
    return sync, backup


def apply_approved(ids: list[str], dry_run: bool = True, yes: bool = False) -> dict[str, Any]:
    """预算门禁前置 → JSON append → fallback append → 守恒校验 → applied_at 写回。"""
    paths = _paths()
    cands = load_candidates(paths["candidates"])
    id_set = set(ids)
    target = [c for c in cands if c["candidate_id"] in id_set]
    missing = sorted(id_set - {c["candidate_id"] for c in target})
    not_approved = [c["candidate_id"] for c in target if c.get("status") != "approved"]
    if missing:
        raise SystemExit(f"ERROR: 候选不存在: {missing}")
    if not_approved:
        raise SystemExit(f"ERROR: 以下候选非 approved（须先人工确认）: {not_approved}")
    if not target:
        raise SystemExit("ERROR: 无可 apply 候选")

    _enforce_budget(cands)
    if dry_run:
        print(f"[DRY-RUN] 将 apply {len(target)} 条到生产(尾部=最低优先级):")
        for c in target:
            print(f"  {c['candidate_id']} {c['pattern']!r} -> {c['skill']}")
        return {"applied": 0, "dry_run": True, "ids": [c["candidate_id"] for c in target]}

    if not yes:
        print("即将 apply 以下候选到生产 DIRECT_MAP:")
        for c in target:
            print(f"  {c['candidate_id']} {c['pattern']!r} -> {c['skill']}")
        ans = input(f"确认 apply 以上 {len(target)} 条? [y/N]: ").strip().lower()
        if ans != "y":
            raise SystemExit("已取消（未写生产）")

    new_entries = [[c["pattern"], c["skill"]] for c in target]
    sync, backup = _dual_write(new_entries)

    # applied_at 写回候选 + 备份 meta 记录 applied_ids
    now = now_iso()
    for c in target:
        c["status"] = "applied"
        c["applied_at"] = now
        c["review_note"] = c.get("review_note") or "applied"
    save_candidates(cands, paths["candidates"])
    with backup["meta"].open(encoding="utf-8") as f:
        meta = json.load(f)
    meta["applied_ids"] = [c["candidate_id"] for c in target]
    _atomic_write_json(backup["meta"], meta)

    return {
        "applied": len(target),
        "dry_run": False,
        "ids": [c["candidate_id"] for c in target],
        "json_count": sync["json_count"],
        "fallback_count": sync["fallback_count"],
        "backup": str(backup["json"]),
    }


def _latest_backup() -> Path | None:
    temp = _paths()["temp"]
    backups = sorted(temp.glob("direct_map_backup_*.json")) if temp.exists() else []
    return backups[-1] if backups else None


def rollback(backup_path: str | Path | None = None) -> dict[str, Any]:
    """恢复备份: JSON + direct_layer.py + 候选 applied→approved。"""
    paths = _paths()
    if backup_path is None:
        latest = _latest_backup()
        if latest is None:
            raise SystemExit("ERROR: 无可用备份（Temp/direct_map_backup_*.json）")
        backup_path = latest
    backup_json = Path(backup_path)
    if not backup_json.exists():
        raise SystemExit(f"ERROR: 备份不存在 {backup_json}")
    stem = str(backup_json)[: -len(".json")]
    backup_py = Path(stem + ".direct_layer.py")
    backup_meta = Path(stem + ".meta.json")
    if not backup_py.exists():
        raise SystemExit(f"ERROR: 备份不完整（缺 {backup_py.name}）")

    with backup_json.open(encoding="utf-8") as f:
        original = json.load(f)
    _atomic_write_json(paths["json"], original)
    shutil.copy2(backup_py, paths["layer"])

    applied_ids: list[str] = []
    if backup_meta.exists():
        with backup_meta.open(encoding="utf-8") as f:
            meta = json.load(f)
        applied_ids = meta.get("applied_ids", [])

    reverted = 0
    if applied_ids:
        cands = load_candidates(paths["candidates"])
        for c in cands:
            if c["candidate_id"] in applied_ids and c.get("status") == "applied":
                c["status"] = "approved"
                c["applied_at"] = None
                reverted += 1
        if reverted:
            save_candidates(cands, paths["candidates"])

    sync = verify_sync()
    return {
        "restored_json": str(paths["json"]),
        "restored_layer": str(paths["layer"]),
        "reverted_candidates": reverted,
        "verify_sync": sync,
    }


def _cmd_apply(args: argparse.Namespace) -> int:
    """--apply-ids / --apply-all-approved（铁律: 显式 + 二次确认）。"""
    if args.apply_ids:
        ids = [x.strip() for x in args.apply_ids.split(",") if x.strip()]
    else:
        cands = load_candidates(_paths()["candidates"])
        ids = [c["candidate_id"] for c in cands if c.get("status") == "approved"]
        if not ids:
            print("无 approved 候选可 apply")
            return 0
        if not args.yes:
            print("即将 apply 以下 approved 候选:")
            for c in cands:
                if c["candidate_id"] in set(ids):
                    print(f"  {c['candidate_id']} {c['pattern']!r} -> {c['skill']}")
            ans = input(f"确认 apply 以上 {len(ids)} 条? [y/N]: ").strip().lower()
            if ans != "y":
                raise SystemExit("已取消（未写生产）")
    result = apply_approved(ids, dry_run=args.dry_run, yes=args.yes)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DIRECT_MAP 人工确认/apply/回滚")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--status", default="pending")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--review", action="store_true", help="交互确认 y/n/s")
    ap.add_argument("--from-review", metavar="MD")
    ap.add_argument("--apply-ids", metavar="C0001,C0002")
    ap.add_argument("--apply-all-approved", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--yes", action="store_true", help="非交互二次确认（配合 --apply-all-approved）"
    )
    ap.add_argument("--rollback", nargs="?", const="__latest__", metavar="BACKUP")
    ap.add_argument("--verify-sync", action="store_true")
    a = ap.parse_args(argv)

    if a.list:
        list_candidates(a.status, a.limit)
        return 0
    if a.review:
        cands = load_candidates(_paths()["candidates"])
        updated = review_interactive(cands)
        save_candidates(updated, _paths()["candidates"])
        print("review 完成, 已写回 candidates.jsonl")
        return 0
    if a.from_review:
        confirm_from_review(a.from_review)
        return 0
    if a.apply_ids or a.apply_all_approved:
        return _cmd_apply(a)
    if a.rollback:
        bp = None if a.rollback == "__latest__" else a.rollback
        result = rollback(bp)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if a.verify_sync:
        print(json.dumps(verify_sync(), ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
