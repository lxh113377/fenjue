#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workflow_gate 契约测试（R195）：boot / task-card / pre-savepoint 正反例。"""

import os
import json
import sys
from pathlib import Path

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import workflow_gate as wg  # noqa: E402
from truth_constants import ENDPOINTS  # noqa: E402


CARD_OK = """# 任务卡

## 本轮目标

测试目标（普通任务，不涉及输入处理）

## 验收判据

1. 判据一
2. 判据二

## 负面测试用例

- （可选）

## 备选方案（≥2）

- 方案 A：甲（选定：理由 | 可行性：成本低实现快）
- 方案 B：乙（否决：理由 | 可行性：成本高周期长）

## 失败预算

- 允许最大回滚次数：1 次

## To-Do

- [ ] 子任务

## Checkpoint 计划

- CP1 验证

## 回滚预案

- git tag r196-test
- git restore memory/task-card.md

## 目标对齐

- 声明：测试任务在 01-goal.md 定义的范围内

## 新方向（P2 暂存）

- （空）

## 决策记录

- 决策：走方案 A | 决策主体: 人
"""


def _base(tmp_path, p0=True, card=True, progress=True):
    memory = tmp_path / "memory"
    memory.mkdir(exist_ok=True)
    (memory / "AGENTS.md").write_text(
        "# P-1\n| 触发条件 | 必加载 skill |\n| 修改 | A-project-handoff |\n"
        "门禁命令: eval/verify_truth_consistency.py\n", encoding="utf-8")
    (memory / "01-goal.md").write_text(
        "# 目标\n\n- 测试项目目标（范围：记忆/工作流管理）\n", encoding="utf-8")
    (memory / "07-next-steps.md").write_text(
        ("## P0 — 必须做\n\n- [ ] 验收任务\n\n" if p0 else "## P0 — 必须做\n\n## P1\n"),
        encoding="utf-8")
    (memory / "常用技能.md").write_text(
        "## 常驻\n\n- A-memory-start\n- A-project-handoff\n- A-get-memory\n"
        "- A-ask-questions\n- A-prompt-better\n\n## 项目常用\n\n- fenjue-routing-health-check\n",
        encoding="utf-8")
    if card:
        (memory / "task-card.md").write_text(CARD_OK, encoding="utf-8")
    if progress:
        steps = {str(i): {"status": "done", "reason": "ok"} for i in range(1, 8)}
        wg._save_json(memory / "sessions" / "fenjue-workflow.json",
                      {"platform": "cx", "task_card": "memory/task-card.md",
                       "steps": steps, "updated": "2026-08-12T00:00:00"})
    return tmp_path


def test_boot_rejects_missing_p1(tmp_path) -> None:
    assert wg.main(["--check", "boot", "--platform", "cx",
                    "--project", str(tmp_path)]) == 1


def test_boot_passes_full_project(tmp_path) -> None:
    project = _base(tmp_path)
    assert wg.main(["--check", "boot", "--platform", "cx",
                    "--project", str(project)]) == 0


def test_pre_savepoint_rejects_empty_p0(tmp_path) -> None:
    project = _base(tmp_path, p0=False)
    assert wg.main(["--check", "pre-savepoint", "--platform", "cx",
                    "--project", str(project)]) == 1


def test_pre_savepoint_rejects_missing_steps(tmp_path) -> None:
    project = _base(tmp_path, progress=False)
    assert wg.main(["--check", "pre-savepoint", "--platform", "cx",
                    "--project", str(project)]) == 1


def test_pre_savepoint_passes_when_all_steps_ready(tmp_path) -> None:
    project = _base(tmp_path)
    assert wg.main(["--check", "pre-savepoint", "--platform", "cx",
                    "--project", str(project)]) == 0


def test_five_platforms_accepted(tmp_path) -> None:
    project = _base(tmp_path)
    for ep in ENDPOINTS:
        assert wg.main(["--bootstrap", "--platform", ep,
                        "--project", str(project)]) == 0, ep


