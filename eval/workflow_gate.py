#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workflow_gate.py — 焚诀七步闭环跨平台工作流门禁（R195）
=====================================================================
共享逻辑单一真相源；四端 scripts/wf_*.ps1 均为薄包装（固定平台参数 +
Python 解析优先级 + 透传退出码），逻辑零重复。

子命令:
  --check <stage> --platform <端>   stage = boot | task-card | pre-savepoint | adversarial
  --bootstrap --platform <端>       输出应实跑清单（注入 ≠ 实跑）
  --status --platform <端>          读会话进度（memory/sessions/fenjue-workflow.json）
  --next --platform <端>            收尾推荐下一步模板（≤3 条 + 反馈入口）
  --task-card                       打印任务卡模板（字段与 task-card 门禁一致）
  --record <step> <state> [reason] --platform <端>   写会话进度步骤状态

退出码: 0 = PASS / 1 = FAIL（拒绝）/ 2 = 用法错误
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)

sys.path.insert(0, EVAL_DIR)
from truth_constants import ENDPOINTS, WORKFLOW_VERSION  # noqa: E402

PROGRESS_REL = os.path.join("memory", "sessions", "fenjue-workflow.json")
TASK_CARD_REL = os.path.join("memory", "task-card.md")
P1_REL = os.path.join("memory", "AGENTS.md")
NEXT_STEPS_REL = os.path.join("memory", "07-next-steps.md")
COMMON_SKILLS_REL = os.path.join("memory", "常用技能.md")
GOAL_REL = os.path.join("memory", "01-goal.md")
ADV_TEST_REL = os.path.join("eval", "adversarial_test.py")

TASK_CARD_HEADERS = [
    "## 本轮目标",
    "## 验收判据",
    "## 负面测试用例",
    "## 备选方案",
    "## 失败预算",
    "## To-Do",
    "## Checkpoint 计划",
    "## 回滚预案",
    "## 目标对齐",
    "## 新方向",
    "## 决策记录",
]

# ── GATE_MSG_STYLE：校验失败提示编写规范（R199 固化，2026-08-16）───────────
# 原则：门禁校验的失败提示 = 「缺什么」+「允许格式」+「示例」+「常见错误」四要素
# 齐备，让使用者一眼看出错在哪、怎么改——禁止「只说缺什么、不说允许格式」。
# 背景教训（2026-08-16 实测）：回滚预案「git -C D:\... revert」不匹配正则却只报
# 「缺具体 git 命令」，导致 3 轮排查返工；自解释化后（允许格式 + git -C 警示）
# 一眼可改。本规范防未来新增校验项重蹈覆辙。
#
# 模板（每条 missing 提示按此结构撰写）：
#   "{缺什么}——允许格式：{允许值/结构}，如「{示例}」；常见错误：{易错写法}"
#
# 历史参照（已自解释化）：
#   - 回滚预案缺命令：允许格式 = git tag/restore/checkout/revert/reset/branch 开头
#     + 示例 + 禁止 git -C 前缀/纯文字/手动 checkout
#   - 决策主体：允许值 = 人|模型|规则（正则已按值域校验）
#   - 失败预算：允许格式 = 含数字的「最大回滚次数：N 次」
STEPS = [str(i) for i in range(1, 8)]

# 四要素关键词（audit_gate_msg_style 审查：missing.append 提示至少含其一）
GATE_MSG_STYLE_KEYWORDS = ("允许格式", "常见错误", "示例", "禁止")

INPUT_PROCESSING_KEYWORDS = (
    "输入", "参数", "解析", "上传", "表单", "用户输入",
    "query", "prompt", "请求", "字符串",
)


