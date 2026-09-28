#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_workflow_spec_check.py — 仓库内工作流规范一致性核查（C11/C12 的 CI 可强制子集）

背景:
  verify_truth_consistency.py 的 C11(workflow 规范/版本/四端脚本一致性) 与
  C12(workflow 任务卡字段 == workflow_gate.TASK_CARD_HEADERS) 依赖外部
  <MEMORY_ROOT>\\prompts\\workflow_seven_step.md，CI 中以 --skip-external 运行被 SKIP，
  导致「工作流规范一致性」在 CI 里静默绿、未被真正强制（STATUS.md 标 ✅ 实为本地口径）。

  本脚本对不依赖外部源的规范部分做仓库内强制，使 CI 真正成为强制闸门:
    1. .github/workflows/ci.yml 必须定义 8 个核心作业
       (build/test/prompt-version/feedback/summary/deploy/routing-health/rollback)
    2. eval/workflow_gate.py::TASK_CARD_HEADERS 必须非空且 == 规范约定的 11 区任务卡字段
       （C12 契约的仓库内等价判定，无需外部规范文件）

退出码: 0 = PASS / 1 = FAIL
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CI_YML = os.path.join(ROOT, ".github", "workflows", "ci.yml")
EXPECTED_JOBS = [
    "build", "test", "prompt-version", "feedback", "summary",
    "deploy", "routing-health", "rollback",
]
# C12 规范任务卡字段（与 eval/workflow_gate.py::TASK_CARD_HEADERS 契约一致，11 区）
EXPECTED_TASK_CARD_HEADERS = [
    "## 本轮目标", "## 验收判据", "## 负面测试用例", "## 备选方案",
    "## 失败预算", "## To-Do", "## Checkpoint 计划", "## 回滚预案",
    "## 目标对齐", "## 新方向", "## 决策记录",
]


def check_ci_jobs() -> bool:
    if not os.path.isfile(CI_YML):
        print(f"[ci-jobs] FAIL: 找不到 {os.path.relpath(CI_YML, ROOT)}")
        return False
    with open(CI_YML, encoding="utf-8") as fh:
        text = fh.read()
    missing = [
        j for j in EXPECTED_JOBS
        if not re.search(rf"^\s{{2}}{re.escape(j)}:\s*$", text, re.M)
    ]
    if missing:
        print(f"[ci-jobs] FAIL: ci.yml 缺失作业: {missing}")
        return False
    print(f"[ci-jobs] PASS: ci.yml 含全部 {len(EXPECTED_JOBS)} 个核心作业")
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
