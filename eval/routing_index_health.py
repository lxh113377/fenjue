#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""routing_index_health.py — 路由健康 + 索引健康统一诊断入口（R196-05 固化，2026-08-16）

定位：将 fenjue-routing-health-check 的 CHECK-2（memory_index 壳死链扫描）与
CHECK-4（主题指针表 check_index_refs）合并为单次执行的统一诊断脚本，替代
「每次诊断时手工拼接 5 份子报告」的做法——两段子报告 + 总判定集中输出。

与 SKILL.md 的关系：
  - CHECK-2 段 = memory_index.md / memory_index_full.md / path_index.md 壳死链扫描
    （引用相对 <MEMORY_ROOT>；memory/memory_content 历史报告引用允许缺失；
    日期模板占位符跳过——与 SKILL.md CHECK-2 步骤 2 过滤规则一致）
  - CHECK-4 段 = 复用 eval/check_index_refs.py 的 check_file 逻辑（等效机器执行器
    check_index_refs.py --json），扫 memory_index.part3*.md 主题指针表路径存在性

用法：
  python eval/routing_index_health.py                       # 统一诊断（两段 + 总判定）
  python eval/routing_index_health.py --json                # 机器可读（schema fenjue-routing-index-health-v1）
  python eval/routing_index_health.py --skip-check2         # 只跑 CHECK-4（诊断提速）
  python eval/routing_index_health.py --skip-check4         # 只跑 CHECK-2
  python eval/routing_index_health.py --check4-target <f>   # CHECK-4 指定目标（透传 check_index_refs 语义）

退出码：0 = 两段全 PASS；1 = 任一 FAIL（可挂门禁/CI）。

回归测试：
  python -m pytest eval/tests/test_routing_index_health.py -q
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# check_index_refs 与本脚本同目录 → 直接 import 复用解析/检查逻辑
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_index_refs as cir  # noqa: E402

# ── 权威路径 ─────────────────────────────────────────────────────────────────
GLOBAL_MEMORY = cir.GLOBAL_MEMORY

# CHECK-2 目标：memory_index 壳（memory_index_full.md / path_index.md 存在才扫）
CHECK2_TARGETS = [
    GLOBAL_MEMORY / "meta" / "memory_index.md",
    GLOBAL_MEMORY / "meta" / "memory_index_full.md",
    GLOBAL_MEMORY / "meta" / "path_index.md",
]

# CHECK-2 过滤：这些前缀的引用允许不存在（历史报告/运行期生成）
CHECK2_EXEMPT_PREFIXES = ("memory/", "memory_content/")
# CHECK-2 过滤：日期模板占位符（运行时按当日日期生成实际文件，非死链）
DATE_PLACEHOLDER_RE = ("YYYY", "W##", "MMDD")


def _is_date_placeholder(ref: str) -> bool:
    return any(tok in ref for tok in DATE_PLACEHOLDER_RE)


def _scan_check2(verbose: bool = False) -> dict:
    """CHECK-2：memory_index 壳死链扫描。返回 {status, refs_total, ok, dead, files}。"""
    dead: list[dict] = []
    refs_total = 0
    ok = 0
    scanned_files = []
    for path in CHECK2_TARGETS:
        if not path.exists():
            continue  # 可选目标（memory_index_full/path_index）不存在则跳过
        content = path.read_text(encoding="utf-8", errors="replace")
        refs = cir.extract_refs(content)
        scanned_files.append(str(path))
        for ref in refs:
            if not cir._is_path_ref(ref):
                continue
            # CHECK-2 特有过滤：历史报告引用 / 日期模板占位符
            rr = cir._norm(ref)
            if rr.startswith(CHECK2_EXEMPT_PREFIXES):
                continue
            if _is_date_placeholder(rr):
                continue
            refs_total += 1
            cands = cir.resolve_candidates(ref)
            hit = next((c for c in cands if Path(c).exists()), None)
            if hit:
                ok += 1
            else:
                dead.append({"src": str(path), "ref": ref})
                if verbose:
                    print(f"  🔴 DEAD: {ref} (来源 {path.name})")
    return {
        "status": "PASS" if not dead else "FAIL",
        "refs_total": refs_total,
        "ok": ok,
        "dead": dead,
        "files": scanned_files,
    }


def _scan_check4(targets: list[Path] | None = None, verbose: bool = False) -> dict:
    """CHECK-4：主题指针表路径存在性（复用 check_index_refs.check_file）。

    与 `check_index_refs.py --json` 等效（同 check_file 逻辑、同解析规则）。
    """
    targets = targets or cir.DEFAULT_TARGETS
    all_missing: list[str] = []
    checked = 0
    scanned = []
    for t in targets:
        if not t.exists():
            continue  # 目标不存在跳过（与 check_index_refs 一致）
        r = cir.check_file(t, verbose=verbose)
        scanned.append(str(t))
        checked += r["checked"]
        all_missing.extend(r["missing"])
    return {
        "status": "PASS" if not all_missing else "FAIL",
        "refs_checked": checked,
        "missing": all_missing,
        "files": scanned,
    }


