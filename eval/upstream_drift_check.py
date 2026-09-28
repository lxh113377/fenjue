# -*- coding: utf-8 -*-
"""P1-1 上游技能漂移检测 —— 比对本地技能与上游开源技能（默认 obra/superpowers）。

对标产出：本仓 4 个技能与上游同源但已分叉（executing-plans 仅为上游 1/8），此前**无任何
机制察觉**。本脚本把「同源关系 + 上游版本 + 漂移量」变成可复跑的检查。

判据（三级）：
  · 行数比 / 字节比 —— 本地显著小于上游 => 「落后」（差距等级）
  · difflib 相似度   —— 文本层面重合度
  · 章节差集         —— **上游有而本地没有的标题**（最直观的缺口清单）

上游目录缺失 => 不算失败（可选依赖），只提示如何重建镜像。
用法::

    python eval/upstream_drift_check.py            # 报告
    python eval/upstream_drift_check.py --json     # 机器可读
    python eval/upstream_drift_check.py --ref <dir>  # 指定上游镜像目录
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR))
from config import GLOBAL_SKILLS  # noqa: E402
MAP_FILE = EVAL_DIR / "upstream_skills.json"
LOCAL_SKILLS_DIR = Path(GLOBAL_SKILLS)
DEFAULT_REF = Path(os.environ.get("SUPERPOWERS_REF",
                                  Path(os.environ.get("TEMP", "/tmp")) / "superpowers_ref_20260923"))


def load_map(path=None):
    p = Path(path) if path else MAP_FILE
    return json.loads(p.read_text(encoding="utf-8"))


def _headings(text):
    return [ln.strip() for ln in text.splitlines() if ln.lstrip().startswith("#")]


def _stats(text):
    return {"bytes": len(text.encode("utf-8")), "lines": len(text.splitlines()), "headings": _headings(text)}


def compare_one(local_path, upstream_path, top_missing=6):
    lt = local_path.read_text(encoding="utf-8", errors="replace")
    ut = upstream_path.read_text(encoding="utf-8", errors="replace")
    ls, us = _stats(lt), _stats(ut)
    ratio = difflib.SequenceMatcher(None, lt, ut).quick_ratio()
    lset = set(ls["headings"])
    missing = [h for h in us["headings"] if h not in lset]
    extra = [h for h in ls["headings"] if h not in set(us["headings"])]
    size_ratio = (ls["bytes"] / us["bytes"]) if us["bytes"] else 0.0
    if size_ratio < 0.5:
        level = "落后（<50% 体量）"
    elif size_ratio < 0.8:
        level = "偏差（50~80% 体量）"
    elif size_ratio > 1.5:
        level = "本地扩展（>150% 体量）"
    else:
        level = "接近（80~150% 体量）"
    return {
        "local_bytes": ls["bytes"], "upstream_bytes": us["bytes"],
        "local_lines": ls["lines"], "upstream_lines": us["lines"],
        "size_ratio": round(size_ratio, 3), "similarity": round(ratio, 3),
        "level": level,
        "missing_headings": missing[:top_missing],
        "missing_headings_total": len(missing),
        "extra_headings_total": len(extra),
    }


def run(ref_dir=None, map_file=None):
    data = load_map(map_file)
    ref = Path(ref_dir) if ref_dir else DEFAULT_REF
    up_root = ref / "skills"
    rows, err = [], ""
    if not up_root.is_dir():
        err = ("上游镜像不存在: {0}（重建：git clone --depth 1 "
               "https://github.com/{1}.git \"{0}\"）").format(up_root, data["upstream"]["repo"])
        return data, rows, err
    for m in data["mappings"]:
        lp = LOCAL_SKILLS_DIR / m["local"] / "SKILL.md"
        up = up_root / m["upstream"] / "SKILL.md"
        if not lp.exists():
            rows.append({"local": m["local"], "upstream": m["upstream"], "status": "本地缺失",
                         "relation": m.get("relation", "")})
            continue
        if not up.exists():
            rows.append({"local": m["local"], "upstream": m["upstream"], "status": "上游缺失",
                         "relation": m.get("relation", "")})
            continue
        r = compare_one(lp, up)
        r.update({"local": m["local"], "upstream": m["upstream"],
                  "relation": m.get("relation", ""), "status": "ok"})
        rows.append(r)
    return data, rows, err


def main(argv=None):
    ap = argparse.ArgumentParser(description="上游技能漂移检测（P1-1）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ref", default=None, help="上游镜像目录")
    ap.add_argument("--map", default=None, help="映射表路径")
    args = ap.parse_args(argv)

    data, rows, err = run(args.ref, args.map)
    up = data["upstream"]

    if args.json:
        print(json.dumps({"schema": "fenjue-upstream-drift-v1",
                          "upstream": {"repo": up["repo"], "version": up["version"]},
                          "ok": bool(rows), "error": err, "rows": rows},
                         ensure_ascii=False, indent=2))
        return 0 if rows else 1

    print("🔍 上游技能漂移检测（上游 = {0} {1}）".format(up["repo"], up["version"]))
    if err:
        print("   ⚠️ " + err)
        return 0
    print("   追踪 {0} 个技能".format(len(rows)))
    print("   " + "-" * 72)
    for r in rows:
        if r.get("status") != "ok":
            print("   ❌ {0:<26} {1}".format(r["local"], r["status"]))
            continue
        print("   • {0:<26} {1}".format(r["local"], r["level"]))
        print("     字节 {0} -> {1}（比 {2}）｜相似度 {3}｜关系 {4}".format(
            r["upstream_bytes"], r["local_bytes"], r["size_ratio"], r["similarity"], r["relation"]))
        if r["missing_headings_total"]:
            print("     上游有而本地缺的章节（{0} 个，列前 {1}）:".format(
                r["missing_headings_total"], len(r["missing_headings"])))
            for h in r["missing_headings"]:
                print("        - " + h[:88])
    print("   " + "-" * 72)
    print("✅ 报告完毕（处置需人工裁决：吸收 / 保持分叉 / 弃用；策略见 upstream_skills.json _policy）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