def audit_gate_msg_style() -> list[str]:
    """GATE_MSG_STYLE 遵守审查（R199）：扫描 task_card_ok 全部 missing.append 提示，
    断言每条含四要素关键词（允许格式/常见错误/示例/禁止 至少其一）。

    防未来新增校验项重蹈「只说缺什么、不说允许格式」覆辙；返回不合规提示列表（空 = 全合规）。
    区段标题缺失（TASK_CARD_HEADERS 直给，非 append 调用）天然豁免——它们只报区名，无需格式。
    """
    import ast
    with Path(__file__).open(encoding="utf-8") as _f:
        src = _f.read()
    tree = ast.parse(src)
    bad: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "task_card_ok"):
            continue
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "append"):
                continue
            for a in sub.args:
                if isinstance(a, ast.JoinedStr):  # f-string
                    text = "".join(
                        p.value if isinstance(p, ast.Constant) else "{...}"
                        for p in a.values)
                elif isinstance(a, ast.Constant) and isinstance(a.value, str):
                    text = a.value
                else:
                    continue
                if not any(k in text for k in GATE_MSG_STYLE_KEYWORDS):
                    bad.append(text.strip()[:60])
    return bad


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def p0_nonempty(project) -> bool:
    """07-next-steps.md 的 P0 区至少有一条未勾选行动项。"""
    text = _read(os.path.join(project, NEXT_STEPS_REL))
    m = re.search(r"^## P0[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        return False
    section = m.group(1)
    return any(line.strip().startswith("- [ ]") for line in section.splitlines())


def _section(text, header):
    """提取指定 ## 区段正文；header 必须含 '## ' 前缀。"""
    m = re.search(rf"^{re.escape(header)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def _has_content(section):
    """区段是否有真实内容（排除占位符/注释行）。"""
    # 占位词表（R199 扩充：N/A/无用例/待定/TBD 等——与提示「常见错误」自洽）
    PLACEHOLDER_WORDS = (
        "可选", "空", "待填", "占位", "无", "N/?A", "无用例", "暂无", "待定", "TBD")
    placeholder_re = re.compile(
        r"(?:%s)(?:[\s、，,；;]*(?:%s))*"
        % ("|".join(PLACEHOLDER_WORDS), "|".join(PLACEHOLDER_WORDS)),
        re.I)

    def _is_placeholder_line(s):
        # 剥离行首列表/括号前缀与行尾闭合符
        s = re.sub(r"^[-—\s（(【\[]+", "", s)
        s = re.sub(r"[）)】\]\s]+$", "", s)
        return not s or placeholder_re.fullmatch(s) is not None

    for ln in section.splitlines():
        s = ln.strip()
        if not s or s.startswith("<!--"):
            continue
        if _is_placeholder_line(s):
            continue
        return True
    return False


def task_card_ok(project):
    """任务卡存在 + 11 个区 + 备选方案 ≥2 且带可行性 + 决策主体/回滚命令/失败预算/目标对齐校验。"""
    text = _read(os.path.join(project, TASK_CARD_REL))
    if not text:
        return False, ["任务卡缺失"]
    missing = [h for h in TASK_CARD_HEADERS if h not in text]
    # 备选方案：≥2 且每项带「可行性:」评估
    alt = _section(text, "## 备选方案")
    alt_lines = [ln.strip() for ln in alt.splitlines()
                 if ln.strip().startswith(("- ", "1.", "2.", "3.", "4."))]
    if len(alt_lines) < 2:
        missing.append(
            f"备选方案 <2（当前 {len(alt_lines)} 项）——允许格式：至少 2 项，每项以"
            "「- 方案 X：描述」或「1. 描述」开头且末尾附「可行性: 高|中|低」评估，"
            "如「- 方案 A：xxx。可行性: 高」；常见错误：只写 1 项、纯文字无方案编号")
    no_feas = [ln for ln in alt_lines
               if "可行性:" not in ln and "可行性：" not in ln]
    if no_feas:
        missing.append(
            f"备选方案 {len(no_feas)} 项缺「可行性:」评估——允许格式：每项末尾附"
            "「可行性: 高|中|低」（冒号后跟枚举值之一），如「- 方案 B：yyy。可行性: 中」；"
            "常见错误：只写方案不写可行性、写「可行性: 可以」等非枚举值")
    # 决策记录：必须标注决策主体
    dec = _section(text, "## 决策记录")
    if not re.search(r"决策主体[:：]\s*(人|模型|规则)", dec):
        missing.append(
            "决策记录缺「决策主体」标记——允许格式：「决策主体: 人|模型|规则」"
            "（枚举三值之一），如「决策主体: 人（用户指令明确）」；常见错误："
            "写「决策主体: 混合」「决策主体: 双方」等非枚举值、漏写该行")
    # 回滚预案：具体 git 命令，禁「手动 git checkout」
    # R199 改进（2026-08-16）：提示自解释化——列出允许格式 + 常见错误示例（git -C 前缀），
    # 消除隐式格式约定的返工（实测：git -C D:\... revert 不匹配正则却无提示）。
    rollback = _section(text, "## 回滚预案")
    if not re.search(r"git\s+(tag|restore|checkout|revert|reset|branch)", rollback):
        missing.append(
            "回滚预案缺具体 git 命令（允许格式：以 git tag / git restore / git checkout / "
            "git revert / git reset / git branch 开头的命令，如「git restore --source=<commit> -- <file>」；"
            "禁止：git -C <dir> 前缀、纯文字描述、手动 checkout 措辞）")
    if re.search(r"手动\s*git\s*checkout", rollback):
        missing.append("回滚预案含「手动 git checkout」措辞——须替换为具体 git 命令"
                       "（如 git restore --source=<commit> -- <file>），禁止「手动」引导")
    if re.search(r"git\s+-C\s+", rollback):
        missing.append(
            "回滚预案用了 git -C <dir> 前缀——格式校验无法识别；允许格式："
            "git tag/restore/checkout/revert/reset/branch 开头的命令，"
            "如「git revert abc123」；常见错误：在 git 与子命令间插入 -C 目录参数；"
            "目标仓库用 cd 或 --git-dir 说明（如「在 <SKILLS_ROOT> 执行 git revert ...」）")
    # 失败预算：声明最大回滚次数（含数字）
    budget = _section(text, "## 失败预算")
    if not re.search(r"\d", budget):
        missing.append(
            "失败预算区缺最大回滚次数——允许格式：声明含数字的回滚次数上限，"
            "如「最大回滚次数：2 次」（数字 0-9）；常见错误：只写"
            "「尽量不失败」「零容忍」等无数字表述")
    # 目标对齐：非空非占位
    align = _section(text, "## 目标对齐")
    if not _has_content(align):
        missing.append(
            "目标对齐区为空——允许格式：声明「行为在 01-goal 范围（…）」并简述关联，"
            "如「行为在 01-goal 范围（焚诀全局记忆与技能生态维护）」；常见错误："
            "留空、只写「无」")
    # 负面测试用例：涉及输入处理时强制
    inputs = (_section(text, "## 本轮目标") + _section(text, "## 验收判据")
              + _section(text, "## To-Do")).lower()
    # 剥离否定短语（如「不涉及输入处理」「无用户输入」），避免误触发强制负面测试
    inputs = re.sub(
        r"(不涉及|不处理|不需要|不含|无|没有)\s*(用户)?(输入|参数|请求|上传|表单)",
        "", inputs)
    if any(k.lower() in inputs for k in INPUT_PROCESSING_KEYWORDS):
        neg = _section(text, "## 负面测试用例")
        if not _has_content(neg):
            missing.append(
                "任务涉及输入处理：负面测试用例区必填 ≥1 条——允许格式：每条以「- 」"
                "开头，描述「输入 → 预期拒绝/防护行为」，如「- 空输入 → 拒绝并提示」；"
                "常见错误：写「N/A」「无」等非用例表述")
    return not missing, missing


def goal_alignment_ok(project):
    """目标对齐：01-goal.md 存在 + 任务卡目标对齐区非空。返回 (ok, 详情)。"""
    goal_text = _read(os.path.join(project, GOAL_REL))
    if not goal_text.strip():
        return False, "01-goal.md 缺失或为空（目标锚点不存在）"
    card = _read(os.path.join(project, TASK_CARD_REL))
    align = _section(card, "## 目标对齐")
    if not _has_content(align):
        return False, "任务卡目标对齐区为空"
    return True, "01-goal.md 存在 + 目标对齐区已声明"


def _progress_path(project):
    return os.path.join(project, PROGRESS_REL)


def _load_progress(project):
    path = _progress_path(project)
    if not os.path.exists(path):
        return None, "会话进度文件缺失: memory/sessions/fenjue-workflow.json"
    try:
        data = _load_json(path)
    except Exception as e:
        return None, f"会话进度解析失败: {e}"
    return data, None


def _missing_steps(data):
    steps = data.get("steps", {})
    missing = []
    for s in STEPS:
        st = steps.get(s, {})
        status = st.get("status") if isinstance(st, dict) else None
        if status not in ("done", "skip"):
            missing.append(s)
        elif status == "skip" and not (st.get("reason") or "").strip():
            missing.append(f"{s}(skip 缺原因)")
    return missing


def check_boot(project, platform="auto", as_json=False):
    """boot 门禁：P-1 绑定表 / 07 P0 / 常用技能清单。"""
    checks = [
        {"name": "P-1 绑定表", "pass": os.path.exists(os.path.join(project, P1_REL)),
         "detail": "memory/AGENTS.md"},
        {"name": "07 P0 非空", "pass": p0_nonempty(project),
         "detail": "memory/07-next-steps.md"},
        {"name": "常用技能清单", "pass": os.path.exists(os.path.join(project, COMMON_SKILLS_REL)),
         "detail": "memory/常用技能.md"},
    ]
    ok = all(c["pass"] for c in checks)
    if as_json:
        print(json.dumps({"schema": "fenjue-workflow-gate-boot-v1", "stage": "boot",
                          "platform": platform, "all_pass": ok, "checks": checks},
                         ensure_ascii=False))
    else:
        for c in checks:
            print(f"[{'PASS' if c['pass'] else 'FAIL'}] {c['name']} — {c['detail']}")
    return 0 if ok else 1


def check_task_card(project, platform="auto", as_json=False):
    ok, missing = task_card_ok(project)
    if as_json:
        print(json.dumps({"schema": "fenjue-workflow-gate-task-card-v1", "stage": "task-card",
                          "platform": platform, "all_pass": ok, "missing": missing},
                         ensure_ascii=False))
    else:
        print(f"[{'PASS' if ok else 'FAIL'}] 任务卡校验 — {TASK_CARD_REL}")
        for item in missing:
            print(f"  - {item}")
    return 0 if ok else 1


def check_adversarial(project, platform="auto", as_json=False):
    """对抗测试门禁：运行 eval/adversarial_test.py --json，exit 0 = PASS。"""
    adv = os.path.join(project, ADV_TEST_REL)
    payload = {
        "schema": "fenjue-workflow-gate-adversarial-v1",
        "stage": "adversarial",
        "platform": platform,
        "all_pass": False,
    }
    if not os.path.exists(adv):
        payload["detail"] = f"{ADV_TEST_REL} 缺失"
        if as_json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"[FAIL] 对抗测试脚本缺失 — {ADV_TEST_REL}")
        return 1
    try:
        r = subprocess.run(
            [sys.executable, adv, "--json"], cwd=project,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600)
    except Exception as e:
        payload["detail"] = f"对抗测试执行异常: {e}"
        if as_json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"[FAIL] 对抗测试执行异常: {e}")
        return 1
    data = None
    out = (r.stdout or "").strip()
    if out.startswith("{"):
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            data = None
    if as_json:
        if data is not None:
            print(out)
        else:
            payload["detail"] = "adversarial_test 未输出 JSON"
            payload["raw"] = out[-2000:]
            payload["stderr"] = (r.stderr or "")[-1000:]
            print(json.dumps(payload, ensure_ascii=False))
    else:
        print("[adversarial] " + ("PASS ✅" if r.returncode == 0 else "FAIL ❌"))
        if out:
            print(out[-4000:])
        if r.stderr:
            print((r.stderr or "")[-1000:], file=sys.stderr)
    return r.returncode