def test_invalid_platform_rejected(tmp_path) -> None:
    assert wg.main(["--bootstrap", "--platform", "zz",
                    "--project", str(tmp_path)]) == 2


def test_check_accepts_platform_auto(tmp_path) -> None:
    project = _base(tmp_path)
    assert wg.main(["--check", "boot", "--platform", "auto",
                    "--project", str(project)]) == 0
    assert wg.main(["--check", "pre-savepoint", "--platform", "auto",
                    "--project", str(project)]) == 0


def test_non_check_rejects_platform_auto(tmp_path) -> None:
    project = _base(tmp_path)
    assert wg.main(["--bootstrap", "--platform", "auto",
                    "--project", str(project)]) == 2


def test_task_card_template_contains_required_fields() -> None:
    for header in wg.TASK_CARD_HEADERS:
        assert header in wg.TASK_CARD_TEMPLATE
    assert wg.main(["--task-card"]) == 0


def test_task_card_requires_two_alternatives(tmp_path) -> None:
    project = _base(tmp_path, card=False)
    card = CARD_OK.replace("- 方案 A：甲（选定：理由 | 可行性：成本低实现快）\n"
                           "- 方案 B：乙（否决：理由 | 可行性：成本高周期长）",
                           "- 方案 A：甲（选定：理由 | 可行性：成本低实现快）")
    (project / "memory" / "task-card.md").write_text(card, encoding="utf-8")
    assert wg.main(["--check", "task-card", "--platform", "cx",
                    "--project", str(project)]) == 1


def test_task_card_requires_decision_subject(tmp_path) -> None:
    project = _base(tmp_path)
    card = CARD_OK.replace("| 决策主体: 人", "")
    (project / "memory" / "task-card.md").write_text(card, encoding="utf-8")
    assert wg.main(["--check", "task-card", "--platform", "cx",
                    "--project", str(project)]) == 1


def test_task_card_requires_feasibility_evaluation(tmp_path) -> None:
    project = _base(tmp_path)
    card = (CARD_OK.replace(" | 可行性：成本低实现快", "")
                   .replace(" | 可行性：成本高周期长", ""))
    (project / "memory" / "task-card.md").write_text(card, encoding="utf-8")
    assert wg.main(["--check", "task-card", "--platform", "cx",
                    "--project", str(project)]) == 1


def test_task_card_rejects_manual_git_checkout(tmp_path) -> None:
    project = _base(tmp_path)
    card = CARD_OK.replace("git restore memory/task-card.md", "手动 git checkout")
    (project / "memory" / "task-card.md").write_text(card, encoding="utf-8")
    assert wg.main(["--check", "task-card", "--platform", "cx",
                    "--project", str(project)]) == 1


def test_task_card_requires_goal_alignment(tmp_path) -> None:
    project = _base(tmp_path)
    card = CARD_OK.replace("\n- 声明：测试任务在 01-goal.md 定义的范围内", "")
    (project / "memory" / "task-card.md").write_text(card, encoding="utf-8")
    assert wg.main(["--check", "task-card", "--platform", "cx",
                    "--project", str(project)]) == 1


def test_task_card_requires_negative_cases_for_input_processing(tmp_path) -> None:
    project = _base(tmp_path)
    card = (CARD_OK
            .replace("测试目标（普通任务，不涉及输入处理）", "解析用户上传的表单输入")
            .replace("\n- （可选）", ""))
    (project / "memory" / "task-card.md").write_text(card, encoding="utf-8")
    assert wg.main(["--check", "task-card", "--platform", "cx",
                    "--project", str(project)]) == 1


def test_negative_cases_optional_without_input_keywords(tmp_path) -> None:
    project = _base(tmp_path)
    assert wg.main(["--check", "task-card", "--platform", "cx",
                    "--project", str(project)]) == 0
    assert wg.main(["--check", "pre-savepoint", "--platform", "cx",
                    "--project", str(project)]) == 0


