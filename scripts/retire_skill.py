#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retire_skill.py — 退役 skill 一键脚本（R198.6，防回滚治本）

把「删除 skill → 登记黑名单 → 重建派生件 → 门禁验证」四步固化为一键操作，
根治 2026-08-16 事故：build_registry 无脑补齐把已删 skill 拉回注册表。

执行链（fail-closed，任一步失败即中止）：
  ① git rm -r <skill>（<SKILLS_ROOT>，可恢复：git 历史有源）
  ② 从注册表移除（unified-skills-index.json + cross_platform_map.json，防守恒 FAIL）
  ③ 登记 retired_skills 黑名单（truth_constants.json，防下次批量入库还原）
  ④ build_indexes.py --apply 重建派生件（BGE/TF-IDF/注册表计数对齐）
  ⑤ verify_truth_consistency.py 门禁（C1-C13 全绿才收尾）

用法:
  python scripts/retire_skill.py <skill_name>          # 完整执行链
  python scripts/retire_skill.py <skill_name> --dry-run # 预览动作，不写盘
  python scripts/retire_skill.py --list                # 列出当前黑名单
  python scripts/retire_skill.py <skill_name> --skip-rebuild  # 跳过重建（仅删+登记）

退出码:
  0 = 成功（退役完成 + 门禁全绿）
  1 = 校验失败（技能不存在 / 已在黑名单 / 系统目录保护 / 门禁 FAIL）
  2 = 用法错误（缺参数 / 未知参数）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "eval"))
# P1-6 批次②: 单源引用（env 可覆盖）
from config import GLOBAL_SKILLS  # noqa: E402
TC_JSON = os.path.join(REPO_ROOT, "eval", "truth_constants.json")
BUILD_INDEXES = os.path.join(REPO_ROOT, "eval", "build_indexes.py")
VERIFY = os.path.join(REPO_ROOT, "eval", "verify_truth_consistency.py")
MIRROR_FIX = os.path.join(
    REPO_ROOT, "skill", "sync", "check-skill-mirror.ps1"
)

# 系统/基础设施目录：禁止退役（删除会破坏仓库结构）
SYSTEM_DIRS = {"_trash", "_temp", "_bak", "_my-skills", ".git", ".hermes", "hooks"}


def log(step: str, msg: str, ok: bool = True):
    icon = "OK " if ok else "FAIL"
    print(f"[{icon}] {step}: {msg}")


def load_tc() -> dict:
    return json.loads(Path(TC_JSON).read_text(encoding="utf-8"))


def save_tc(tc: dict):
    Path(TC_JSON).write_text(
        json.dumps(tc, ensure_ascii=False, indent=2), encoding="utf-8")


def get_retired(tc: dict) -> list:
    return tc.get("retired_skills", [])


def validate(name: str, dry_run: bool = False) -> tuple[bool, str]:
    """参数校验：存在性 / 黑名单去重 / 系统目录保护 / 合法性。"""
    if not name or name.strip() != name or "/" in name or "\\" in name or ".." in name:
        return False, f"非法技能名: {name!r}（禁路径分隔符/空白/..）"
    if name in SYSTEM_DIRS:
        return False, f"{name} 是系统/基础设施目录，禁止退役"
    tc = load_tc()
    retired = get_retired(tc)
    if name in retired:
        return False, f"{name} 已在黑名单（{len(retired)} 项），无需重复退役"
    skill_dir = os.path.join(GLOBAL_SKILLS, name)
    if not os.path.isdir(skill_dir):
        return False, f"{name} 不在 {GLOBAL_SKILLS}（磁盘无此目录），无法退役"
    return True, "校验通过"


def git_rm(name: str) -> bool:
    r = subprocess.run(  # external-write-ok: 退役流程设计内受控删除（git 历史可恢复，R198.6 用户显式发起）
        ["git", "-C", GLOBAL_SKILLS, "rm", "-r", "-q", name],
        capture_output=True, text=True, timeout=120,  # P1-6
    )
    if r.returncode != 0:
        log("git rm", f"{name} 失败: {r.stderr.strip()[:200]}", ok=False)
        return False
    log("git rm", f"{name} 已从 <SKILLS_ROOT> 删除（git 历史可恢复）")
    return True


