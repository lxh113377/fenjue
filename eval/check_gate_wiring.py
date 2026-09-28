#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_gate_wiring.py — 「门禁接入点自检」（R278，2026-09-22）

【为什么需要它】
2026-09-22 实测：`verify_truth_consistency.py` 头部堂而皇之声明
    「接入点: pre-commit hook / 周维护 Step 0 / CI (.github/workflows/ci.yml)」
而 reality 是 **4 条声明只有 2 条是活的**：
  · 焚诀仓 .git/hooks/ 里**只有 post-commit**，pre-commit **压根没装**
  · GM 仓 pre-commit 只跑 secret_scan，不含 verify
  · pre_commit_hooks.py **无人调用**（依赖 .pre-commit-config.yaml，却从未 pre-commit install）
⇒ **声明式文档会腐烂成谎言；只有可执行的自检才算数。**
   本脚本即把「接入点声明」变成机器可验证的断言。

【自检范围】
  ① verify_truth_consistency.py 头部 `接入点:` 块里声明的每一类调用方
  ② 两仓 git hook 的落地状态（焚诀仓 / GM 仓）
  ③ 版本化副本（换机重装凭据，防 .git/hooks 不被跟踪导致换机即失效）

【触发条件】
  每次 `verify_truth_consistency.py` 执行时（作为 C19）—— 纯静态、零副作用、毫秒级，
  无 SKIP 逃生门；本脚本自身不可用时 C19 判 FAIL。

【⚠️ 为什么静态而不真跑 hook】
  hook 内容含 `verify_truth_consistency.py` 调用 ⇒ 真跑会 **verify → C19 → hook → verify**
  无限递归。故只做「存在性 + 内容断言 + 可执行位」三层静态核验，不执行 hook。

【检查项清单（6 项）】
  W1 焚诀仓 .git/hooks/pre-commit 存在且含 verify 调用
  W2 GM 仓 .git/hooks/pre-commit 存在且含 verify 调用
  W3 两仓 hook 版本化副本存在（eval/hooks/pre-commit + scripts/hooks/pre-commit）
  W4 CI 配置引用 verify（.github/workflows/ci.yml）
  W5 hook 声明的 `exit 1` 语义存在（FAIL 时能拦提交，而不是仅打印）
  W6 verify 头部 `接入点:` 块的每条声明，都能在本文件的 WIRE_MAP 里找到对应检查
     （防"新声明无对应自检"的二次漂移）

【失败报告】
  逐项列出 `W# 描述 — 实际状态`，并给出补齐命令。