def test_adversarial_missing_script(tmp_path) -> None:
    project = _base(tmp_path)
    assert wg.main(["--check", "adversarial", "--platform", "cx",
                    "--project", str(project)]) == 1


def test_adversarial_passes_with_runner(tmp_path) -> None:
    project = _base(tmp_path)
    adv_dir = project / "eval"
    adv_dir.mkdir(exist_ok=True)
    (adv_dir / "adversarial_test.py").write_text(
        '#!/usr/bin/env python3\n'
        'import json, sys\n'
        'print(json.dumps({"schema": "fenjue-adversarial-v1", '
        '"all_pass": True, "checks": {}}))\n'
        'sys.exit(0)\n', encoding="utf-8")
    assert wg.main(["--check", "adversarial", "--platform", "cx",
                    "--project", str(project)]) == 0


def test_record_and_status_roundtrip(tmp_path, capsys) -> None:
    project = _base(tmp_path, progress=False)
    assert wg.main(["--record", "6", "done", "执行完成", "--platform", "cx",
                    "--project", str(project)]) == 0
    assert wg.main(["--status", "--platform", "cx",
                    "--project", str(project)]) == 0
    out = capsys.readouterr().out
    assert "Step 6" in out


def test_skip_requires_reason(tmp_path) -> None:
    project = _base(tmp_path, progress=False)
    assert wg.main(["--record", "1", "skip", "", "--platform", "cx",
                    "--project", str(project)]) == 2