def remove_from_registry(name: str) -> bool:
    """从注册表移除（unified-skills-index + cross_platform_map），防 build_indexes 守恒 FAIL。"""
    ok = True
    for rel, key in (("skill/registry/unified-skills-index.json", "skills"),
                     ("skill/registry/cross_platform_map.json", "skills")):
        path = os.path.join(REPO_ROOT, rel)
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            bucket = data.get(key, {})
            if name in bucket:
                del bucket[name]
                data[key] = bucket
                Path(path).write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                log("注册表", f"{name} 已从 {os.path.basename(path)} 移除")
            else:
                log("注册表", f"{name} 不在 {os.path.basename(path)}（跳过）")
        except Exception as e:
            log("注册表", f"{os.path.basename(path)} 更新失败: {e!r}", ok=False)
            ok = False
    return ok


def add_to_blacklist(name: str) -> bool:
    tc = load_tc()
    retired = get_retired(tc)
    if name not in retired:
        retired.append(name)
        retired.sort()
        tc["retired_skills"] = retired
        # 更新变更记录
        changed = tc.get("_changed", "")
        if "retire_skill.py" not in changed:
            tc["_changed"] = changed + "；" + f"2026-08-16 retire_skill.py 登记 {name}"
        save_tc(tc)
        log("黑名单", f"{name} 已登记（共 {len(retired)} 项）")
    return True


def rebuild_indexes() -> bool:
    r = subprocess.run(
        [sys.executable, BUILD_INDEXES, "--apply"],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=900,  # P1-6
    )
    if r.returncode != 0:
        log("重建", f"build_indexes --apply 失败: {r.stderr.strip()[-300:]}", ok=False)
        return False
    log("重建", "派生件已重建（BGE/TF-IDF/注册表计数对齐）")
    return True


def run_verify() -> bool:
    r = subprocess.run(
        [sys.executable, VERIFY],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=300,  # P1-6
    )
    if r.returncode != 0:
        tail = [ln for ln in r.stdout.strip().splitlines() if "❌" in ln or "FAIL" in ln]
        log("verify", f"门禁 FAIL: {'; '.join(tail[:4])}", ok=False)
        return False
    log("verify", "verify C1-C13 全绿")
    return True


def mirror_sync() -> None:
    if os.path.exists(MIRROR_FIX):
        log("提示", f"建议收尾跑镜像同步: powershell -File {MIRROR_FIX} -Fix")
    else:
        log("提示", "check-skill-mirror.ps1 不存在（跳过镜像提示）")


def list_blacklist() -> int:
    tc = load_tc()
    retired = get_retired(tc)
    print(f"当前退役黑名单（{len(retired)} 项）:")
    for i, s in enumerate(retired, 1):
        print(f"  {i:2d}. {s}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="退役 skill 一键脚本（R198.6 防回滚）")
    ap.add_argument("name", nargs="?", help="要退役的 skill 名称")
    ap.add_argument("--list", action="store_true", help="列出当前黑名单")
    ap.add_argument("--dry-run", action="store_true", help="预览动作，不写盘")
    ap.add_argument("--skip-rebuild", action="store_true", help="跳过重建（仅 git rm + 登记）")
    args = ap.parse_args()

    if args.list:
        return list_blacklist()

    if not args.name:
        print("用法错误: 需要 <skill_name> 或 --list", file=sys.stderr)
        return 2

    # 校验
    ok, reason = validate(args.name, args.dry_run)
    if not ok:
        log("校验", reason, ok=False)
        return 1
    log("校验", f"{args.name}: {reason}")

    if args.dry_run:
        print(f"[DRY-RUN] 将执行: git rm {args.name} → 登记黑名单 → "
              f"{'build_indexes --apply' if not args.skip_rebuild else '跳过重建'} → verify")
        return 0

    # ① git rm
    if not git_rm(args.name):
        return 1

    # ② 从注册表移除（防 build_indexes 守恒 FAIL）
    if not remove_from_registry(args.name):
        return 1

    # ③ 登记黑名单
    if not add_to_blacklist(args.name):
        return 1

    # ④ 重建（可跳过）
    if not args.skip_rebuild and not rebuild_indexes():
        return 1

    # ⑤ verify
    if not run_verify():
        return 1

    mirror_sync()
    print(f"\n✅ 退役完成: {args.name}（git rm + 黑名单 + 重建 + verify 全绿）")
    print("  提示: 收尾请跑 check-skill-mirror.ps1 -Fix 同步镜像端")
    return 0


if __name__ == "__main__":
    sys.exit(main())
