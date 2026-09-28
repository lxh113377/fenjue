#!/usr/bin/env python3
"""从 eval/ 生成 publish/skill-hitrate-toolkit/eval/ 发布副本（阶段1 批次5）。

用法:
  python scripts/build_publish.py            # 构建：缺失副本补齐；漂移副本打印清单后拒绝（需 --force）
  python scripts/build_publish.py --force    # 构建：连同漂移副本一并覆盖
  python scripts/build_publish.py --check    # 校验：源与副本 diff；漂移则打印清单并以非 0 退出
  python scripts/build_publish.py --dry-run  # 预览：打印将执行的动作，不写盘

fail-closed：任何源文件缺失即中止；--check 发现漂移即判非 0；无 --force 不覆盖漂移副本。

R212（2026-09-05）语义修订：
  - KNOWN_DIVERGED 记录的 3 个文件为人决策认可的**刻意算法分叉**
    （R210 用户终裁「维持现状+文档化」，转 public 前统一，07 记录 04ea343）——
    不再因「现状漂移」判 FAIL / 需 --force，构建时也跳过覆盖（保护分叉）；
  - 新增孤儿副本硬检：publish 副本目录中**不在 SOURCES 清单的 .py**
    （残留/漏登记反向证据）→ --check 判非 0、构建时打印提示 → 杜绝
    「本地看得见、发布副本没有/多出」的静默漂移。
"""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "eval"
PUBLISH_EVAL_DIR = REPO_ROOT / "publish" / "skill-hitrate-toolkit" / "eval"

# R212: 人决策认可的刻意算法分叉（R210 04ea343「维持现状+文档化」）。
# 转 public 发布前必须做算法统一+路径清洗，届时从本集合移除并重新贴合。
KNOWN_DIVERGED = {"eval_dual_tree.py", "skill_hitrate_eval_v2.py", "tfidf_router.py"}

# 显式清单：eval/ 源 -> publish 副本（按实际存在配对，新增文件必须在此登记）
# R207 P1-14: 运行时依赖文件（index_integrity/config/truth_constants+json）一并注入，
# 使发布副本可独立 import 运行（此前 fork 缺依赖 → 独立运行 ImportError）。
SOURCES: tuple[tuple[str, str], ...] = (
    # 发布工具本体（4）—— build_skill_vectors 已退役删除（2026-09-23，R193 弃始+观察期满）
    ("eval_dual_tree.py", "eval_dual_tree.py"),
    ("skill_hitrate_eval_v2.py", "skill_hitrate_eval_v2.py"),
    ("tfidf_router.py", "tfidf_router.py"),
    ("tune_threshold.py", "tune_threshold.py"),
    # 运行时依赖闭包（5）：fork 脚本 import index_integrity/config；config→truth_constants→.json；
    # eval_dual_tree/tune_threshold 模块加载期读同目录 test_queries.json
    ("index_integrity.py", "index_integrity.py"),
    ("config.py", "config.py"),
    ("truth_constants.py", "truth_constants.py"),
    ("truth_constants.json", "truth_constants.json"),
    ("test_queries.json", "test_queries.json"),
)


def _pairs() -> list[tuple[Path, Path]]:
    return [(EVAL_DIR / src, PUBLISH_EVAL_DIR / dst) for src, dst in SOURCES]


def _orphans() -> list[Path]:
    """publish 副本目录中不在 SOURCES 清单的 .py（残留/漏登记反向证据）。"""
    if not PUBLISH_EVAL_DIR.is_dir():
        return []
    managed = {dst for _, dst in SOURCES}
    return sorted(p for p in PUBLISH_EVAL_DIR.glob("*.py") if p.name not in managed)


def _report() -> list[tuple[str, Path, Path]]:
    """返回 [(状态, 源, 副本)]，状态 ∈ {一致, 缺失, 漂移, 分叉}；源缺失 fail-closed 中止。

    分叉 = KNOWN_DIVERGED 记录的刻意算法分叉（人决策认可，不算违规，构建时跳过）。"""
    report: list[tuple[str, Path, Path]] = []
    for src, dst in _pairs():
        if not src.is_file():
            print(f"[ERROR] 源文件缺失: {src.relative_to(REPO_ROOT)}")
            raise SystemExit(1)
        if not dst.is_file():
            report.append(("缺失", src, dst))
        elif not filecmp.cmp(src, dst, shallow=False):
            st = "分叉" if dst.name in KNOWN_DIVERGED else "漂移"
            report.append((st, src, dst))
        else:
            report.append(("一致", src, dst))
    return report


def _rel(p: Path) -> str:
    """相对 REPO_ROOT 的展示路径（tmp/外部目录场景经 os.path.relpath 兜底，不抛异常）。"""
    try:
        return p.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return os.path.relpath(p, str(REPO_ROOT))


def _print_state(state: str, src: Path, dst: Path) -> None:
    print(f"  [{state}] {_rel(dst)} <- {_rel(src)}")


def cmd_check() -> int:
    report = _report()
    dirty = [item for item in report if item[0] not in ("一致", "分叉")]
    orphans = _orphans()
    if orphans:
        print("孤儿副本（发布目录中不在 SOURCES 清单的 .py，请登记或清理）:")
        for p in orphans:
            print(f"  [孤儿] {_rel(p)}")
    if dirty:
        print("publish 副本与 eval 源不一致:")
        for state, src, dst in dirty:
            _print_state(state, src, dst)
    if dirty or orphans:
        return 1
    print(f"OK: publish 副本与 eval 源全部一致（{len(SOURCES)} 个文件，"
          f"{len(KNOWN_DIVERGED)} 个已知分叉豁免）")
    return 0


def cmd_build(force: bool, dry_run: bool) -> int:
    report = _report()
    # 契约（docstring）：缺失副本自动补齐；【未豁免漂移】副本 fail-closed 拒绝，需 --force。
    # 已知分叉（KNOWN_DIVERGED）刻意跳过——不覆盖、不报错（保护人决策认可的分叉现状）。
    drifted = [item for item in report if item[0] == "漂移"]
    orphans = _orphans()
    if drifted and not force and not dry_run:
        print("发现漂移副本，需 --force 覆盖（fail-closed，不静默覆盖）:")
        for state, src, dst in drifted:
            _print_state(state, src, dst)
        return 1
    for state, src, dst in report:
        if state in ("一致", "分叉"):
            if dry_run:
                print(f"  [跳过] {_rel(dst)} 已一致"
                      + ("（已知分叉）" if state == "分叉" else ""))
            continue
        # 缺失副本按契约自动补齐；漂移副本（已通过上方 --force 门禁）覆盖
        action = "复制" if state == "缺失" else "覆盖"
        if dry_run:
            print(f"  [预览:{action}] {_rel(dst)} <- {_rel(src)}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        print(f"  [{action}] {_rel(dst)}")
    if orphans:
        print(f"提示: {len(orphans)} 个孤儿副本未在 SOURCES 清单（{', '.join(p.name for p in orphans)}）"
              "——请登记或清理，--check 将据此判 FAIL")
    if dry_run:
        print("dry-run：未写入任何文件")
    else:
        print("构建完成")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="生成 publish/skill-hitrate-toolkit/eval/ 发布副本"
    )
    parser.add_argument("--check", action="store_true", help="仅校验源与副本 diff，漂移返回非 0")
    parser.add_argument("--dry-run", action="store_true", help="预览将要执行的动作，不写盘")
    parser.add_argument("--force", action="store_true", help="构建时覆盖漂移副本（默认拒绝）")
    args = parser.parse_args()
    if args.check:
        return cmd_check()
    return cmd_build(force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
