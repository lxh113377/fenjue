#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_summary.py — 生成 CI 运行摘要（item 9 可观测性 step-summary 核心）

聚合来源:
  - ci-results/*.json          各闸门结果（run_gate 产出）
  - pytest-report.xml          pytest junit 报告
  - feedback-summary.json     反馈闭环汇总（ci_feedback 产出）
  - ci-blind-eval.json        盲测集结果（ci_blind_eval 产出，可能缺失）

输出:
  - 写入 $GITHUB_STEP_SUMMARY（GitHub Actions 运行页摘要）
  - 同时落盘 ci-summary.md 作为 artifact

不依赖任何外部服务；缺失文件降级为“跳过”提示，不报错退出。
"""
import glob
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "ci-results")
sys.path.insert(0, os.path.join(REPO_ROOT, "eval"))

from io_utils import load_json as _io_load_json  # noqa: E402  # P1-5: 读写原语唯一实现


def load_json(path):
    """fail-open 形态（历史契约：缺失/损坏返回 None，不报错退出）。"""
    return _io_load_json(path, default=None)


def parse_junit(path):
    if not os.path.exists(path):
        return None
    try:
        root = ET.parse(path).getroot()
        # pytest 新版把根包成 <testsuites>，计数属性在子 <testsuite> 上；兼容两种结构
        suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
        agg = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        for s in suites:
            for k in agg:
                try:
                    agg[k] += int(s.attrib.get(k, 0))
                except (TypeError, ValueError):
                    pass  # 缺失/非数字属性按 0 计（junit 版本差异容错，R207 P2-1 留痕）
        return agg
    except Exception:
        return None


def main() -> int:
    gates = []
    for gf in sorted(glob.glob(os.path.join(RESULTS_DIR, "*.json"))):
        d = load_json(gf)
        if d and "slug" in d:
            gates.append(d)
    junit = parse_junit(os.path.join(REPO_ROOT, "pytest-report.xml"))
    feedback = load_json(os.path.join(REPO_ROOT, "feedback-summary.json"))
    blind = load_json(os.path.join(REPO_ROOT, "ci-blind-eval.json"))

    L = []
    L.append("# 焚诀 CI 运行摘要")
    L.append("")
    L.append("## 闸门结果")
    if gates:
        L.append("| 闸门 | 状态 | 退出码 |")
        L.append("|---|---|---|")
        for g in gates:
            icon = "✅" if g["status"] == "pass" else "❌"
            L.append(f"| {g['slug']} | {icon} {g['status'].upper()} | {g['exit_code']} |")
    else:
        L.append("_无闸门结果（ci-results 未生成）_")
    L.append("")

    L.append("## 单元测试 (pytest)")
    if junit:
        L.append(
            f"- 总计 **{junit['tests']}** | 失败 {junit['failures']} | "
            f"错误 {junit['errors']} | 跳过 {junit['skipped']}"
        )
    else:
        L.append("_未找到 pytest-report.xml_")
    L.append("")

    L.append("## 反馈闭环 (feedback)")
    if feedback:
        L.append(
            f"- 总数 **{feedback['total']}** | open {feedback['open']} | "
            f"closed {feedback['closed']}"
        )
        rec = feedback.get("recovered_pending", 0)
        if rec:
            L.append(f"- 待回收(已恢复未关闭): **{rec}**")
        if feedback.get("open_items"):
            items = ", ".join(
                f"{i['severity']}:{i['id']}" for i in feedback["open_items"][:10]
            )
            L.append(f"- 待处理(open): {items}")
    else:
        L.append("_未找到 feedback-summary.json_")
    L.append("")

    L.append("## 盲测集 (frozen blind)")
    if blind and blind.get("available"):
        flag = "" if blind.get("pass") else " ⚠️ 低于阈值(软门禁，不阻断)"
        L.append(
            f"- Top-1 合理性: **{blind.get('top1_pct', 0):.1f}%** "
            f"(阈值 {blind.get('threshold', 0)}%) | 样本 {blind.get('n', 0)}{flag}"
        )
        if blind.get("bge_status"):
            L.append(f"- BGE 状态: {blind['bge_status']}")
    else:
        L.append("_盲测未运行/环境不可用（跳过，不阻断）_")
    L.append("")

    md = "\n".join(L)
    Path(os.path.join(REPO_ROOT, "ci-summary.md")).write_text(md, encoding="utf-8")

    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with Path(gh).open("a", encoding="utf-8") as f:
            f.write(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
