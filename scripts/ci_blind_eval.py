#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_blind_eval.py — 盲测集门禁（item 11 评测集污染防护 + 基线相对化）

读取 frozen_blind_eval.py --json 的原始输出（ci-blind-eval-raw.json），归一化为
ci-blind-eval.json 供 ci_summary 消费。

判据（2026-09-24 GitHub 对标轮改机制，非调参）：
  原状 = 固定阈值 50%，而实测 Top-1 = 93.1% ⇒ 门禁需跌掉 43pp 才红，**事实上永不失败**；
        同行答案不是"把 50 改成 80"，而是**相对基线判回归**（Codecov `target: auto` +
        `threshold`；promptfoo 把 threshold 做成指标上的具名字段而非空基线文件）。
  现状 = 有效阈值 = max(硬底, 基线 Top-1 − 允许回落)：
        · 基线 = eval/blindset_gate_baseline.json（当场按盲测集版本匹配后读取）
        · 硬底 = --threshold（默认 50%），只拦"路由整个坏掉"级灾难，不是回归门
        · **版本不符 / 基线缺失 ⇒ 直接红并要求重标**（fail-closed）。根因：换题集后
          旧基线不再可比，"改测试集就能漂过门禁"正是本门要堵的路。

允许回落取 1.0pp 的依据（R236 补注③「参数标定前先测两侧边界值」，2026-09-24 实测）：
  同一管线连跑 3 次 Top-1 恒为 93.1%（n=291, bge=engaged）⇒ 管线**确定性**，
  同版本内任何真实回归都会体现为分数变化，故容差可取紧；1.0pp 仅为吸收
  四舍五入与统计口径抖动，不是"容忍退化"。
  ⚠️ 本容差**只在同一 blindset_version 内成立**；轮换题集（eval/rotate_blindset.py --force）
     后必须重标基线，否则会按上面的版本守卫直接红——这是有意的耦合。

退出码: 0 通过 / 2 低于有效阈值或基线不可信（CI 步骤 continue-on-error，标记不阻断）
"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_PATH = os.path.join(REPO_ROOT, "eval", "blindset_gate_baseline.json")
ROTATION_PATH = os.path.join(REPO_ROOT, "eval", "blindset_rotation.json")


def _current_version() -> int:
    """盲测集版本 = rotate_blindset 台账的 active_version（无台账按 0）。"""
    try:
        return int(json.loads(Path(ROTATION_PATH).read_text(encoding="utf-8"))
                   .get("active_version", 0))
    except Exception:  # noqa: BLE001
        return 0


def resolve_gate(raw_pct, raw_n, hard_floor, baseline_path=None):
    """返回 (有效阈值, 判定说明, 基线是否可信)。基线不可用一律按「不可信」处理，禁静默沿用硬底。

    baseline_path 走「调用期解析模块常量」而非默认参固化 —— 默认参在 import 时求值，
    会让测试 monkeypatch(BASELINE_PATH) 静默失效（本项目实测过的同类桩层坑）。
    """
    if baseline_path is None:
        baseline_path = BASELINE_PATH
    try:
        base = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return hard_floor, ("基线不可读（%s）⇒ 本门不可信，需重标: %s"
                            % (e.__class__.__name__, baseline_path)), False
    ver = _current_version()
    if int(base.get("blindset_version", -1)) != ver:
        return hard_floor, ("基线版本 %s != 当前盲测集版本 %d ⇒ 换题集后必须重标基线"
                            "（禁沿用旧基线漂过门禁）"
                            % (base.get("blindset_version"), ver)), False
    if int(base.get("n", 0)) != int(raw_n):
        return hard_floor, ("基线样本数 %s != 本次 %s ⇒ 比对面不一致，需重标"
                            % (base.get("n"), raw_n)), False
    allow = float(base.get("allow_drop_pp", 1.0))
    base_pct = float(base.get("top1_pct", 0.0))
    eff = max(hard_floor, round(base_pct - allow, 2))
    return eff, ("基线相对门: 基线 %.1f%% − 容差 %.1fpp ⇒ 有效阈值 %.2f%%（硬底 %.1f%%）"
                 % (base_pct, allow, eff, hard_floor)), True


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="盲测集门禁（基线相对回归判定）")
    ap.add_argument("--raw-in", default=os.path.join(REPO_ROOT, "ci-blind-eval-raw.json"))
    ap.add_argument("--json-out", default=os.path.join(REPO_ROOT, "ci-blind-eval.json"))
    ap.add_argument("--threshold", type=float, default=50.0,
                    help="硬底（只拦灾难级塌陷，非回归门）；回归门见 blindset_gate_baseline.json")
    args = ap.parse_args()

    try:
        raw = json.loads(Path(args.raw_in).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        raw = None

    out = {
        "available": False,
        "top1_pct": 0.0,
        "n": 0,
        "threshold": args.threshold,
        "gate_mode": "hard-floor",
        "gate_note": "未运行",
        "bge_status": None,
        # pass 在"没跑"时是 null 而非 true —— "跳过不等于通过"（同行明文：
        # A test that skipped did not run. Say so rather than counting it.）
        "pass": None,
    }
    rc = 0
    if isinstance(raw, dict) and raw.get("n"):
        out["available"] = True
        out["top1_pct"] = float(raw.get("score", 0.0))
        out["n"] = int(raw.get("n", 0))
        out["bge_status"] = raw.get("bge_status")
        eff, note, trustworthy = resolve_gate(out["top1_pct"], out["n"], args.threshold)
        out["threshold"] = eff
        out["gate_note"] = note
        out["gate_mode"] = "baseline-relative" if trustworthy else "untrusted-baseline"
        out["pass"] = bool(trustworthy and out["top1_pct"] >= eff)
        rc = 0 if out["pass"] else 2

    Path(args.json_out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if not out["available"]:
        print("[blind] 未运行/环境不可用 -> pass=null（不计为通过），exit 0 不阻断")
        return 0
    status = ("PASS" if out["pass"]
              else ("BELOW-GATE" if out["gate_mode"] == "baseline-relative"
                    else "GATE-UNTRUSTED(基线不可信)"))
    print("[blind] Top-1=%.1f%% 有效阈值=%s%% n=%s bge=%s -> %s | %s" % (
        out["top1_pct"], out["threshold"], out["n"], out["bge_status"], status,
        out["gate_note"]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