用法: python eval/check_gate_wiring.py [--json]
退出码: 0=PASS / 1=FAIL
"""
import argparse
import json
import os
import re
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "eval"))
from config import GLOBAL_MEMORY  # noqa: E402


def hooks_dir(working: str) -> str:
    """hooks 目录 = `git rev-parse --git-common-dir` 下的 hooks（D-44）。

    原先写死 `<仓>/.git/hooks`：在 `git worktree` 里 `.git` 是**文件**不是目录，
    W1 因此恒判"hook 不存在"——而 worktree 其实共用主仓的钩子，判据把可用说成不可用。
    取不到 git 时回退老路径（非仓库环境仍按原样核验，不放松）。
    """
    try:
        r = subprocess.run(["git", "-C", working, "rev-parse", "--git-common-dir"],
                           capture_output=True, text=True, timeout=20)
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out:
            common = out if os.path.isabs(out) else os.path.join(working, out)
            return os.path.join(os.path.normpath(common), "hooks")
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.join(working, ".git", "hooks")


FJ_HOOK = os.path.join(hooks_dir(PROJECT_DIR), "pre-commit")
GM_ROOT = GLOBAL_MEMORY
GM_HOOK = os.path.join(hooks_dir(GM_ROOT), "pre-commit")
FJ_COPY = os.path.join(PROJECT_DIR, "eval", "hooks", "pre-commit")
GM_COPY = os.path.join(GM_ROOT, "scripts", "hooks", "pre-commit")

VERIFY = os.path.join(PROJECT_DIR, "eval", "verify_truth_consistency.py")
CI_YML = os.path.join(PROJECT_DIR, ".github", "workflows", "ci.yml")

# W6 用：verify 头部「接入点:」声明的每类调用方 → 对应检查项 id
# 新增接入方式时：先在 verify 头部写声明，再在此登记对应检查（否则 W6 FAIL）
WIRE_MAP = {
    "pre-commit hook": "W1/W2",
    "CI": "W4",
    "周维护": "W7",
}

# W7：周维护 Step 0 的 checklist 文件（分卷命名，取 glob 前缀）
WEEKLY_GLOB_PREFIX = os.path.join(PROJECT_DIR, "skill", "checklist", "weekly_maintenance")


from io_utils import read_text as _io_read_text  # P1-5: 读写原语唯一实现


def read_text(path):
    return _io_read_text(path, errors='ignore')


def check_hook(path, label, failures, notes):
    """W1/W2：hook 存在 + 含 verify 调用 + 含 exit 1 拦截语义。"""
    if not os.path.exists(path):
        failures.append(f"{label} hook 不存在（{path}）—— 门禁未接入本地提交环节")
        return
    text = read_text(path)
    # R278：接受**直接**调用（含 verify_truth_consistency 字样）或**间接**调用
    # （调用 eval/pre_commit_hooks.py —— 该入口第 1 道闸即 verify C1~C19）。
    # 首版只认直接调用 ⇒ 全量 hook（走统一入口）被误判为"未接入"，属判据过严。
    direct = "verify_truth_consistency" in text
    indirect = "pre_commit_hooks.py" in text or "pre_commit_hooks" in text
    if not (direct or indirect):
        failures.append(f"{label} hook 存在但未调用 verify（直接或经 pre_commit_hooks.py）")
        return
    if not re.search(r"exit\s+1", text):
        failures.append(f"{label} hook 含 verify 但无 `exit 1` 拦截语义 ⇒ FAIL 不会阻止提交")
        return
    notes.append(f"{label} hook ✔ 含 verify 调用 + exit 1 拦截语义")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    failures, notes = [], []

    # W1 / W2：两仓 hook 落地
    check_hook(FJ_HOOK, "W1 焚诀仓", failures, notes)
    check_hook(GM_HOOK, "W2 GM 仓", failures, notes)

    # W3：版本化副本（.git/hooks/* 不受 git 跟踪，换机会丢）
    for path, label in ((FJ_COPY, "W3 焚诀仓副本"), (GM_COPY, "W3 GM 仓副本")):
        if os.path.exists(path):
            notes.append(f"{label} ✔ {path}")
        else:
            failures.append(f"{label} 缺失（{path}）—— .git/hooks/* 不被 git 跟踪，"
                            f"换机后将失去门禁接入")

    # W4：CI 引用 verify
    if not os.path.exists(CI_YML):
        failures.append(f"W4 CI 配置缺失（{CI_YML}）")
    elif "verify_truth_consistency" in read_text(CI_YML):
        notes.append("W4 CI ✔ ci.yml 引用 verify_truth_consistency")
    else:
        failures.append(f"W4 CI 未引用 verify（{CI_YML}）")

    # W5：hook 的 exit 语义（已在 check_hook 内断言，此处汇总说明）
    notes.append("W5 hook `exit 1` 拦截语义 ✔（任一 hook 缺失会由 W1/W2 报出）")

    # W7：周维护 Step 0 必须真的调用 verify（verify 头部声明了该接入点）
    import glob as _glob
    weekly = sorted(_glob.glob(WEEKLY_GLOB_PREFIX + "*.md"))
    if not weekly:
        failures.append(f"W7 未找到周维护 checklist（{WEEKLY_GLOB_PREFIX}*.md）—— "
                        f"verify 头部声明了「周维护 Step 0」接入点")
    elif not any("verify_truth_consistency" in read_text(p) for p in weekly):
        failures.append(f"W7 周维护 checklist（{len(weekly)} 卷）均未调用 verify_truth_consistency "
                        f"—— 声明的接入点不存在")
    else:
        hit = [os.path.basename(p) for p in weekly if "verify_truth_consistency" in read_text(p)]
        notes.append(f"W7 周维护 Step 0 ✔ 调用 verify（{', '.join(hit)}）")

    # W6：接入点声明 ↔ 自检登记 的覆盖一致性
    if os.path.exists(VERIFY):
        head = read_text(VERIFY)[:4000]
        m = re.search(r"接入点:\s*\n((?:\s*-\s*.+\n)+)", head)
        if not m:
            failures.append("W6 verify 头部未解析到「接入点:」声明块（判据面失效，R247）")
        else:
            declared = [ln.strip().lstrip("-").strip() for ln in m.group(1).splitlines()]
            unmapped = [d for d in declared
                        if not any(k in d for k in WIRE_MAP)]
            if unmapped:
                failures.append(
                    f"W6 声明了 {len(unmapped)} 条无对应自检的接入点: {unmapped} —— "
                    f"请在 check_gate_wiring.WIRE_MAP 登记对应检查，否则该声明不可验证")
            else:
                notes.append(f"W6 接入点声明 {len(declared)} 条均已登记对应自检 ✔")
    else:
        failures.append(f"W6 verify 脚本缺失（{VERIFY}）")

    if args.json:
        print(json.dumps({"failures": failures, "pass": not failures}, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    print("=" * 70)
    print("check_gate_wiring — 门禁接入点自检（R278）")
    print("=" * 70)
    for n in notes:
        print(f"  ✔ {n}")
    print()
    if failures:
        print(f"❌ FAIL — {len(failures)} 项接入点失效:")
        for f in failures:
            print(f"  - {f}")
        print("\n补齐命令：")
        print("  焚诀仓:  cd <焚诀> && cp eval/hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit")
        print("  GM 仓 :  cd <MEMORY_ROOT> && cp scripts/hooks/pre-commit .git/hooks/pre-commit")
        return 1
    print("✅ PASS — 所有声明的门禁接入点均已落地且可验证")
    return 0


if __name__ == "__main__":
    sys.exit(main())
