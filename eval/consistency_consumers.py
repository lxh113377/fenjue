#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
consistency_consumers.py — 「同一实体名的排除清单必须全消费方一致」门禁（R276，2026-09-22）

【为什么需要它】
2026-09-22 一天之内出现**三次同型故障**，根因完全相同：
    环境/清单变了，某个消费方**只改了注释或根本没跟**，导致假失败或假通过。

  ① `eval/status_report.py` fallback 分支硬编码「144 skill / 13领域」（陈旧常量）
  ② `<MEMORY_ROOT>/scripts/sync_global_memory.ps1` 的 junction 清单仍含
     已退役端 `oc`×2 / `cc`×2 ⇒ 每日 03:00 桌面报告**永久假 FAIL**
  ③ `<MEMORY_ROOT>/scripts/skill_content_parse_guard.py` 的非域排除清单漏了
     `index_manifest.json`（**其余 5 个消费方都已排除**）⇒ 恒 exit 1

共同形态：**某个实体（文件名/目录名/端 id）对 N 个消费方都"该被排除"，但排除清单散落在
各处、靠人工同步 —— 改 N-1 处、漏第 N 处，就成了永久性假门禁。**

【本门禁的判据】
维护「实体 → 应排除/应识别它的消费方清单」，逐项核验每个消费方文件里**确实提到该实体名**。
- 任一消费方缺失 → FAIL（列出补齐位置）
- 另附**动态发现**：扫出「遍历 skill_content/*.json」但未排除两个非域文件的脚本 → WARN

【边界】
- 只验「消费方是否知晓该实体」，不验其排除写法是否语义正确（那是各脚本自身门禁的事）。
- 实体与消费方清单**人工维护**（新增消费方时须同步登记）—— 登记缺失本身由动态发现兜。
- 不自动改任何文件（只报告）。

用法:
  python eval/consistency_consumers.py [--json]
退出码: 0=PASS / 1=FAIL
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import GLOBAL_MEMORY  # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GM_SCRIPTS = os.path.join(GLOBAL_MEMORY, "scripts")

# ============================================================
# 实体清单：实体名 → 为什么它必须被排除 + 应识别它的消费方
# ============================================================
# 每条消费方 = (显示名, 文件路径)。核验方式：文件内容中出现实体字面量即视为"已识别"。
ENTITIES = {
    # ---- skill_content/ 下的非域 JSON：任何遍历域 JSON 的脚本都必须排除 ----
    "index_manifest.json": {
        "reason": "build_indexes.py 生成的 pickle 完整性清单，无 domain/count/skills 键；"
                  "混入域遍历会致 schema 校验假 FAIL、计数虚高",
        # R276 锚点判据：skill_ids.json 是"必然被排除"的同类基准 ——
        # **凡出现 skill_ids.json 的每一行，都必须同时出现 index_manifest.json**。
        # 这比对整文件搜实体名精确得多：首版用全文比对时，注释里提一嘴就算"已识别"，
        # 对照桩（注入缺陷）因此放过 ⇒ 改为行级锚点后成功抓出
        # functional_dim_checks.py:268 的同类遗漏（该文件 L130 排了、L268 只排了 skill_ids.json）。
        "anchor": "skill_ids.json",
        # R276 二次收敛：锚点行还必须**形如排除语句** —— 首版只按「行含锚点名」筛，
        # 把注释、docstring、写文件语句（json.dump(..., "skill_ids.json")）全当锚点，
        # 产出 6 项含大量误报的 FAIL。加上形态约束后只留真缺陷。
        "anchor_line_re": r"(not\s+in\s*\(|notin\s*@\(|NON_DOMAIN_FILES\s*=|DOMAIN_FILE_SKIPS\s*=|f\s+in\s*\(|f\s*==\s*['\"])",
        "consumers": [
            ("build_indexes.py:DOMAIN_FILE_SKIPS", os.path.join(PROJECT_DIR, "eval", "build_indexes.py")),
            ("skill_content_parse_guard.py:NON_DOMAIN_FILES", os.path.join(GM_SCRIPTS, "skill_content_parse_guard.py")),
            ("auto-fix.ps1", os.path.join(GM_SCRIPTS, "auto-fix.ps1")),
            ("degradation-test.ps1", os.path.join(GM_SCRIPTS, "degradation-test.ps1")),
            ("derivative_watch.py", os.path.join(PROJECT_DIR, "eval", "derivative_watch.py")),
            ("functional_dim_checks.py", os.path.join(PROJECT_DIR, "eval", "functional_dim_checks.py")),
        ],
    },
    "skill_ids.json": {
        "reason": "纯 id 列表（非域 JSON），同上",
        "consumers": [
            ("build_indexes.py:DOMAIN_FILE_SKIPS", os.path.join(PROJECT_DIR, "eval", "build_indexes.py")),
            ("skill_content_parse_guard.py:NON_DOMAIN_FILES", os.path.join(GM_SCRIPTS, "skill_content_parse_guard.py")),
            ("auto-fix.ps1", os.path.join(GM_SCRIPTS, "auto-fix.ps1")),
            ("degradation-test.ps1", os.path.join(GM_SCRIPTS, "degradation-test.ps1")),
            ("derivative_watch.py", os.path.join(PROJECT_DIR, "eval", "derivative_watch.py")),
            ("functional_dim_checks.py", os.path.join(PROJECT_DIR, "eval", "functional_dim_checks.py")),
        ],
    },
    # ---- 非技能目录：扫描技能目录的脚本必须排除 ----
    "_trash": {
        "reason": "回收区，非技能目录；计入会致技能数虚高",
        "consumers": [
            ("scan_skills.ps1:NonSkillDirNames", os.path.join(GM_SCRIPTS, "scan_skills.ps1")),
            ("run-health-check.ps1:NonSkillDirs", os.path.join(GM_SCRIPTS, "run-health-check.ps1")),
        ],
    },
    "_my-skills": {
        "reason": "在册元技能（registry 内含、带 SKILL.md、user-invocable:false）；"
                  "**必须计入**而非排除 —— 曾因 `-notlike '_*'` 被误排除致守恒校验假告警",
        "consumers": [
            ("scan_skills.ps1:NonSkillDirNames", os.path.join(GM_SCRIPTS, "scan_skills.ps1")),
        ],
        "note": "判据：该名**不得**出现在排除白名单 $NonSkillDirNames 的括号内（允许在注释/其它处出现）",
        "forbidden_in": True,
        # R276：必须限定范围 —— 首版用「全文出现即 FAIL」被判据自身缺陷误报
        # （该名在注释里合理出现），改为只在排除白名单的括号内比对。
        "forbidden_scope": r"\$NonSkillDirNames\s*=\s*@\(([^)]*)\)",
    },
    # ---- 退役端：端清单/ junction 检查中不得再出现 ----
    "openclaw": {
        "reason": "OpenClaw 端已于 2026-09-21 退役（权威 = truth_constants.json endpoints.retired.oc）",
        "consumers": [
            ("sync_global_memory.ps1:Verify-Junctions", os.path.join(GM_SCRIPTS, "sync_global_memory.ps1")),
        ],
        "note": "判据：退役端不得出现在应有矩阵（Ep 列表）中",
        "forbidden_in": True,
    },
}

# 动态发现：这些脚本若出现「遍历 skill_content 域 JSON」特征，就必须排除下列非域文件
DYNAMIC_TRAVERSE_MARKERS = ["skill_content"]
DYNAMIC_MUST_EXCLUDE = ["index_manifest.json", "skill_ids.json"]
DYNAMIC_SCAN_DIRS = [GM_SCRIPTS, os.path.join(PROJECT_DIR, "eval")]
DYNAMIC_EXTS = (".py", ".ps1")
# 排除自身与已知的非遍历脚本（避免噪音）
DYNAMIC_SELF = os.path.basename(__file__)
DYNAMIC_IGNORE = {"skill_content_parse_guard.py"}  # 由 ENTITIES 段覆盖，不重复报


from io_utils import read_text as _io_read_text  # P1-5: 读写原语唯一实现


def read_text(path):
    return _io_read_text(path, errors='ignore')


def check_entities():
    """返回 (failures, notes)。"""
    failures, notes = [], []
    for ent, spec in ENTITIES.items():
        forbidden = spec.get("forbidden_in", False)
        anchor = spec.get("anchor")
        for label, path in spec["consumers"]:
            if not os.path.exists(path):
                failures.append(f"[{ent}] 消费方文件不存在: {label} -> {path}")
                continue
            text = read_text(path)
            present = ent in text
            if anchor:
                # 锚点判据：逐行核验「凡排除 anchor 的行必同时排除 ent」。
                # 锚点行 = 含 anchor 且**形如排除语句**（anchor_line_re 约束），
                # 避免把注释/写文件语句误当排除清单。
                line_re = spec.get("anchor_line_re")
                rows = []
                for i, ln in enumerate(text.splitlines()):
                    if anchor not in ln:
                        continue
                    if line_re and not re.search(line_re, ln):
                        continue
                    rows.append((i + 1, ln))
                if not rows:
                    failures.append(
                        f"[{ent}] {label} 未找到形如排除语句的锚点行（判据面失效，R247）")
                else:
                    bad = [n for n, ln in rows if ent not in ln]
                    if bad:
                        failures.append(
                            f"[{ent}] {label} 第 {bad} 行排除了锚点 '{anchor}' 却未排除 '{ent}' "
                            f"（共 {len(rows)} 处锚点行）")
                    else:
                        notes.append(
                            f"[{ent}] {label} {len(rows)} 处锚点行均已同时排除 ✔")
                continue
            if forbidden:
                # 反向判据：不该出现在指定范围内（未给定范围才退化为全文比对）
                target, scope = text, spec.get("forbidden_scope")
                if scope:
                    m = re.search(scope, text, re.S)
                    if not m:
                        # 范围判据失效必须显式报错，不能静默放过（R247 零命中即失效）
                        failures.append(f"[{ent}] {label} 未匹配到 forbidden_scope 范围（判据失效）")
                        continue
                    target = m.group(1)
                if ent in target:
                    failures.append(
                        f"[{ent}] {label} 中'{ent}'出现在禁止范围内 —— "
                        f"退役端应出清、元技能应计入（{spec['reason']}）")
                else:
                    notes.append(
                        f"[{ent}] {label} 未把它列入禁止范围 ✔（{'范围:' + 'limited' if scope else '全文'}）")
            else:
                if not present:
                    failures.append(
                        f"[{ent}] {label} 未排除 '{ent}' —— 该消费方会把它当作正常对象处理。"
                        f"原因: {spec['reason']}")
                else:
                    notes.append(f"[{ent}] {label} 已识别 '{ent}' ✔")
    return failures, notes


def dynamic_scan():
    """扫出遍历 skill_content 域 JSON 但未排除两个非域文件的脚本。"""
    warns, scanned = [], 0
    for d in DYNAMIC_SCAN_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(DYNAMIC_EXTS) or fn == DYNAMIC_SELF or fn in DYNAMIC_IGNORE:
                continue
            path = os.path.join(d, fn)
            try:
                text = read_text(path)
            except Exception:  # noqa: BLE001
                continue
            scanned += 1
            if not any(m in text for m in DYNAMIC_TRAVERSE_MARKERS):
                continue
            # 是否在遍历 json（含目录列举/glob 特征）
            if not re.search(r"(listdir|Get-ChildItem|glob|os\.walk)", text):
                continue
            missing = [e for e in DYNAMIC_MUST_EXCLUDE if e not in text]
            if missing:
                # 跨盘（<MEMORY_ROOT>\scripts）时 relpath 抛 ValueError，退化为绝对路径
                try:
                    label = os.path.relpath(path, PROJECT_DIR)
                except ValueError:
                    label = path
                warns.append(
                    f"{label}: 提及 skill_content 且遍历文件，"
                    f"但未出现 {missing} —— 请确认是否需要排除")
    return warns, scanned


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    failures, notes = check_entities()
    warns, scanned = dynamic_scan()

    if args.json:
        print(json.dumps({
            "entities": len(ENTITIES),
            "consumers_checked": sum(len(s["consumers"]) for s in ENTITIES.values()),
            "failures": failures,
            "dynamic_warns": warns,
            "scripts_scanned": scanned,
            "pass": not failures,
        }, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    print("=" * 68)
    print("consistency_consumers — 实体排除清单跨消费方一致性（R276）")
    print("=" * 68)
    total_consumers = sum(len(s["consumers"]) for s in ENTITIES.values())
    print(f"实体 {len(ENTITIES)} 个 | 消费方核验 {total_consumers} 项 | 扫描脚本 {scanned} 个")
    print()
    for n in notes:
        print(f"  ✔ {n}")
    if warns:
        print()
        for w in warns:
            print(f"  ⚠ [动态发现] {w}")
    print()
    if failures:
        print(f"❌ FAIL — {len(failures)} 项不一致:")
        for f in failures:
            print(f"  - {f}")
        print("\n处置：把缺失实体的排除补进对应消费方（或若该消费方已不再遍历，从本清单移除登记）。")
        return 1
    print("✅ PASS — 所有实体的排除清单在全部消费方处一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