# ── --check-paths：四端根目录 + junction 表对账（R199 多消费方固化，2026-08-17）──
# 消费方：周维护 Step 4m（季度实测校验第 2 项）、Step 4l 全量兜底、CI 门禁——
# 统一调本函数，口径一致；--paths-root 可追加自定义根目录（多环境参数化）。
PATH_ROOTS = [
    r"<MEMORY_ROOT>",
    r"<SKILLS_ROOT>",
    r"<USER_HOME>\.workbuddy",
    r"<USER_HOME>\.claude",
    r"<USER_HOME>\.trae-cn",
]
JUNCTION_SRC = GLOBAL_MEMORY / "meta" / "path_index.md"
# 挂载点映射（名称 → 实际 junction 路径；2026-08-17 实测校准）。
# is_junction() 校验：表标 ✅ 但挂载点不存在/非 junction → FAIL（覆盖「目标在但 junction
# 已移除」——OC 端 2026-08-17 实测零 junction，target 存在性校验无法发现此类失效）。
# 标 ❌（预期移除）的条目不入此表（如 QW skills）。
JUNCTION_MOUNTS = {
    "OC memory_content": r"<USER_HOME>\.openclaw\memory_content",
    "OC memory": r"<USER_HOME>\.openclaw\memory",
    "OC skills": r"<USER_HOME>\.openclaw\skills",
    "WB memory": r"<USER_HOME>\.workbuddy\memory",
    "WB skills": r"<USER_HOME>\.workbuddy\skills",
    "CC memory_content": r"<USER_HOME>\.claude\memory_content",
    "CC skills": r"<USER_HOME>\.claude\skills",
    "TC skills": r"<USER_HOME>\.trae-cn\skills",
}


def _scan_paths(roots: list[str] | None = None) -> dict:
    """各端根目录存在性。返回 {status, roots: [{path, exists}]}。"""
    roots = roots or PATH_ROOTS
    items = [{"path": p, "exists": os.path.exists(p)} for p in roots]
    bad = [i for i in items if not i["exists"]]
    return {"status": "PASS" if not bad else "FAIL", "roots": items}