def check_git_atomicity(project, allow_dirty=False):
    """R210-03 M2（账实同步机制化）：savepoint 前置 git 原子性校验。

    治理目标（R210 §2.3-M2，2026-09-04 三时点快照实证账实漂移）：
      「有代码改动 → 必须 commit + 07 销账」原子完成，禁止半途收尾。
    判定（fail-closed）：
      - tracked 修改（M/A/D/R，含已暂存与未暂存）→ FAIL 并列明细
      - 未跟踪（??）：deliverables/*.md 报告类 → WARN 不阻断；
        _temp/_trash/.tmp 噪声区 → 豁免；其余 → FAIL
      - allow_dirty=True 显式人工放行（豁免动作记入输出，可审计）
    多客户端并行环境注意：本函数只陈述工作树事实；FAIL 输出附带
    「改动归属自查」提示——若 dirty 来自并行会话在途工作，由人裁决
    等待错峰或协调提交，不得由 agent 单方回滚。
    非 git 仓 / git 不可用 → skip（返回 ok，不误伤只读项目）。

    R279（2026-09-23）：子进程 git 剥离继承的 GIT_* 环境。实证：
    pre-commit hook 导出的 GIT_DIR（真仓 .git 绝对路径）会被临时仓的
    `git status` 继承，导致读到真仓索引而全员 FAIL。修法：靠 cwd 做仓库发现。
    """
    if allow_dirty:
        return {"git_atomicity_ok": True, "allow_dirty": True,
                "dirty_tracked": [], "untracked_reports": []}
    _clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=project,
                           capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace", env=_clean_env)
    except Exception as e:  # noqa: BLE001 — 环境不可用降级放行（如非 git 项目）
        return {"git_atomicity_ok": True, "skip": f"git 不可用: {e}",
                "dirty_tracked": [], "untracked_reports": []}
    if r.returncode != 0:
        return {"git_atomicity_ok": True, "skip": f"git status rc={r.returncode}",
                "dirty_tracked": [], "untracked_reports": []}
    dirty, reports = [], []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        code, path = line[:2], line[3:].strip().strip('"')
        norm = path.replace("\\", "/")
        if code == "??":
            if norm.startswith("deliverables/"):
                reports.append(path)              # 报告类 WARN（目录折叠形态 `?? deliverables/` 亦命中）
            elif norm.startswith(("_temp/", "_trash/", ".tmp/", "_bak/")):
                continue                          # 噪声回收区豁免
            else:
                dirty.append(f"?? {path}")
        else:
            dirty.append(f"{code} {path}")
    return {"git_atomicity_ok": not dirty, "allow_dirty": False,
            "dirty_tracked": dirty, "untracked_reports": reports}


