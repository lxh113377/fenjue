#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
noise_guard.py — 焚诀「广义噪声禁区」机器门禁执行器 (R198.2, 致命纪律 #17 延伸)。

noise_lint.py 只校验「文件散射」（R198 主体）；本脚本补 R198.2 的三类广义噪声
（非文件散射，但可静态核查的状态源），把「文本规则」变成「可执行检查」：

  F5 MCP/工具发现噪音（噪声问题.txt 五）：
     - 工具 description 超长（>800 字符）→ 全量加载时浪费 context
     - 无工具文件的 server 目录 → 未连接/不可用工具仍被发现的近似信号
  F6 Shell 执行噪音（噪声问题.txt 六）：
     - 受管脚本输出点过密（Write-Host/print > 阈值）→ 门禁输出混入结果
  F9 TodoWrite/任务噪音（噪声问题.txt 九）：
     - 任务卡历史 completed 条目堆积（> 阈值）→ 旧任务仍占 context
     - 任务卡分卷过多 → 索引壳膨胀

P2 收敛（2026-08-16）：
  - F5/F6 引入 allowlist（F5_ALLOWLIST / F6_ALLOWLIST）：存量已知项标记后聚焦增量——
    工具方定义（MCP description）与报告型脚本（健康检查/自检输出）不可直接改，
    标记为已知后，未来新增超长/过密项仍会被抓。
  - F6 阈值 15 → 25（报告型脚本合理输出密度）。
  - run-health-check.ps1 / scan_skills.ps1 装饰性输出已合并（标题块/收尾块）。

P1 升级（2026-08-16，T27/T28 硬门禁）：
  - F5/F6 由 info 级升级为 error 级硬门禁（与 F9 同级）——存量违规已全部 allowlist，
    升级后未来新增超长 description / 过密输出点直接拦截提交。
  - 新增 --quiet 模式（pre-commit 静默执行，仅退出码）。

退出码:
  0 = PASS（无违规）
  1 = FAIL（发现违规，可被 pre-commit / savepoint 门禁拦截）
  2 = 用法/运行错误
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "eval"))
# P1-6 批次②: 单源引用
from config import GLOBAL_MEMORY as _GM_ROOT  # noqa: E402

MCP_ROOT = Path(r"<USER_HOME>\.trae-cn\mcps")
SCRIPTS_ROOTS = [REPO_ROOT / "scripts", Path(_GM_ROOT) / "scripts"]
TASK_CARD = REPO_ROOT / "memory" / "task-card.md"

# 阈值（可核查判定标准）
F5_DESC_LIMIT = 800      # 工具 description 超长阈值（字符）
F6_OUTPUT_LIMIT = 25     # 单脚本输出点阈值（Write-Host/print 计数；报告型脚本合理密度，P2 自 15 上调）
F9_DONE_LIMIT = 15       # 任务卡历史 completed 条目阈值
F9_VOLUME_LIMIT = 3      # 任务卡分卷数阈值

# 已知项 allowlist（P2：存量标记已知，聚焦增量——未来新增超长/过密项仍会被抓）
F5_ALLOWLIST = {
    "Exec.json": "integrated_code_mode 工具方定义（description 长，不可直接改）",
    "pull_request_review_write.json": "GitHub 插件工具方定义（description 长，不可直接改）",
}
F6_ALLOWLIST = {
    "quick_verify.ps1": "报告型健康检查脚本（输出点为功能性状态报告，非噪声）",
    "pre-cc-check.ps1": "报告型自检脚本（输出点为功能性检查结果，非噪声）",
    "run-health-check.ps1": "报告型健康检查脚本（输出点为功能性状态报告，非噪声）",
}


