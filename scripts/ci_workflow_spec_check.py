#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_workflow_spec_check.py — 仓库内工作流规范一致性核查（C11/C12 的 CI 可强制子集）

背景:
  verify_truth_consistency.py 的 C11(workflow 规范/版本/四端脚本一致性) 与
  C12(workflow 任务卡字段 == workflow_gate.TASK_CARD_HEADERS) 依赖外部
  <MEMORY_ROOT>\\prompts\\workflow_seven_step.md，CI 中以 --skip-external 运行被 SKIP，
  导致「工作流规范一致性」在 CI 里静默绿、未被真正强制（STATUS.md 标 ✅ 实为本地口径）。

  本脚本对不依赖外部源的规范部分做仓库内强制，使 CI 真正成为强制闸门:
    1. 「本面应当有哪些 CI 作业」读自 `.ci/workflow_jobs.json`（随仓声明的名册），
       逐条核对该 job 是否真在声明的 workflow 文件里定义；名册缺失或为空 ⇒ UNVERIFIED
    2. eval/workflow_gate.py::TASK_CARD_HEADERS 必须非空且 == 规范约定的 11 区任务卡字段
       （C12 契约的仓库内等价判定，无需外部规范文件）

退出码: 0 = PASS / 1 = FAIL（含名册缺失，因为那意味着闸门无依据可判）
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 作业名册来自仓内声明文件，而不是本脚本里的一份硬编常量。
# 改这里的原因（2026-09-29 对标轮实测）：本脚本此前硬编 8 个作业名
# （build/test/prompt-version/feedback/summary/deploy/routing-health/rollback），
# 那是**私有源仓**的 CI 形态；对外子集只有一条 ci.yml，于是一跑就判红、
# 且红因与它想防的事无关（缺的作业本就不属于这个面）。同一族缺陷本轮已在
# eval/check_doc_links.py 上抓到过一次：判据的分母必须由被检对象自己声明。
ROSTER = os.path.join(ROOT, ".ci", "workflow_jobs.json")
# C12 规范任务卡字段（与 eval/workflow_gate.py::TASK_CARD_HEADERS 契约一致，11 区）
EXPECTED_TASK_CARD_HEADERS = [
    "## 本轮目标", "## 验收判据", "## 负面测试用例", "## 备选方案",
    "## 失败预算", "## To-Do", "## Checkpoint 计划", "## 回滚预案",
    "## 目标对齐", "## 新方向", "## 决策记录",
]


def check_ci_jobs() -> bool:
    """名册里每个 (job, file) 都必须在该 workflow 文件里定义，缺一判红。"""
    if not os.path.isfile(ROSTER):
        print(f"[ci-jobs] UNVERIFIED: 作业名册缺失 {os.path.relpath(ROSTER, ROOT)}"
              " —— 名册不在场时本判据看不见任何面，不得记 PASS")
        return False
    with open(ROSTER, encoding="utf-8") as fh:
        roster = json.load(fh)
    required = roster.get("required") or []
    if not required:
        print("[ci-jobs] UNVERIFIED: 名册 required 为空，检查未发生")
        return False
    missing, unreadable = [], []
    for item in required:
        job, rel = item.get("job"), item.get("file")
        if not job or not rel:
            missing.append(f"名册条目缺键: {item}")
            continue
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            unreadable.append(rel)
            missing.append(f"{rel}（文件不在场）")
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if not re.search(rf"^\s{{2}}{re.escape(job)}:\s*$", text, re.M):
            missing.append(f"{rel} :: {job}")
    if missing:
        print(f"[ci-jobs] FAIL: 名册要求 {len(required)} 个作业，缺失/不可读 {len(missing)} 个: {missing}")
        if unreadable:
            print(f"[ci-jobs] 盲区（workflow 文件读不到）: {unreadable}")
        return False
    print(f"[ci-jobs] PASS: 名册 {len(required)} 个作业全部在声明的 workflow 文件里定义"
          f"（面={roster.get('face', '?')}）")
    return True


def check_task_card_headers() -> bool:
    sys.path.insert(0, os.path.join(ROOT, "eval"))
    try:
        import workflow_gate as wg  # noqa: E402
    except Exception as e:  # 导入失败（如 truth_constants 缺失）显式 FAIL
        print(f"[task-card] FAIL: 无法 import eval/workflow_gate: {e}")
        return False
    actual = [h.strip() for h in getattr(wg, "TASK_CARD_HEADERS", [])]
    if not actual:
        print("[task-card] FAIL: TASK_CARD_HEADERS 为空")
        return False
    if sorted(actual) != sorted(EXPECTED_TASK_CARD_HEADERS):
        print("[task-card] FAIL: 任务卡字段与规范契约不一致")
        print(f"  actual({len(actual)})={actual}")
        print(f"  expect({len(EXPECTED_TASK_CARD_HEADERS)})={EXPECTED_TASK_CARD_HEADERS}")
        return False
    print(f"[task-card] PASS: TASK_CARD_HEADERS == 规范 {len(actual)} 区 (C12 仓库内等价)")
    return True


def main() -> int:
    ok = True
    ok &= check_ci_jobs()
    ok &= check_task_card_headers()
    print("workflow-spec check:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