def check_pre_savepoint(project, platform="auto", as_json=False, allow_dirty=False):
    p0_ok = p0_nonempty(project)
    ok = p0_ok
    git_at = check_git_atomicity(project, allow_dirty=allow_dirty)
    ok = ok and git_at["git_atomicity_ok"]
    data, err = _load_progress(project)
    steps_out, missing, cok, cmissing, card_rel = [], [], True, [], None
    goal_ok, goal_detail = goal_alignment_ok(project)
    ok = ok and goal_ok
    # R1: handoff_loaded 机器校验（T25 补漏项）— 执行过实际工作(⑥ done)但未加载
    # A-project-handoff(④ 非 done) = 修改未受项目记忆管理保护 → FAIL；只读任务不误伤
    handoff_loaded = True
    handoff_detail = "skip(只读/无需项目记忆管理)"
    if err is None:
        s4 = (data.get("steps", {}).get("4") or {})
        s6 = (data.get("steps", {}).get("6") or {})
        if isinstance(s4, dict) and s4.get("status") == "done":
            handoff_loaded = True
            handoff_detail = "done(A-project-handoff 已加载)"
        else:
            handoff_loaded = False
            handoff_detail = "Step4 未 done（未加载 A-project-handoff）"
            if isinstance(s6, dict) and s6.get("status") == "done":
                ok = False
                handoff_detail += " + Step6 已执行实际工作 → 修改未受项目记忆管理保护，savepoint 拒绝"
            else:
                handoff_detail += " + Step6 未执行（只读/纯咨询任务，放行）"
    if err:
        missing = ["progress"]
        ok = False
    else:
        steps = data.get("steps", {})
        for s in STEPS:
            st = steps.get(s, {})
            steps_out.append({"step": s, "status": st.get("status", "pending"),
                              "reason": st.get("reason", "")})
        missing = _missing_steps(data)
        ok = ok and not missing
        card_rel = data.get("task_card")
        if card_rel:
            cok, missing = task_card_ok(project)
            cmissing = missing
            ok = ok and cok
    payload = {
        "schema": "fenjue-workflow-gate-pre-savepoint-v1",
        "stage": "pre-savepoint",
        "platform": platform,
        "all_pass": ok,
        "p0_ok": p0_ok,
        "git_atomicity": git_at,
        "goal_alignment_ok": goal_ok,
        "goal_alignment_detail": goal_detail,
        "handoff_loaded": handoff_loaded,
        "handoff_detail": handoff_detail,
        "progress_error": err,
        "steps": steps_out,
        "missing_steps": missing,
        "task_card": card_rel,
        "task_card_ok": cok,
        "task_card_missing": cmissing,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if ok else 1
    if not p0_ok:
        print("[FAIL] 07 P0 为空（savepoint 前置拒绝）")
    if not goal_ok:
        print(f"[FAIL] 目标对齐: {goal_detail}")
    if not handoff_loaded:
        print(f"[{'FAIL' if 'Step6 已执行' in handoff_detail else 'WARN'}] handoff_loaded: {handoff_detail}")
    if err:
        print(f"[FAIL] {err}")
    if missing and not err:
        print(f"[FAIL] 步骤未达可收尾态: {missing}")
    for st in steps_out:
        flag = "done" if st["status"] == "done" else ("skip" if st["status"] == "skip" else "pending")
        print(f"[{flag.upper()}] Step {st['step']} — {st['reason'] or st['status']}")
    if card_rel:
        print(f"[{'PASS' if cok else 'FAIL'}] 任务卡声明 — {card_rel}")
        for item in cmissing:
            print(f"  - {item}")
    print("=" * 40)
    print("pre-savepoint: " + ("PASS ✅" if ok else "FAIL ❌"))
    return 0 if ok else 1


def bootstrap(project, platform, as_json):
    """应实跑清单：常驻 + 项目常用（注入 ≠ 实跑）。"""
    text = _read(os.path.join(project, COMMON_SKILLS_REL))

    def section(name):
        m = re.search(rf"^## {name}[^\n]*\n(.*?)(?=^## )", text, re.M | re.S)
        if not m:
            return []
        return [ln.strip()[2:] for ln in m.group(1).splitlines()
                if ln.strip().startswith("- ")][:20]

    resident = section("常驻")
    project_common = section("项目常用")
    gate = ""
    p1 = _read(os.path.join(project, P1_REL))
    gm = re.search(r"门禁命令:\s*([^\s|]+)", p1)
    if gm:
        gate = gm.group(1)
    data = {
        "platform": platform,
        "spec_version": WORKFLOW_VERSION,
        "resident": resident,
        "project_common": project_common,
        "gate_command": gate,
        "note": "注入≠实跑：以上为应实跑清单；未列出的 skill 按 unified_router 命中再加载",
    }
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"[bootstrap] 平台={platform} 规范=V{WORKFLOW_VERSION} 门禁={gate or '无'}")
        print(f"[bootstrap] 常驻实跑({len(resident)}): " + ", ".join(resident))
        print(f"[bootstrap] 项目常用({len(project_common)}): " + ", ".join(project_common))
    return 0


