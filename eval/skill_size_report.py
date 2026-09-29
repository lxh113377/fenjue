# -*- coding: utf-8 -*-
"""P2-4 技能主文件体量盘点 + 棘轮（顶层 SKILL.md 向 ≤12KB 收拢）。

面与量纲（2026-09-25 复算，别信下面这行的历史读数）：
    python -c "import sys;sys.path.insert(0,'eval');from pathlib import Path;import config;print(len(list(Path(config.GLOBAL_SKILLS).glob('*/SKILL.md'))))"   # 顶层数
    python -c "import sys;sys.path.insert(0,'eval');import skill_size_report as s;print(s.nested_count())"                                                  # 不在本面的嵌套数（只申报）
    python eval/skill_size_report.py --json | python -c "import json,sys;d=json.load(sys.stdin);print(d['total'])"                                          # 本次盘点面
背景：2026-09-23 实测 151 个顶层 SKILL.md 平均 10,373 B，超 4KB 107 个、超 10KB 47 个、
超 20KB 22 个（最大 60.8 KB）。对标参照：Superpowers 用 word budget 测试守门（主文件 ~1000 词）。

本脚本提供两件事（不直接改技能，避免批量误伤）：
  · **盘点**：按体量档位列出超限技能 + 建议动作（拆 references / 精简 / 保留）
  · **棘轮**：把「超限技能集合与体量」冻结为基线（`skill_size_baseline.json`），
    只许降不许升 —— 与 C20 同族的可持续治理，避免"一次性拆完又长回来"

用法::

    python eval/skill_size_report.py              # 盘点（对照基线）
    python eval/skill_size_report.py --update     # 采集/收紧基线
    python eval/skill_size_report.py --json
    python eval/skill_size_report.py --top 30
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR))
from config import GLOBAL_SKILLS  # noqa: E402
SKILLS_DIR = Path(GLOBAL_SKILLS)
BASELINE_FILE = EVAL_DIR / "skill_size_baseline.json"
SCHEMA = "fenjue-skill-size-baseline-v1"

# 档位（soft limit；分卷不受限，见 references/ 体量治理）
TIERS = [
    (20 * 1024, "超重（>20KB）", "优先拆 references/ 或精简正文"),
    (12 * 1024, "超标（>12KB）", "建议拆 references/（soft limit = 12KB）"),
    (4 * 1024, "偏大（>4KB）", "纪律线 4KB；按需拆卷"),
]


def scan(skills_dir=None):
    """盘上字节数（`stat().st_size`），不是"读成文本再编码回去"的字节数。

    旧口径 `len(read_text().encode())` 会把 CRLF 吃成 LF：实测 15 个 SKILL.md 被低估，
    最多 688 B（story-import 盘上 36,837 B 只算出 36,149 B）。全仓其它体量闸（R161 分卷 4096 B、
    part-size、噪声门禁）量的都是盘上字节，此处不同口径 ⇒ 盘上已越线、算出来却未越线的文件会静默过关。
    """
    root = Path(skills_dir) if skills_dir else SKILLS_DIR
    rows = []
    for fp in sorted(root.glob("*/SKILL.md")):
        try:
            rows.append({"skill": fp.parent.name, "bytes": fp.stat().st_size})
        except OSError:
            continue
    rows.sort(key=lambda r: -r["bytes"])
    return rows


def nested_count(skills_dir=None):
    """不在本面的嵌套 SKILL.md（分卷/references 子技能）—— 只申报，不静默少算（D-69 族）。"""
    root = Path(skills_dir) if skills_dir else SKILLS_DIR
    try:
        return sum(1 for p in root.rglob("SKILL.md") if len(p.relative_to(root).parts) > 2)
    except OSError:
        return -1


def tier_of(n):
    for limit, label, action in TIERS:
        if n > limit:
            return label, action
    return "合规（<=4KB）", "-"


def load_baseline(path=None):
    p = Path(path) if path else BASELINE_FILE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_baseline(rows, path=None):
    p = Path(path) if path else BASELINE_FILE
    over12 = [r for r in rows if r["bytes"] > 12 * 1024]
    over20 = [r for r in rows if r["bytes"] > 20 * 1024]
    over4 = [r for r in rows if r["bytes"] > 4 * 1024]
    payload = {
        "schema": SCHEMA,
        "generated": datetime.now().strftime("%Y-%m-%d"),
        "note": ("技能主文件体量棘轮：超限集合与体量只许降不许升。新增技能主文件禁超 soft limit（12KB）。"
                 "收紧用 --update（仅在真实拆卷/精简后执行）。"),
        "total": len(rows),
        "avg_bytes": round(sum(r["bytes"] for r in rows) / len(rows)) if rows else 0,
        "counts": {"over_4kb": len(over4), "over_12kb": len(over12), "over_20kb": len(over20)},
        "over_12kb": {r["skill"]: r["bytes"] for r in over12},
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def check(skills_dir=None, baseline=None):
    rows = scan(skills_dir)
    base = load_baseline(baseline)
    failures, notes = [], []
    if not rows:
        return (["未扫描到任何 SKILL.md（skills_dir 配置错误，R247）"], [], rows)
    if base is None:
        return (["基线缺失（先跑 --update）"], [], rows)
    base_map = base.get("over_12kb") or {}
    for r in rows:
        if r["bytes"] <= 12 * 1024:
            continue
        b = base_map.get(r["skill"])
        if b is None:
            failures.append("新增超限技能 {0}（{1} B > 12KB soft limit）".format(r["skill"], r["bytes"]))
        elif r["bytes"] > b:
            failures.append("{0} 体量上升 {1} -> {2} B".format(r["skill"], b, r["bytes"]))
        elif r["bytes"] < b:
            notes.append("{0} 已下降 {1} -> {2} B（可 --update 收紧）".format(r["skill"], b, r["bytes"]))
    return (failures, notes, rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="技能主文件体量盘点 + 棘轮（P2-4）")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--skills-dir", default=None)
    ap.add_argument("--baseline", default=None)
    args = ap.parse_args(argv)

    if args.update:
        rows = scan(args.skills_dir)
        p = write_baseline(rows, args.baseline)
        over12 = len([r for r in rows if r["bytes"] > 12 * 1024])
        over20 = len([r for r in rows if r["bytes"] > 20 * 1024])
        print("✅ 基线已更新: {0}（{1} 技能 / 超12KB {2} / 超20KB {3}）".format(p, len(rows), over12, over20))
        return 0

    failures, notes, rows = check(args.skills_dir, args.baseline)
    if args.json:
        print(json.dumps({"schema": "fenjue-skill-size-report-v1", "ok": not failures,
                          "total": len(rows), "failures": failures, "notes": notes,
                          "top": rows[:args.top]}, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    over4 = len([r for r in rows if r["bytes"] > 4096])
    over12 = len([r for r in rows if r["bytes"] > 12 * 1024])
    over20 = len([r for r in rows if r["bytes"] > 20 * 1024])
    avg = round(sum(r["bytes"] for r in rows) / len(rows)) if rows else 0
    print("📏 技能主文件体量盘点（{0} 个 SKILL.md）".format(len(rows)))
    nd = nested_count(args.skills_dir)
    if nd > 0:
        print("   另有 {0} 个嵌套 SKILL.md 不在本面（references/ 子技能，分卷不受限）".format(nd))
    print("   平均 {0} B ｜ >4KB {1} ｜ >12KB {2} ｜ >20KB {3}".format(avg, over4, over12, over20))
    print("   " + "-" * 70)
    for r in rows[:args.top]:
        label, action = tier_of(r["bytes"])
        print("   {0:>7} B  {1:<28} {2}  → {3}".format(r["bytes"], r["skill"], label, action))
    print("   " + "-" * 70)
    if failures:
        print("🔴 [GATE:skill-size-fail]")
        for x in failures[:10]:
            print("   ❌ " + x)
        return 1
    for x in notes[:5]:
        print("   ℹ️ " + x)
    print("✅ [GATE:skill-size-pass] 超限集合与体量未回退（拆卷工作可分批推进）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
