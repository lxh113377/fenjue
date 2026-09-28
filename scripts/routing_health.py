#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""routing_health.py — 路由健康度检查（item 13 CI 化，仓库本地镜像版）

将 fenjue-routing-health-check 技能的三项 CHECK 改写为脚本，检查目标指向
**仓库内可挂载的镜像目录**（默认 `global_memory_mirror/`，可用 `--root` 或
环境变量 `FENJUE_GM_ROOT` 覆盖），从而解除对 `<MEMORY_ROOT>` 绝对路径的依赖，
可在 CI 环境周期化执行。

CHECK-1: skill_routing 领域计数 vs skill_content/*.json 实际 skill 数
CHECK-2: memory_index*.md / path_index.md 引用死链扫描
CHECK-3: VERSION_LOCK 分卷连续性 + sync_health.json registry_count 一致性

镜像目录结构（与 <MEMORY_ROOT> 同构，仅取体检所需子集）：
  <root>/skill_routing.md (+ .partN.md)
  <root>/skill_content/*.json
  <root>/meta/memory_index*.md (+ memory_index_full.md / path_index.md)
  <root>/meta/VERSION_LOCK*.md
  <root>/sync_health.json

退出码：
  根目录不存在          -> 全部 SKIP，exit 0（CI 未挂载镜像时保持绿，仅提示）
  根存在但出现 FAIL    -> exit 1（真实漂移，告警）
  仅 SKIP（文件缺失）  -> exit 0
"""
import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path


def read_split(root, rel_base):
    """读取 base.md 并拼接其 .part1..N.md 分卷（R168：壳+全部分卷）。"""
    base = os.path.join(root, rel_base)
    paths = [base]
    stem = base[:-3] if base.endswith(".md") else base
    i = 1
    while True:
        p = f"{stem}.part{i}.md"
        if os.path.exists(p):
            paths.append(p)
            i += 1
        else:
            break
    chunks = []
    for p in paths:
        if os.path.exists(p):
            try:
                chunks.append(Path(p).read_text(encoding="utf-8"))
            except Exception:
                pass  # 单路径读失败跳过（多源拼接容错，R207 P2-1 留痕）
    return "\n".join(chunks)


def _count_skills_in_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, list):
        return sum(1 for s in data if isinstance(s, dict) and s.get("name"))
    if isinstance(data, dict):
        if isinstance(data.get("skills"), list):
            return len(data["skills"])
        return len(data)
    return 0


def check_1_count(root):
    """skill_routing 领域计数 vs skill_content 实际 skill 数。"""
    details = []
    status = "PASS"
    sc_dir = os.path.join(root, "skill_content")
    if not os.path.isdir(sc_dir):
        return {"name": "CHECK-1 计数校验", "status": "SKIP",
                "summary": "skill_content/ 不存在", "details": details}

    actual = {}
    for f in sorted(glob.glob(os.path.join(sc_dir, "*.json"))):
        bn = os.path.basename(f)
        if bn in ("embeddings.npy", "skill_ids.json", "tfidf_matrix.npz", "tfidf_vectorizer.pkl"):
            continue
        cnt = _count_skills_in_json(f)
        if cnt is None:
            details.append(f"解析失败: {bn}")
            continue
        actual[os.path.splitext(bn)[0]] = cnt

    text = read_split(root, "skill_routing.md")
    annotated = {}
    total_annotated = None
    tm = re.search(r"(?:总计|技能总数)[：:]\s*(\d+)", text)
    if not tm:
        tm = re.search(r"(\d+)\s*个\s*skill", text)
    if tm:
        total_annotated = int(tm.group(1))

    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0] in ("领域", "文件") or "技能数" in cells[0]:
            continue
        fm = re.search(r"skill_content[/\\]([\w\-]+)\.json", cells[1])
        domain = fm.group(1) if fm else cells[0]
        if not cells[2].isdigit():
            continue
        annotated[domain] = int(cells[2])

    total_actual = sum(actual.values())
    for d, n in annotated.items():
        if d not in actual:
            status = "FAIL"
            details.append(f"MISSING_JSON: {d} 标注 {n} 但 skill_content 无对应 JSON")
        elif actual[d] != n:
            status = "FAIL"
            details.append(f"COUNT_MISMATCH: {d} 标注 {n} != 实际 {actual[d]}")
    for d in actual:
        if d not in annotated:
            status = "FAIL"
            details.append(f"MISSING_ROUTING: {d} 有 {actual[d]} 条但 skill_routing 无对应领域行")

    if total_annotated is not None and total_annotated != total_actual:
        status = "FAIL"
        details.append(f"TOTAL_DRIFT: 标注总计 {total_annotated} != 实际总计 {total_actual}")

    summary = (f"实际 {total_actual} 条 / {len(actual)} 域"
               + (f" | 标注总计 {total_annotated}" if total_annotated is not None else ""))
    return {"name": "CHECK-1 计数校验", "status": status, "summary": summary,
            "details": details, "total_actual": total_actual}


def _normalize_ref(ref, root):
    ref = ref.replace("\\", "/").strip()
    ref = re.sub(r"^[./]+", "", ref)
    ref = re.sub(r"^[A-Za-z]:[\\/]?global_memory[\\/]?", "", ref, flags=re.IGNORECASE)
    ref = re.sub(r"^[\\/]?global_memory[\\/]?", "", ref, flags=re.IGNORECASE)
    ref = ref.lstrip("/")
    if re.search(r"YYYY|W\d\d|MMDD", ref):
        return None
    if ref.startswith("memory/") or ref.startswith("memory_content/"):
        return None
    return ref


def check_2_deadlinks(root):
    """memory_index*.md / path_index.md 引用死链扫描。"""
    details = []
    status = "PASS"
    idx_files = []
    for pat in ("meta/memory_index*.md", "meta/memory_index_full.md", "meta/path_index.md"):
        idx_files += glob.glob(os.path.join(root, pat))
    if not idx_files:
        return {"name": "CHECK-2 死链扫描", "status": "SKIP",
                "summary": "memory_index 文件不存在", "details": details}

    refs = set()
    for fp in idx_files:
        try:
            txt = Path(fp).read_text(encoding="utf-8")
        except Exception:
            continue
        for m in re.finditer(r"`([^`]+\.(?:md|json|py|txt|yaml|yml|toml))`", txt):
            refs.add(m.group(1))
        for m in re.finditer(r"\]\(([^)]+\.(?:md|json|py|txt|yaml|yml|toml))\)", txt):
            refs.add(m.group(1))
        for m in re.finditer(r"(?:^|\||\s)([\w./\\-]+\.(?:md|json|py|txt|yaml|yml|toml))(?=\s|\||$)", txt):
            refs.add(m.group(1))

    dead = 0
    scope_skip = 0
    for r in sorted(refs):
        norm = _normalize_ref(r, root)
        if norm is None:
            continue
        # 仅校验镜像范围内（skill_content/ 与 meta/）的引用；其余（core/lessons/info/
        # 绝对路径/仓库路径等）属镜像子集之外，跳过不报死链，避免误报。
        if not (norm.startswith("skill_content/") or norm.startswith("meta/")):
            scope_skip += 1
            continue
        if not os.path.exists(os.path.join(root, norm)):
            dead += 1
            details.append(f"DEAD: {r} -> {norm}")
    if dead:
        status = "FAIL"
    return {"name": "CHECK-2 死链扫描", "status": status,
            "summary": f"引用 {len(refs)} | 范围内 {len(refs) - scope_skip} | 死链 {dead} | 范围外跳过 {scope_skip}",
            "details": details}


def check_3_version(root, total_actual=None):
    """VERSION_LOCK 分卷连续性 + sync_health registry_count 一致性。"""
    details = []
    status = "PASS"
    vl_base = os.path.join(root, "meta", "VERSION_LOCK.md")
    vl_stem = vl_base[:-3]
    parts = [p for p in glob.glob(f"{vl_stem}.part*.md") if re.search(r"\.part\d+\.md$", p)]
    parts_sorted = sorted(parts, key=lambda p: int(re.search(r"\.part(\d+)\.md$", p).group(1)))
    if not os.path.exists(vl_base) and not parts_sorted:
        return {"name": "CHECK-3 版本一致性", "status": "SKIP",
                "summary": "VERSION_LOCK 不存在", "details": details}

    # 分卷连续性
    expected = 1
    for p in parts_sorted:
        n = int(re.search(r"\.part(\d+)\.md$", p).group(1))
        if n != expected:
            status = "FAIL"
            details.append(f"VL_INDEX_DRIFT: 分卷缺 part{expected}（跳到 part{n}）")
        expected += 1

    # sync_health registry_count vs CHECK-1 实际总数
    sh_path = os.path.join(root, "sync_health.json")
    if os.path.exists(sh_path):
        try:
            sh = json.loads(Path(sh_path).read_text(encoding="utf-8"))
            rc = sh.get("checks", {}).get("registry", {}).get("registry_count")
            if rc is not None and total_actual is not None and int(rc) != int(total_actual):
                status = "FAIL"
                details.append(f"REGISTRY_COUNT_STALE: sync_health={rc} != 实际={total_actual}")
        except Exception:
            details.append("SH_PARSE_FAIL: sync_health.json 解析失败")
    else:
        details.append("SH_MISSING: sync_health.json 不存在")
    return {"name": "CHECK-3 版本一致性", "status": status,
            "summary": f"VERSION_LOCK 分卷 {len(parts_sorted)}", "details": details}


def main():
    ap = argparse.ArgumentParser(description="路由健康度检查（镜像目录版）")
    ap.add_argument("--root", default=os.environ.get("FENJUE_GM_ROOT", "global_memory_mirror"))
    ap.add_argument("--json-out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "routing-health.json"))
    args = ap.parse_args()

    root = args.root
    if not os.path.isdir(root):
        msg = (f"[SKIP] 镜像根目录不存在: {root} "
               f"（CI 未挂载 global_memory 镜像；本地用 sync_routing_mirror.py 生成）")
        print(msg)
        gh = os.environ.get("GITHUB_STEP_SUMMARY")
        if gh:
            with Path(gh).open("a", encoding="utf-8") as f:
                f.write(f"# 路由健康度\n\n- {msg}\n")
        Path(args.json_out).write_text(
            json.dumps({"root": root, "status": "SKIP", "checks": []},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        sys.exit(0)

    c1 = check_1_count(root)
    c2 = check_2_deadlinks(root)
    c3 = check_3_version(root, total_actual=c1.get("total_actual"))
    # 将 CHECK-1 实际总数注入 CHECK-3 的 registry 一致性判定
    checks = [c1, c2, c3]
    overall = "PASS"
    for c in checks:
        if c["status"] == "FAIL":
            overall = "FAIL"

    L = ["# 路由健康度快检报告", ""]
    L.append(f"- 镜像根: `{root}`")
    L.append(f"- 总评: **{overall}**")
    L.append("")
    for c in checks:
        icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}.get(c["status"], c["status"])
        L.append(f"## {c['name']} {icon} {c['status']}")
        L.append(f"- {c['summary']}")
        for d in c["details"][:30]:
            L.append(f"  - {d}")
        L.append("")
    md = "\n".join(L)

    print(md)
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with Path(gh).open("a", encoding="utf-8") as f:
            f.write(md + "\n")
    Path(args.json_out).write_text(
        json.dumps({"root": root, "status": overall, "checks": checks},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    sys.exit(1 if overall == "FAIL" else 0)


if __name__ == "__main__":
    main()