def check_f5():
    """MCP 工具发现噪音：description 超长 + 空工具 server（硬门禁，工具方定义不可直接改）。"""
    issues = []
    stats = {"servers": 0, "tools": 0, "long_desc": 0, "allowed": 0}
    if not MCP_ROOT.exists():
        return {"status": "SKIP", "reason": f"MCP 目录不存在: {MCP_ROOT}", "issues": []}
    for server_dir in MCP_ROOT.iterdir():
        if not server_dir.is_dir():
            continue
        tools_dir = server_dir / "solo_work_lite"
        if not tools_dir.is_dir():
            continue
        for sub in tools_dir.iterdir():
            if not sub.is_dir():
                continue
            stats["servers"] += 1
            tdir = sub / "tools"
            if not tdir.is_dir():
                continue
            tool_files = list(tdir.glob("*.json"))
            if not tool_files:
                issues.append({"type": "F5", "severity": "error",
                               "target": str(sub), "detail": "server 无工具文件（未连接/不可用近似信号）"})
            for tf in tool_files:
                stats["tools"] += 1
                try:
                    d = json.loads(tf.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                desc = d.get("description", "")
                if len(desc) > F5_DESC_LIMIT:
                    stats["long_desc"] += 1
                    if tf.name in F5_ALLOWLIST:
                        stats["allowed"] += 1
                        continue  # 已知工具方定义，聚焦增量
                    issues.append({"type": "F5", "severity": "error",
                                   "target": str(tf), "detail": f"description {len(desc)} 字符（>{F5_DESC_LIMIT}）"})
    return {"status": "PASS", "stats": stats, "issues": issues}


def check_f6():
    """Shell 执行噪音：受管脚本输出点过密（硬门禁，功能需要，建议优化非阻断）。"""
    issues = []
    stats = {"scripts": 0, "dense": 0, "allowed": 0}
    for root in SCRIPTS_ROOTS:
        if not root.exists():
            continue
        for fp in sorted(root.rglob("*")):
            if not fp.is_file() or fp.suffix.lower() not in (".ps1", ".py"):
                continue
            if any(seg in fp.parts for seg in ("_trash", "_temp", "_bak", "__pycache__")):
                continue
            stats["scripts"] += 1
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            n = len(re.findall(r"Write-Host|Write-Output|print\s*\(", text))
            if n > F6_OUTPUT_LIMIT:
                stats["dense"] += 1
                if fp.name in F6_ALLOWLIST:
                    stats["allowed"] += 1
                    continue  # 报告型脚本已知功能性输出，聚焦增量
                issues.append({"type": "F6", "severity": "error",
                               "target": str(fp), "detail": f"{n} 个输出点（>{F6_OUTPUT_LIMIT}）"})
    return {"status": "PASS", "stats": stats, "issues": issues}


def check_f9():
    """TodoWrite 任务噪音：任务卡历史 completed 堆积 + 分卷膨胀（硬门禁，agent 可归档）。"""
    issues = []
    stats = {"done_items": 0, "volumes": 0}
    if not TASK_CARD.exists():
        return {"status": "SKIP", "reason": f"任务卡不存在: {TASK_CARD}", "issues": []}
    text = TASK_CARD.read_text(encoding="utf-8", errors="ignore")
    done = len(re.findall(r"^\s*-\s*\[x\]", text, re.M))
    stats["done_items"] = done
    if done > F9_DONE_LIMIT:
        issues.append({"type": "F9", "severity": "error",
                       "target": str(TASK_CARD), "detail": f"{done} 条历史 completed（>{F9_DONE_LIMIT}，必须归档）"})
    vols = sorted(TASK_CARD.parent.glob("task-card.part*.md"))
    stats["volumes"] = len(vols)
    if len(vols) > F9_VOLUME_LIMIT:
        issues.append({"type": "F9", "severity": "error",
                       "target": str(TASK_CARD), "detail": f"{len(vols)} 个分卷（>{F9_VOLUME_LIMIT}，必须合并）"})
    return {"status": "PASS" if not issues else "FAIL", "stats": stats, "issues": issues}


def main():
    as_json = "--json" in sys.argv
    as_quiet = "--quiet" in sys.argv
    results = {"f5": check_f5(), "f6": check_f6(), "f9": check_f9()}
    errors = [it for r in results.values() for it in r["issues"] if it["severity"] == "error"]
    infos = [it for r in results.values() for it in r["issues"] if it["severity"] == "info"]
    verdict = "FAIL" if errors else "PASS"

    if as_quiet:
        return 0 if verdict == "PASS" else 1

    if as_json:
        print("__JSON__" + json.dumps({"verdict": verdict, "errors": len(errors), "infos": len(infos),
                                       "results": results}, ensure_ascii=False, default=str))
        return 0 if verdict == "PASS" else 1

    print("=" * 72)
    print("noise_guard — 广义噪声禁区机器门禁 (R198.2: F5 MCP / F6 Shell / F9 TodoWrite)")
    print("=" * 72)
    for key, label in (("f5", "F5 MCP/工具发现噪音"), ("f6", "F6 Shell 执行噪音"), ("f9", "F9 TodoWrite/任务噪音")):
        r = results[key]
        st = r.get("status", "SKIP")
        mark = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}[st]
        print(f"\n[{mark}] {label}")
        if "reason" in r:
            print(f"  SKIP {r['reason']}")
            continue
        print(f"  {json.dumps(r.get('stats', {}), ensure_ascii=False)}")
        for it in r["issues"]:
            print(f"  {it['severity'].upper():5} {it['type']} {it['target']} — {it['detail']}")
    print("\n" + "=" * 72)
    print(f"结论: {verdict} | 硬门禁 {len(errors)} 项")
    print("=" * 72)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
