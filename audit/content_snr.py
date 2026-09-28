#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
content_snr.py — D2-8 内容信噪比（噪声大雨点小专项，满分6）
=====================================================================
把"内容质量"纳入焚诀评分系统：衡量全局记忆 / skill 树 / lessons 库的
信号 vs 噪声，四子项：
  M1 元经验占比   — lessons 库中"教系统维护系统"的元经验字节占比（目标 ≤30%）
  M2 大 SKILL 文件 — ~/.agents/skills 顶层 SKILL.md >40KB 数量（目标 ≤1）
  M3 索引声明失真  — 索引/壳文件里的尺寸、条数声明与真实现状不符的数量（目标 0）
  M4 自检金标准陈旧 — degradation-test 硬编码期望值/口径与数据层不符项（目标 0）

明确豁免（刻意为之，不扣分）：
  - 4KB 零豁免拆分导致的文件碎片化、part 文件数量、叙事分段，一律不计入
    任何子项；其合规性由主线② D2-7（fragment_detector）单独维护。

规则：
  - 只读，不修改任何文件。
  - 输出行含子项实测值 + 一行 "内容信噪比: X/6"，供 scorecard.py 解析。
用法:
  python audit/content_snr.py
"""
import os
import re
import subprocess
import json

GM = r"<MEMORY_ROOT>"
LESSONS = os.path.join(GM, "lessons")
AGENTS_SKILLS = r"<USER_HOME>\.agents\skills"
DT_PATH = os.path.join(GM, "scripts", "degradation-test.ps1")

META_RE = re.compile(
    r"memory-tooling|skill-gov|audit-leak|verify-|size-|measure|probe|"
    r"philosophy|oc-dispatch|powershell|annotation",
    re.I,
)


def sz(p):
    return os.path.getsize(p) if os.path.exists(p) else 0


def read(p):
    if not os.path.exists(p):
        return ""
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


# ---------- M1 元经验占比（archive 冷存储不计入，对齐审计铁律2） ----------
lfiles = [
    f for f in os.listdir(LESSONS)
    if f.endswith(".md") and os.path.isfile(os.path.join(LESSONS, f))
    and not f.startswith("lessons-archive")
]
lbytes = sum(sz(os.path.join(LESSONS, f)) for f in lfiles)
meta_files = [f for f in lfiles if META_RE.search(f)]
meta_bytes = sum(sz(os.path.join(LESSONS, f)) for f in meta_files)
meta_ratio = meta_bytes / lbytes if lbytes else 0
m1 = 1.0 if meta_ratio <= 0.30 else max(0.0, 1.0 - (meta_ratio - 0.30) / 0.30)

# ---------- M2 大 SKILL 文件（仅用户级顶层 skill，不含插件/嵌套子 skill） ----------
big = []
if os.path.isdir(AGENTS_SKILLS):
    for name in sorted(os.listdir(AGENTS_SKILLS)):
        sp = os.path.join(AGENTS_SKILLS, name, "SKILL.md")
        if os.path.isfile(sp) and sz(sp) > 40 * 1024:
            big.append("%s=%.1fKB" % (name, sz(sp) / 1024))
big_count = len(big)
m2 = 1.0 if big_count <= 1 else max(0.0, 1.0 - (big_count - 1) / 5.0)

# ---------- M3 索引声明失真 ----------
stale = []
p0_size = sz(os.path.join(LESSONS, "lessons-p0.md"))
p1 = read(os.path.join(LESSONS, "lessons.part1.md"))
if "≤1KB" in p1 and p0_size > 1024:
    stale.append("lessons.part1 声明 lessons-p0 ≤1KB, 实际 %.1fKB" % (p0_size / 1024))
p0_items = len(
    re.findall(r"^##\s+\S", read(os.path.join(LESSONS, "lessons-p0.md")), re.M)
)
# R164: 解析声明的条数（原硬编码 4 条，lessons-p0 现为 8 条）
m4 = re.search(r"P0 必须记住（(\d+)条", p1)
if m4 and int(m4.group(1)) != p0_items:
    stale.append("lessons.part1 声明 P0 必须记住 %s 条, 实际 %d 条" % (m4.group(1), p0_items))
# R164: 元经验合并后检查单一叶子上限声明 vs 实际分卷数
gov = read(os.path.join(LESSONS, "lessons-system-maintenance.part1.md"))
gov_parts = [
    f for f in lfiles
    if f.startswith("lessons-system-maintenance.part")
]
m = re.search(r"≤16KB（当前\s*(\d+)\s*卷）", gov)
if m and int(m.group(1)) != len(gov_parts):
    stale.append(
        "system-maintenance 声明 %s 卷, 实际 %d 个 part" % (m.group(1), len(gov_parts))
    )
stale_count = len(stale)
m3 = 1.0 if stale_count == 0 else max(0.0, 1.0 - 0.34 * stale_count)

# ---------- M4 自检金标准陈旧 ----------
golden_stale = 0
golden_notes = []
dt_src = read(DT_PATH)
total_actual = 0
sc_dir = os.path.join(GM, "skill_content")
if os.path.isdir(sc_dir):
    for f in os.listdir(sc_dir):
        if f.endswith(".json") and f != "skill_ids.json":
            try:
                with open(os.path.join(sc_dir, f), encoding="utf-8") as fh:
                    total_actual += len(json.load(fh).get("skills", []))
            except Exception:
                pass  # 单文件损坏跳过累计（SNR 比对允许小幅偏差，R207 P2-1 留痕）
# 期望总数硬编码（新写法 $expectedTotal = N / 旧写法 -eq N）与数据层实际比对
mm = re.search(r"\$expectedTotal\s*=\s*(\d+)", dt_src) or \
     re.search(r"3a: Total skills.*?\$total\s+-eq\s+(\d+)", dt_src, re.S)
if mm and int(mm.group(1)) != total_actual:
    golden_stale += 1
    golden_notes.append(
        "degradation-test 硬编码期望 %s vs 实际 %d" % (mm.group(1), total_actual)
    )
# skill_ids.json 必须从领域 JSON 枚举中排除（否则 13 域变 14、总数翻倍假 FAIL）
if "skill_ids.json" not in dt_src and re.search(r"skill_content\\\*\.json", dt_src):
    golden_stale += 1
    golden_notes.append(
        "degradation-test 未排除 skill_ids.json → 领域数/总数虚高(288 vs 144)"
    )
dt_fails = -1
try:
    dt_run = subprocess.run(
        ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", DT_PATH],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    dt_fails = dt_run.stdout.count("FAIL")
except Exception as e:
    golden_notes.append("degradation-test 运行失败: %s" % e)
if dt_fails > 0 and golden_stale == 0:
    golden_stale += 1
    golden_notes.append("degradation-test 仍有 FAIL=%d（陈旧项未识别或数据层真损）" % dt_fails)
m4 = 1.0 if golden_stale == 0 else max(0.0, 1.0 - 0.5 * golden_stale)

# ---------- 汇总 ----------
score = round(6 * (m1 + m2 + m3 + m4) / 4, 1)

print("M1 元经验占比: %.1f%% (%d/%d files, %.1f/%.1f KB) -> %.2f" % (
    meta_ratio * 100, len(meta_files), len(lfiles),
    meta_bytes / 1024, lbytes / 1024, m1))
print("M2 大SKILL文件(>40KB): %d %s -> %.2f" % (big_count, big, m2))
print("M3 索引声明失真: %d %s -> %.2f" % (
    stale_count, "[" + "; ".join(stale) + "]" if stale else "", m3))
print("M4 自检金标准陈旧: %d (degradation-test FAIL=%s) %s -> %.2f" % (
    golden_stale, dt_fails, "[" + "; ".join(golden_notes) + "]" if golden_notes else "", m4))
print("内容信噪比: %s/6 [M1=%.2f M2=%.2f M3=%.2f M4=%.2f]" % (score, m1, m2, m3, m4))