def status(project, as_json):
    data, err = _load_progress(project)
    if err:
        print(f"[status] FAIL — {err}")
        return 1
    lines = []
    steps = data.get("steps", {})
    for s in STEPS:
        st = steps.get(s, {})
        status = st.get("status", "pending")
        reason = st.get("reason", "")
        lines.append({"step": s, "status": status, "reason": reason})
    missing = _missing_steps(data)
    if as_json:
        print(json.dumps({"updated": data.get("updated"), "steps": lines,
                          "missing": missing}, ensure_ascii=False, indent=2))
    else:
        for ln in lines:
            print(f"[{ln['status'].upper()}] Step {ln['step']} — {ln['reason'] or ''}")
        if missing:
            print(f"[status] 缺步清单: {missing}")
        else:
            print("[status] 七步状态齐，可进入 savepoint")
    return 0


def next_template(platform, as_json):
    lines = [
        f"收尾推荐下一步（平台 {platform}，≤3 条）:",
        "1. [用户操作] …",
        "2. [agent 自动] …",
        "3. [P2 可选] …",
        "反馈入口: http://localhost:8787 或 python feedback/app.py --close <id>",
    ]
    if as_json:
        print(json.dumps({"platform": platform, "max": 3,
                          "template": lines[:-1],
                          "feedback": "http://localhost:8787 / feedback/app.py --close <id>"},
                         ensure_ascii=False, indent=2))
    else:
        print("\n".join(lines))
    return 0