def _scan_junctions(src: Path | None = None) -> dict:
    """Junction 表对账：目标存在性 + 挂载点实体（is_junction）双重校验。

    行格式：`| 名称 → | 目标 | 状态 |`；状态 ✅=应存在，❌=已移除（预期不存在）。
    判定：
      - 标 ✅ 但目标不存在 → FAIL（target 失效）
      - 标 ✅ 且目标存在，但名称在 JUNCTION_MOUNTS 且挂载点不存在/非 junction
        → FAIL（mount 失效——「目标在但 junction 已移除」，OC 端实测场景）
      - 标 ❌ 但目标存在 → WARN（可能已恢复，不 FAIL）
      - 标 ❌ → 不校验挂载点（预期移除）
    非路径目标（—）跳过。
    """
    src = src or JUNCTION_SRC
    if not src.exists():
        return {"status": "FAIL", "error": f"junction 源不存在: {src}", "items": []}
    items = []
    fail = False
    warn = 0
    for ln in src.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\|\s*(.+?)\s*→\s*\|\s*(.+?)\s*\|\s*(✅|❌)", ln)
        if not m:
            continue
        name, target, mark = m.group(1), m.group(2), m.group(3)
        name, target = name.strip(), target.strip()
        if target in ("—", "-", ""):
            continue  # 非路径条目（如「桌面 … 无junction」）
        exists = os.path.exists(target)
        # 挂载点实体校验（仅标 ✅ 且名称在映射表时）
        mount = JUNCTION_MOUNTS.get(name)
        mount_valid = None
        if mark == "✅" and mount:
            mount_valid = Path(mount).is_junction()
        if mark == "✅" and not exists:
            fail = True
            items.append({"name": name, "target": target, "mark": mark,
                          "exists": exists, "mount": mount, "mount_valid": mount_valid,
                          "consistent": False})
        elif mark == "✅" and exists and mount_valid is False:
            fail = True  # 目标在但挂载点已失效（OC 实测场景）
            items.append({"name": name, "target": target, "mark": mark,
                          "exists": exists, "mount": mount, "mount_valid": False,
                          "consistent": False})
        elif mark == "❌" and exists:
            warn += 1
            items.append({"name": name, "target": target, "mark": mark,
                          "exists": exists, "mount": mount, "mount_valid": mount_valid,
                          "consistent": None})  # 可能已恢复
        else:
            items.append({"name": name, "target": target, "mark": mark,
                          "exists": exists, "mount": mount, "mount_valid": mount_valid,
                          "consistent": True})
    return {"status": "FAIL" if fail else "PASS", "items": items, "warn": warn}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="路由健康 + 索引健康统一诊断（CHECK-2 + CHECK-4 合并；--check-paths 追加各端根目录+junction 对账）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--skip-check2", action="store_true", help="跳过 CHECK-2（只跑索引健康）")
    ap.add_argument("--skip-check4", action="store_true", help="跳过 CHECK-4（只跑壳死链）")
    ap.add_argument("--check4-target", action="append", default=None,
                    help="CHECK-4 指定检查文件（可多次）；默认 DEFAULT_TARGETS")
    ap.add_argument("--check-paths", action="store_true",
                    help="追加各端根目录存在性 + junction 表对账（Step 4m 消费）")
    ap.add_argument("--paths-root", action="append", default=None,
                    help="追加自定义根目录（可多次，多环境参数化）")
    ap.add_argument("--verbose", action="store_true", help="输出每条引用解析明细")
    args = ap.parse_args(argv)


    r2 = None if args.skip_check2 else _scan_check2(verbose=args.verbose)
    r4 = None if args.skip_check4 else _scan_check4(
        [Path(t) for t in args.check4_target] if args.check4_target else None,
        verbose=args.verbose)
    # --check-paths：四端根目录 + junction 表对账（Step 4m 消费；可与 CHECK-2/4 并存）
    roots = list(PATH_ROOTS) + (args.paths_root or [])
    rp = _scan_paths(roots) if args.check_paths else None
    rj = _scan_junctions() if args.check_paths else None

    all_pass = True
    for r in (r2, r4, rp, rj):
        if r is not None and r["status"] == "FAIL":
            all_pass = False

    if args.json:
        print(json.dumps({
            "schema": "fenjue-routing-index-health-v1",
            "ts": datetime.now().isoformat(timespec="seconds"),
            "check2": r2,
            "check4": r4,
            "paths": rp,
            "junctions": rj,
            "all_pass": all_pass,
        }, ensure_ascii=False, indent=2))
    else:
        if r2 is not None:
            print("=== CHECK-2 SUB-REPORT ===")
            print(f"状态: {r2['status']}")
            print(f"引用总数: {r2['refs_total']} | 存活: {r2['ok']} | 死链: {len(r2['dead'])}")
            for d in r2["dead"][:15]:
                print(f"  🔴 DEAD: {d['ref']} (来源 {d['src']})")
            print("=== CHECK-2 END ===")
            print()
        if r4 is not None:
            print("=== CHECK-4 SUB-REPORT ===")
            print(f"状态: {r4['status']}")
            print(f"路径引用: {r4['refs_checked']} | 缺失: {len(r4['missing'])}")
            for m in r4["missing"][:15]:
                print(f"  🔴 MISS: {m}")
            print("=== CHECK-4 END ===")
            print()
        if rp is not None:
            print("=== PATHS SUB-REPORT ===")
            print(f"状态: {rp['status']}（各端根目录存在性）")
            for i in rp["roots"]:
                print(f"  {'✅' if i['exists'] else '🔴'} {i['path']}")
            print("=== PATHS END ===")
            print()
        if rj is not None:
            print("=== JUNCTIONS SUB-REPORT ===")
            print(f"状态: {rj['status']}（目标存在性 + 挂载点 is_junction 双重校验）")
            for i in rj["items"]:
                mark = "✅" if i["consistent"] else ("⚠️" if i["consistent"] is None else "🔴")
                detail = f"表标 {i['mark']}，目标{'存在' if i['exists'] else '不存在'}"
                if i.get("mount") and i["mount_valid"] is False:
                    detail += f"，⚠️ 挂载点失效（{i['mount']} 非 junction/不存在）"
                print(f"  {mark} {i['name']} → {i['target']}（{detail}）")
            if rj.get("warn"):
                print(f"  ⚠️ {rj['warn']} 项标 ❌ 但目标存在（可能已恢复，需人工确认）")
            print("=== JUNCTIONS END ===")
            print()
        print("=== 总判定 ===")
        if r2 is not None:
            print(f"路由健康（CHECK-2 壳死链）: {r2['status']}")
        if r4 is not None:
            print(f"索引健康（CHECK-4 指针表）: {r4['status']}")
        if rp is not None:
            print(f"各端根目录（PATHS）: {rp['status']}")
        if rj is not None:
            print(f"Junction 对账（JUNCTIONS）: {rj['status']}")
        print(f"统一诊断: {'PASS 全部可循' if all_pass else 'FAIL 存在缺失'}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
