#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
noise_lint.py — 焚诀「生成文件存放规范」机器校验器 (R198, 致命纪律 #17) — 仓库内可移植版。

与用户级技能 A-project-handoff/scripts/noise_lint.py 同源分类逻辑，但针对 CI / 多机可移植做了改造：
  * 默认扫描「仓库根目录」（由 __file__ 推导，无需硬编码用户路径），
    因此在本机、CI(ubuntu-latest)、任意机器均可运行 → 规范真正被强制。
  * 仍接受显式路径参数（可追加扫描 D:\\global_* 等受管根；不存在则 SKIP，不误阻 CI）。
  * 分类规则、allowlist、退出码与原版一致。
  * P1-10 回灌技能侧 d88b5ee R280 三口径（一级豁免传递/子项自判/跨根去重），
    全部经 is_reparse_dir 三重回退实现，CI/非 Windows 下行为不变。

退出码:
  0 = 零散射（PASS，无违规）
  1 = 发现违规（FAIL，可被 pre-commit / CI 门禁拦截）
  2 = 用法/运行错误
"""
import os
import re
import sys
import json
import subprocess

# 仓库根目录 = scripts/ 的上级，CI 中即为 checkout 出的仓库，始终存在（可移植关键）
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 指定回收/临时区（名称命中即 quarantine，不计入违规）
QUARANTINE_ZONES = re.compile(
    r"(^|/)(_trash|_temp|_bak|_fenjue_backups|\.cleanup|_archive|_my-skills)(/|$)"
)

# 散落文件名特征：临时/备份/迁移/中间产物（命中即违规候选）
# tmp(?!l) 避免误匹配合法模板文件 *.tmpl
STRAY_NAME = re.compile(
    r"(_old|_copy|_backup|_deprecated|_bak|\.bak|_tmp|_new\d*|_final|tmp(?!l)[\w\-]*|\.log)"
    r"([-_]?[\d][\d\-_.]*)?$",
    re.I,
)

# 分卷文件命名约定：name.partN.md 或嵌套扁平化 name.partN-M.md（R2 命名收敛，
# 焚诀有意设计，允许在根部）
SPLIT_VOLUME = re.compile(r"^\.?[\w\-.]+\.part\d+(-\d+)*\.md$")

# 平台迁移/注册表产物特征（应被 .gitignore 覆盖，否则视为违规）
MIGRATION_NAME = re.compile(
    r"(_migration|migration_|_skillid_migration|\.disable_to_model|bm_skillid|_merge_log|_temp_list)",
    re.I,
)

# D-43：这些一级目录的子项**不进**二级散落检测——它们是 VCS 机制件而非工作区表面。
# 一级扫描早就把 .git 放进 PROJECT_CORE，二级却漏了对应豁免，于是 .git/hooks/*、
# .git/push-failure.log 这类设计内本机件被判成"散落产物"，把提交整条链拦死。
# 名单刻意保持最小：只豁免 VCS 内部目录，不放行任何工作区目录。
NON_WORKSPACE_DIRS = {".git"}

# 焚诀项目根部 allowlist（strict 模式：未登记即违规，体现「强制」——
# 防 agent 随手在项目根造目录/文件）
PROJECT_CORE = {
    "dirs": {
        # 基础设施
        ".git", ".github", ".workbuddy",
        # 跨项目 CI 全绿契约（对标轮十八追加轮）：`.ci/contract.json` 是被 git 跟踪的
        # 信任边界（未入库的契约拒绝执行），运行时日志在 `.ci/logs/` 已被 .gitignore 覆盖。
        # 与 .github 同级：都是"声明 CI 怎么跑"的位置，只是本仓的远端被账号额度卡住，
        # 检查面挪到本地 pre-push 承担（见 eval/hooks/pre-push）。
        ".ci",
        # TraeCode 平台目录（plan/文档产物 .trae/documents）
        ".trae",
        # 工具缓存（再生品，通常已被 .gitignore 覆盖）
        ".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        # 项目核心
        "archive", "audit", "deliverables", "documents", "eval", "feedback",
        "others", "publish", "reports", "scripts", "skill", "skill_tree",
        # junction / 符号链接（设计内，指向 <MEMORY_ROOT>）
        "memory", "memory_content", "prompts",
    },
    "files": {
        # 忽略/门禁配置
        ".agentignore", ".aiexclude", ".coveragerc", ".gitattributes", ".gitignore",
        ".rgignore", ".pre-commit-config.yaml", "requirements-ci.txt",
        # R208 O-7/O-8: 工具链配置（pytest/mypy/ruff 已并入 pyproject 单一源；mypy.ini/pytest.ini 已废弃）
        "pyproject.toml",
        # 指令/状态索引壳
        "AGENTS.md", "README.md", "STATUS.md", "index.md",
        "NOISE_PREVENTION.md", ".hermes.md",
        # 根部社区件（对标轮六 7-J）：许可/漏洞报告/参与方式，GitHub 一等公民位
        "LICENSE.md", "SECURITY.md", "CONTRIBUTING.md",
        # 对标轮十八 D-114：发布面（可引用的版本账）。与上面三件同级——
        # GitHub 一等公民位；证据是 obra/superpowers 也在根目录放 RELEASE-NOTES.md，
        # 而本仓的版本账此前只在 GM 的 VERSION_LOCK.md（2026-09-21 那次清空真丢过分卷）。
        "RELEASE-NOTES.md",
        # 根部交付物（历史遗留；建议后续归入 publish/，暂不判违规以免破坏在用产物）
        "workflow-completeness-assessment.html",
    },
    "file_patterns_allowed": [SPLIT_VOLUME],
}


def git_ignored(root, name):
    """用仓库 .gitignore 判定该根部子项是否已被忽略。非 git 仓库返回 False。"""
    try:
        r = subprocess.run(
            ["git", "-C", root, "check-ignore", "-q", name],
            capture_output=True, text=True, timeout=30,  # P1-6
        )
        return r.returncode == 0
    except Exception:
        return False


def git_ignored_many(root, names):
    """批量 .gitignore 判定：单次 `git check-ignore --stdin -z` 进程替代逐项 spawn
    （pre-commit 每次提交对 ~40 个根部子项各起一个 git 进程 → 收敛为 1 个）。
    返回被忽略名称集合；非 git 仓库 / git 出错返回空集（调用方回退逐项判定）。"""
    if not names:
        return set()
    try:
        r = subprocess.run(
            ["git", "-C", root, "check-ignore", "--stdin", "-z"],
            input="\0".join(names) + "\0",
            capture_output=True, text=True, timeout=30,  # P1-6
        )
        if r.returncode not in (0, 1):  # 0=有命中, 1=无命中, 其它=出错
            return set()
        return {p for p in (r.stdout or "").split("\0") if p}
    except Exception:
        return set()


_QUARANTINE_DIRNAMES = (
    "_trash", "_temp", "_bak", "_fenjue_backups", ".cleanup", "_archive", "_my-skills"
)


def is_reparse_dir(path):
    """判断是否为 junction / 符号链接（reparse point），跨平台 fail-safe。

    同源回灌（技能侧 d88b5ee 跨根去重，P1-10）：同一物理目录经 junction
    被扫成两个根时，跳过链接侧的二级扫描，避免把目标根的内容判成散落。
    兼容性：os.path.isjunction（3.12+）→ os.path.islink（对 junction 亦 True）
    → lstat().st_reparse_tag 三重回退；异常一律按「非 reparse」处理。
    非 Windows/CI 上恒返回 False，行为不变（可移植）。
    """
    try:
        isjunction = getattr(os.path, "isjunction", None)
        if isjunction is not None and isjunction(path):
            return True
        if os.path.islink(path):
            return True
        return getattr(os.lstat(path), "st_reparse_tag", 0) != 0
    except Exception:
        return False


def classify_strict(root, child, cfg, ignored=None):
    """strict 分类：未在 allowlist / 分卷正则 / gitignore 内的根部项即违规。"""
    name = os.path.basename(child)
    is_dir = os.path.isdir(child)

    # 1) 指定回收/临时区
    if QUARANTINE_ZONES.search("/" + name + "/") or name in (
        "_trash", "_temp", "_bak", "_fenjue_backups", ".cleanup", "_archive", "_my-skills"
    ):
        return "quarantine", "指定回收/临时区（设计内）"

    # 2) 被 .gitignore 命中（批量结果优先；未提供时回退单次调用）
    if name in ignored if ignored is not None else git_ignored(root, name):
        return "quarantine", "被 .gitignore 命中（不入库）"

    # 3) 核心 allowlist
    if is_dir and name in cfg.get("dirs", set()):
        return "ok", "已知核心目录"
    if not is_dir and name in cfg.get("files", set()):
        return "ok", "已知核心文件"
    for pat in cfg.get("file_patterns_allowed", []):
        if not is_dir and pat.match(name):
            return "ok", "分卷文件（name.partN.md，设计内）"

    # 4) 散落特征
    if STRAY_NAME.search(name) or MIGRATION_NAME.search(name):
        return "violation", "根部散落：临时/备份/迁移产物"

    return "violation", "根部意外项（不在核心 allowlist）"


def scan_root(root, cfg, quiet=False):
    root = os.path.normpath(root)
    results = {"root": root, "exists": os.path.isdir(root),
               "children": [], "violation": [], "quarantine": [], "ok": []}
    if not results["exists"]:
        if not quiet:
            print(f"[SKIP] 目录不存在：{root}")
        return results

    root_children = sorted(os.listdir(root))
    ignored = git_ignored_many(root, root_children)
    for name in root_children:
        child = os.path.join(root, name)
        status, reason = classify_strict(root, child, cfg, ignored=ignored)
        entry = {"name": name, "type": "dir" if os.path.isdir(child) else "file",
                 "status": status, "reason": reason,
                 "relocate_to": os.path.join(root, "_trash", name) if status == "violation" else None}
        results["children"].append(entry)
        results[status].append(entry)
        if not quiet:
            mark = {"ok": "  OK ", "quarantine": "  ~~ ", "violation": "VIOL"}[status]
            print(f"  {mark} {entry['type']:4} {name:<42} {reason}")

    # 二级扫描：对根下所有直接子目录做 depth=2 散落检测（盲区修补，
    # 防 memory/、eval/ 等核心子目录内的备份残留 *.bak 逃逸检测）。
    # R280 三口径（同源回灌技能侧 d88b5ee，P1-10）：
    #   ① 一级已豁免（指定回收区 / .gitignore 命中）的顶层项不再深扫；
    #   ② 二级子项自身命中回收区名即跳过（如 memory_content/_bak）；
    #   ③ 顶层项是 junction/符号链接 → 跳过其二级扫描（跨根去重）。
    #   ④ D-43：git 内部目录不是工作区表面（见模块级 NON_WORKSPACE_DIRS 注释）。
    status_by_name = {e["name"]: e["status"] for e in results["children"]}
    for name in sorted(os.listdir(root)):
        child = os.path.normpath(os.path.join(root, name))
        if not os.path.isdir(child):
            continue
        if name in NON_WORKSPACE_DIRS:
            continue
        if QUARANTINE_ZONES.search("/" + name + "/") or name in _QUARANTINE_DIRNAMES:
            continue
        if status_by_name.get(name) == "quarantine":
            continue
        if is_reparse_dir(child):
            continue
        try:
            sub_names = sorted(os.listdir(child))
        except Exception:
            continue
        for sname in sub_names:
            schild = os.path.normpath(os.path.join(child, sname))
            if QUARANTINE_ZONES.search("/" + sname + "/") or sname in _QUARANTINE_DIRNAMES:
                continue
            if STRAY_NAME.search(sname) or MIGRATION_NAME.search(sname):
                rel = f"{name}/{sname}"
                entry = {
                    "name": rel,
                    "type": "dir" if os.path.isdir(schild) else "file",
                    "status": "violation",
                    "reason": "子目录内部散落：临时/备份/迁移产物（二级扫描，盲区修补）",
                    "relocate_to": os.path.join(root, "_trash", f"{name}_{sname}"),
                }
                results["children"].append(entry)
                results["violation"].append(entry)
                if not quiet:
                    print(f"  VIOL {entry['type']:4} {rel:<48} {entry['reason']}")
    return results


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    quiet = "--quiet" in args
    paths = [a for a in args if not a.startswith("--")]

    # 默认仅扫仓库根（可移植、CI 必存在）；显式传参则改用传入路径
    roots = [os.path.normpath(p) for p in paths] if paths else [REPO_ROOT]
    cfg = PROJECT_CORE

    print("=" * 72)
    print("noise_lint — 焚诀生成文件存放规范校验 (致命纪律 #17, 仓库内可移植版)")
    print("=" * 72)

    all_results = []
    total_violations = 0
    for root in roots:
        print(f"\n# 扫描根目录：{root}")
        res = scan_root(root, cfg, quiet=quiet)
        all_results.append(res)
        total_violations += len(res["violation"])

    print("\n" + "=" * 72)
    summary = {os.path.basename(r["root"]): {"ok": len(r["ok"]),
                                              "quarantine": len(r["quarantine"]),
                                              "violation": len(r["violation"])}
               for r in all_results}
    print("汇总：", json.dumps(summary, ensure_ascii=False))
    if total_violations == 0:
        print("[GATE:noise-pass]")  # R216e 门禁标记——协议单一真相源 = rule_editor.py GATE_REGISTRY（改字面量必须同步该常量 + contract.md 协议表）
        print("PASS 零散射：受管根目录无违规散落文件。")
        verdict = "PASS"
    else:
        print("[GATE:noise-fail]")  # R216e 门禁标记——协议单一真相源 = rule_editor.py GATE_REGISTRY（改字面量必须同步该常量 + contract.md 协议表）
        print(f"FAIL 发现 {total_violations} 个违规散落项 → 必须迁往对应 _trash，禁止删除。")
        verdict = "FAIL"
        for r in all_results:
            for v in r["violation"]:
                print(f"   VIOL {r['root']}\\{v['name']}  ->  {v['relocate_to']}")

    if as_json:
        print("\n__JSON__" + json.dumps({"verdict": verdict,
                                         "total_violations": total_violations,
                                         "roots": all_results}, ensure_ascii=False, default=str))

    print("=" * 72)
    return 0 if total_violations == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