TASK_CARD_TEMPLATE = """# 任务卡 — {task}

> 来源：{source} | 平台：{platform} | {date}
> 填写提示（R199 四要素：每个区按「允许格式 + 示例 + 常见错误」填写，规避门禁返工）
> 门禁校验失败提示 = 缺什么 + 允许格式 + 示例 + 常见错误；本模板占位即四要素示例。

## 本轮目标

（一句话定义本轮要交付什么，锚定需求澄清结论；允许格式：1 句动宾结构；常见错误：空、只写任务名）

## 验收判据

1. （二元判据，可机器/命令验证；允许格式：每条「可执行验证」的断言，如「verify 13 PASS」；常见错误：写「完成」「做好」等不可验证描述）
2. （二元判据）
3. （二元判据）

## 负面测试用例

- （涉及输入处理/解析/用户输入时必填 ≥1 条；允许格式：每条「输入 → 预期拒绝/防护行为」，如「- 空输入 → 拒绝并提示」；常见错误：写「N/A」「无」等占位）

## 备选方案（≥2，每项带可行性评估）

- 方案 A：…（选定：理由 | 可行性: 高|中|低——枚举值之一，如「可行性: 高」；常见错误：只写方案不写可行性、写「可行性: 可以」等非枚举值）
- 方案 B：…（否决：理由 | 可行性: 中）

## 失败预算

- 最大回滚次数：N 次（允许格式：含数字的回滚上限，如「最大回滚次数：2 次」，N 为 0-9；0 = 不允许失败；常见错误：写「尽量不失败」「零容忍」无数字）

## To-Do

- [ ] （子任务 1；允许格式：每条以「- [ ]」开头 + 动词开头）
- [ ] （子任务 2）

## Checkpoint 计划

- CP1 （阶段 + 验证命令；允许格式：每阶段附可跑命令，如「CP1 编译 py_compile」）
- CP2 （阶段 + 验证命令）

## 回滚预案

- git tag R196-<任务名>-<日期>（改动前打 tag；允许格式：git tag/restore/checkout/revert/reset/branch 开头；常见错误：在 git 与子命令间插入 -C 目录参数（-C 前缀写法）会被门禁拦截、纯文字描述、手动 checkout 措辞）
- git restore <文件路径>（如「git restore --source=HEAD -- eval/foo.py」）

## 目标对齐

- 声明：行为在 01-goal 范围（…）；允许格式：「行为在 01-goal 范围（一句话关联）」，如「行为在 01-goal 范围（焚诀全局记忆与技能生态维护）」；常见错误：留空、只写「无」

## 新方向（P2 暂存）

- （执行中发现的新方向，记这里不打断；常见错误：删掉本区——门禁要求 11 区齐全）

## 决策记录

- 决策：… | 决策主体: 人|模型|规则（允许格式：三枚举值之一，如「决策主体: 人（用户指令明确）」；常见错误：写「混合」「双方」等非枚举值、漏写该行；同步 07-next-steps）
"""