def test_check_pre_savepoint_json_positive(tmp_path, capsys) -> None:
    project = _base(tmp_path)
    assert wg.main(["--check", "pre-savepoint", "--platform", "auto",
                    "--project", str(project), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == "fenjue-workflow-gate-pre-savepoint-v1"
    assert data["all_pass"] is True
    assert len(data["steps"]) == 7
    assert data["missing_steps"] == []
    assert data["goal_alignment_ok"] is True


def test_check_pre_savepoint_json_negative(tmp_path, capsys) -> None:
    project = _base(tmp_path, p0=False)
    assert wg.main(["--check", "pre-savepoint", "--platform", "auto",
                    "--project", str(project), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["all_pass"] is False
    assert data["p0_ok"] is False


def test_check_boot_json(tmp_path, capsys) -> None:
    project = _base(tmp_path)
    assert wg.main(["--check", "boot", "--platform", "auto",
                    "--project", str(project), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["all_pass"] is True
    assert len(data["checks"]) == 3


# ── R199 提示自解释化回归（2026-08-17）：每个校验项失败提示须含「允许格式」───

def _card_variant(tmp_path, **over):
    """基于 CARD_OK 生成变体任务卡，over 为「区段标题 → 新内容」替换。"""
    text = CARD_OK
    for section, content in over.items():
        # 替换区段：从标题行到下一个 ## 标题之前（末节截到文件尾）
        start = text.index(section)
        nxt = text.find("\n## ", start + len(section))
        if nxt == -1:
            nxt = len(text)
        text = text[:start] + section + "\n" + content + text[nxt:]
    p = tmp_path / "memory" / "task-card.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return tmp_path


def test_alt_count_hint_contains_format(tmp_path) -> None:
    project = _card_variant(tmp_path, **{"## 备选方案（≥2）": "- 方案 A：xxx。可行性: 高\n"})
    ok, missing = wg.task_card_ok(str(project))
    joined = "; ".join(missing)
    assert not ok
    assert "至少 2 项" in joined and "可行性: 高|中|低" in joined


def test_alt_feasibility_hint_contains_enum(tmp_path) -> None:
    project = _card_variant(tmp_path, **{"## 备选方案（≥2）":
                                         "- 方案 A：xxx\n- 方案 B：yyy\n"})
    ok, missing = wg.task_card_ok(str(project))
    joined = "; ".join(missing)
    assert not ok
    assert "可行性: 高|中|低" in joined and "非枚举值" in joined


def test_decision_subject_hint_contains_enum(tmp_path) -> None:
    project = _card_variant(tmp_path, **{"## 决策记录": "- 决策主体: 混合\n"})
    ok, missing = wg.task_card_ok(str(project))
    joined = "; ".join(missing)
    assert not ok
    assert "人|模型|规则" in joined and "非枚举值" in joined


def test_budget_hint_contains_format(tmp_path) -> None:
    project = _card_variant(tmp_path, **{"## 失败预算": "- 尽量不失败，零容忍\n"})
    ok, missing = wg.task_card_ok(str(project))
    joined = "; ".join(missing)
    assert not ok
    assert "最大回滚次数" in joined and "数字" in joined


def test_negative_placeholder_rejected(tmp_path) -> None:
    """占位词增强：负面测试区写「- N/A 无用例」视为无内容 → 拒绝。"""
    project = _card_variant(
        tmp_path,
        **{"## 本轮目标": "测试目标（涉及输入解析）",
           "## 负面测试用例": "- N/A 无用例\n"})
    ok, missing = wg.task_card_ok(str(project))
    assert not ok
    assert any("负面测试用例区必填" in m for m in missing)


def test_has_content_placeholder_words() -> None:
    """_has_content 占位词检测：N/A/无/待定 视为空；「无网络依赖」不误伤。"""
    assert wg._has_content("- N/A 无用例\n") is False
    assert wg._has_content("- 无\n") is False
    assert wg._has_content("（待定）\n") is False
    assert wg._has_content("- 无网络依赖，纯本地执行\n") is True
    assert wg._has_content("- 空输入 → 拒绝并提示\n") is True


# ── R199 规范执行审查 + 模板单一数据源（2026-08-17）──────────────────────────

def test_audit_gate_msg_style_all_compliant() -> None:
    """GATE_MSG_STYLE 遵守审查：全部 missing.append 提示含四要素关键词。"""
    bad = wg.audit_gate_msg_style()
    assert bad == [], f"不合规提示（缺四要素）: {bad}"


def test_task_card_template_single_source() -> None:
    """任务卡模板单一数据源：A-project-handoff 不得定义独立任务卡模板。

    init 冷启动不生成 task-card（仅 savepoint 读取校验）；唯一权威模板 =
    workflow_gate.TASK_CARD_TEMPLATE——若 handoff.py 出现模板头，说明两套模板
    并存漂移，立即 FAIL。
    """
    import os as _os
    handoff_py = Path(_os.path.expanduser("~")) / ".workbuddy" / "skills" / \
        "A-project-handoff" / "scripts" / "handoff.py"
    if not handoff_py.exists():
        return  # 无 handoff 环境（CI）跳过
    src = handoff_py.read_text(encoding="utf-8")
    assert "## 备选方案（≥2）" not in src, \
        "A-project-handoff 定义了独立任务卡模板头——违反单一数据源（唯一权威 = workflow_gate.TASK_CARD_TEMPLATE）"
    # handoff.py 不得内嵌任务卡模板字符串（TASK_CARD 字样只应出现在门禁读取/注释）
    assert "TASK_CARD_TEMPLATE" not in src, \
        "handoff.py 不应复制 workflow_gate 的任务卡模板常量"


# ============ R210-03 M2：git 账实原子性校验 ============

def _git(repo, *args):
    import subprocess
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


@pytest.fixture()
def mini_repo(tmp_path):
    """独立临时 git 仓（不污染焚诀仓）。"""
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.email=t@t.com", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "init")
    return repo


def test_git_atomicity_clean_repo_pass(mini_repo):
    out = wg.check_git_atomicity(str(mini_repo))
    assert out["git_atomicity_ok"] is True
    assert out["dirty_tracked"] == []


def test_git_atomicity_tracked_dirty_fails(mini_repo):
    tracked = mini_repo / "code.py"
    tracked.write_text("x = 1\n", encoding="utf-8")
    _git(mini_repo, "add", "code.py")
    _git(mini_repo, "-c", "user.email=t@t.com", "-c", "user.name=t",
         "commit", "-q", "-m", "add code")
    tracked.write_text("x = 2\n", encoding="utf-8")   # 未提交修改 → FAIL
    out = wg.check_git_atomicity(str(mini_repo))
    assert out["git_atomicity_ok"] is False
    assert any("code.py" in d for d in out["dirty_tracked"])


def test_git_atomicity_staged_dirty_fails(mini_repo):
    f = mini_repo / "code.py"
    f.write_text("x = 1\n", encoding="utf-8")
    _git(mini_repo, "add", "code.py")                  # 仅暂存未提交 → 同样 FAIL
    out = wg.check_git_atomicity(str(mini_repo))
    assert out["git_atomicity_ok"] is False


def test_git_atomicity_deliverables_md_is_warn_only(mini_repo):
    (mini_repo / "deliverables").mkdir()
    (mini_repo / "deliverables" / "report.md").write_text("# r\n", encoding="utf-8")
    out = wg.check_git_atomicity(str(mini_repo))
    assert out["git_atomicity_ok"] is True             # 报告类 WARN 不阻断
    assert len(out["untracked_reports"]) == 1


def test_git_atomicity_noise_dirs_exempt(mini_repo):
    for d in ("_temp", "_trash", ".tmp"):
        (mini_repo / d).mkdir()
        (mini_repo / d / "x.txt").write_text("n", encoding="utf-8")
    out = wg.check_git_atomicity(str(mini_repo))
    assert out["git_atomicity_ok"] is True             # 噪声回收区豁免


def test_git_atomicity_other_untracked_fails(mini_repo):
    (mini_repo / "loose.py").write_text("y = 2\n", encoding="utf-8")
    out = wg.check_git_atomicity(str(mini_repo))
    assert out["git_atomicity_ok"] is False            # 非白名单未跟踪 → FAIL


def test_git_atomicity_allow_dirty_explicit_pass(mini_repo):
    f = mini_repo / "code.py"
    f.write_text("x = 1\n", encoding="utf-8")
    _git(mini_repo, "add", "code.py")
    out = wg.check_git_atomicity(str(mini_repo), allow_dirty=True)
    assert out["git_atomicity_ok"] is True and out["allow_dirty"] is True


def test_git_atomicity_non_git_dir_skips(tmp_path):
    out = wg.check_git_atomicity(str(tmp_path))        # 非 git 仓 → skip 放行
    assert out["git_atomicity_ok"] is True and out.get("skip")


def test_git_atomicity_ignores_inherited_hook_env(mini_repo, tmp_path, monkeypatch):
    """R279：hook 导出的 GIT_DIR/GIT_WORK_TREE 不得毒化临时仓判定。

    实证（2026-09-23）：pre-commit hook 继承 GIT_DIR=真仓.git 时，
    干净 mini 仓被判 dirty，全员 FAIL。修法：子进程剥离 GIT_*，靠 cwd 发现。
    """
    dirty = tmp_path / "other"
    dirty.mkdir()
    _git(dirty, "init", "-q")
    (dirty / "uncommitted.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", str(dirty / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(dirty))
    out = wg.check_git_atomicity(str(mini_repo))
    assert out["git_atomicity_ok"] is True
    assert out["dirty_tracked"] == []


def test_pre_savepoint_payload_carries_git_atomicity(mini_repo, capsys):
    rc = wg.check_pre_savepoint(str(mini_repo), as_json=True, allow_dirty=False)
    payload = json.loads(capsys.readouterr().out)
    assert "git_atomicity" in payload                 # M2 新字段进 JSON（schema 兼容追加）
    assert rc in (0, 1)