def task_card(platform, as_json):
    text = TASK_CARD_TEMPLATE.format(
        task="<任务名>", source="<需求来源>", platform=platform,
        date=datetime.date.today().isoformat())
    print(text)
    return 0


def record(project, platform, step, state, reason, as_json):
    if step not in STEPS:
        print(f"[record] FAIL — step 必须是 {STEPS} 之一，收到 {step!r}")
        return 2
    if state not in ("done", "skip"):
        print(f"[record] FAIL — state 必须是 done|skip，收到 {state!r}")
        return 2
    if state == "skip" and not reason.strip():
        print("[record] FAIL — skip 必须带 reason")
        return 2
    data = {}
    path = _progress_path(project)
    if os.path.exists(path):
        try:
            data = _load_json(path)
        except Exception:
            data = {}
    data.setdefault("platform", platform)
    data.setdefault("task_card", TASK_CARD_REL)
    data.setdefault("steps", {})
    data["steps"][step] = {"status": state, "reason": reason.strip()}
    data["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save_json(path, data)
    print(f"[record] Step {step} → {state}" + (f"（{reason.strip()}）" if reason.strip() else ""))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(description="焚诀七步闭环工作流门禁（R195）")
    p.add_argument("--check", choices=["boot", "task-card", "pre-savepoint", "adversarial"])
    p.add_argument("--allow-dirty", action="store_true",
                   help="pre-savepoint 专用：显式豁免 git 账实原子性校验（豁免记入输出可审计）")
    p.add_argument("--bootstrap", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--next", action="store_true")
    p.add_argument("--task-card", action="store_true")
    p.add_argument("--adversarial", action="store_true")
    p.add_argument("--record", nargs="+", metavar="ARGS")
    p.add_argument("--platform", default="")
    p.add_argument("--project", default=PROJECT_DIR)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    cmds = [args.check is not None, args.bootstrap, args.status,
            args.next, args.task_card, args.adversarial, args.record is not None]
    if sum(bool(c) for c in cmds) != 1:
        print("[usage] 必须且只能指定一个子命令 "
              "(--check/--bootstrap/--status/--next/--task-card/--adversarial/--record)",
              file=sys.stderr)
        return 2

    platform = args.platform
    if args.task_card:
        return task_card(platform or "cx", args.json)
    if platform not in ENDPOINTS:
        if (args.check or args.adversarial) and platform in ("", "auto"):
            # --check / --adversarial 不依赖平台；handoff.py savepoint 集成时传 auto
            platform = "auto"
        else:
            print(f"[usage] 平台必须是 {ENDPOINTS} 之一，收到 {platform!r}", file=sys.stderr)
            return 2

    project = os.path.abspath(args.project)
    if args.adversarial:
        # 与 --check adversarial 等价；#17 R198.2 机器门禁快捷入口
        return check_adversarial(project, platform or "auto", args.json)
    if args.check:
        fn = {"boot": check_boot, "task-card": check_task_card,
              "pre-savepoint": check_pre_savepoint,
              "adversarial": check_adversarial}[args.check]
        return fn(project, platform, args.json)
    if args.bootstrap:
        return bootstrap(project, platform, args.json)
    if args.status:
        return status(project, args.json)
    if args.next:
        return next_template(platform, args.json)
    # --record
    if len(args.record) not in (2, 3):
        print("[usage] --record 需要 <step> <done|skip> [reason]", file=sys.stderr)
        return 2
    step, state = args.record[0], args.record[1]
    reason = args.record[2] if len(args.record) == 3 else ""
    return record(project, platform, step, state, reason, args.json)


if __name__ == "__main__":
    sys.exit(main())
