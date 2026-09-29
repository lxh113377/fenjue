#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸清单与 hook 文案自洽测试（对标轮四 6-E/7-B + D-21 治本）。

病灶：闸数/C 项范围以**静态抄写**散落在模块 docstring、跟踪 hook、以及**不被 git 跟踪的
.git/hooks 副本**里。前三轮 D-5 标"已修"，本轮抽验发现 `.git/hooks/pre-commit` 仍写
「13 道 / C1~C19」、GM 仓 hook 仍写「C1~C18」，实为 15 道 / C1~C30 —— 因为 git 根本
看护不到 .git/。故本测试做两件事：① 断言"数字只能派生，不能抄写"；② 断言"跟踪副本 ==
在役 hook"（把不可跟踪面拉回可比面）。
"""

import os
import re
import sys

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(EVAL_DIR)
sys.path.insert(0, EVAL_DIR)

import pre_commit_hooks as pch  # noqa: E402

HOOK_TRACKED = os.path.join(EVAL_DIR, "hooks", "pre-commit")
HOOK_LIVE = os.path.join(ROOT, ".git", "hooks", "pre-commit")
STATIC_COUNT = re.compile(r"\d+\s*道")
STATIC_C_RANGE = re.compile(r"C1~C\d+")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_gate_names_unique_and_present():
    names = pch.GATE_NAMES
    assert len(names) == len(set(names)), "闸名重复 = 有闸被复制粘贴（对标轮四 D-26 同族）"
    assert "gate-stubs" in names, "桩门禁必须仍在拦截链上（6-E 防回滚）"
    assert "tdd-gate" in names and "truth-consistency" in names


def test_every_gate_declared_in_docstring():
    doc = pch.__doc__ or ""
    missing = [n for n in pch.GATE_NAMES if n not in doc]
    assert not missing, "GATES 新增闸未同步模块 docstring: %s" % missing


def test_docstring_does_not_hardcode_gate_count():
    """docstring 可列名，但不得出现「N 道」这类会腐烂的**现状**总数。

    历史留痕行（含「对标轮」标记）豁免——本仓规则是历史不重写，只禁现状断言（C5 同口径）。
    """
    doc = pch.__doc__ or ""
    live_lines = [ln for ln in doc.splitlines() if "对标轮" not in ln]
    offenders = [ln.strip() for ln in live_lines if STATIC_COUNT.search(ln)]
    assert not offenders, "模块 docstring 抄写了闸数，改派生: %s" % offenders


def test_main_prints_derived_count():
    src = _read(os.path.join(EVAL_DIR, "pre_commit_hooks.py"))
    assert "GATES-COUNT" in src, "PASS 行须回显派生闸数，供 hook 读取"


def test_tracked_hook_has_no_stale_literals():
    text = _read(HOOK_TRACKED)
    assert not STATIC_COUNT.search(text), "跟踪 hook 抄写了闸数（D-21）"
    assert not STATIC_C_RANGE.search(text), "跟踪 hook 抄写了 C 项范围（D-21）"


@pytest.mark.skipif(not os.path.exists(HOOK_LIVE), reason="本机无 .git/hooks/pre-commit（非仓库工作副本）")
def test_live_hook_matches_tracked_copy():
    """核心：不被 git 跟踪的在役 hook 一旦与跟踪副本分叉，就是 D-21 的物理成因。"""
    assert _read(HOOK_LIVE) == _read(HOOK_TRACKED), (
        ".git/hooks/pre-commit 与 eval/hooks/pre-commit 分叉 —— 在役闸与版本化闸不是同一份，"
        "重装即行为漂移；用 cp eval/hooks/pre-commit .git/hooks/pre-commit 归一")


GM_HOOK_CANDIDATES = (
    os.path.join(os.environ.get("GLOBAL_MEMORY_ROOT", r"<MEMORY_ROOT>"), "scripts", "hooks", "pre-commit"),
)


@pytest.mark.skipif(not os.path.exists(GM_HOOK_CANDIDATES[0]),
                    reason="GM 仓 hook 不在本机（CI/异机最小环境）")
def test_gm_hook_has_no_stale_c_range():
    text = _read(GM_HOOK_CANDIDATES[0])
    assert not STATIC_C_RANGE.search(text), "GM 仓 hook 抄写了 C 项范围（D-21 同族）"
    # 只检**代码行**是否把 verify 输出静音（注释里引述旧 bug 不算），失败必给明细（D-27）
    silenced = [ln.strip() for ln in text.splitlines()
                if "verify_truth_consistency.py" in ln and "/dev/null" in ln
                and not ln.strip().startswith("#")]
    assert not silenced, "GM 仓 hook 吞掉 verify 输出 = 失败无明细: %s" % silenced


def test_worktree_detection_is_conservative():
    """D-45：只有 linked worktree 才允许降级跑判据，且"取不到 git"必须按主树处理。"""
    assert pch.degraded_worktree(".git", ".git") is False
    assert pch.degraded_worktree("X/.git/worktrees/w1", "X/.git") is True
    assert pch.degraded_worktree("", "") is False, "探测失败时宁可跑全量，不许静默降级"
    assert pch.degraded_worktree("X/.git", "") is False


def test_main_repo_is_not_treated_as_worktree():
    assert pch.degraded_worktree() is False, "主工作树被误判为隔离树 ⇒ 每次提交都少跑一半判据"


def test_parse_dirty_porcelain_separates_worktree_from_index():
    """D-46 诊断面的正确性：只看工作树侧脏（含未跟踪），纯暂存面改动不算在途他人活。"""
    text = ("M  eval/staged_only.py\n"
            " M skill_content/automation.json\n"
            "?? reports/new.md\n"
            "MM eval/both.py\n"
            "R  old.md -> new2.md\n"
            "\n")
    dirty = pch.parse_dirty_porcelain(text)
    assert dirty == ["skill_content/automation.json", "reports/new.md", "eval/both.py"], dirty
    assert pch.parse_dirty_porcelain("") == []


# ---- D-118（对标轮十八）：在役 post-commit 与跟踪副本的分叉 ----
# 一手实测：`eval/hooks/post-commit` 里已提交"有界退避重试 + SECONDS=0"（80447e0），
# 但 `.git/hooks/post-commit` 一直是不含该段的老副本（`grep -c SECONDS=0 .git/hooks/post-commit`
# 修复前 = 0）——**推送重试的修复从头到尾没在役过**。钩子不被 git 跟踪 ⇒ 没有任何测试看过它。

HOOK_LIVE_POST = os.path.join(ROOT, ".git", "hooks", "post-commit")
HOOK_TRACKED_POST = os.path.join(EVAL_DIR, "hooks", "post-commit")
TRACKER_MARK = "# BEGIN Qoder AI tracker"


def _norm(path: str) -> str:
    return open(path, "rb").read().decode("utf-8", "replace").replace("\r\n", "\n")


@pytest.mark.skipif(not os.path.exists(HOOK_LIVE_POST),
                    reason="本机无 .git/hooks/post-commit（CI/干净签出没有钩子，D-48 口径）")
def test_live_post_commit_is_tracked_copy_plus_tracker_tail():
    live, tracked = _norm(HOOK_LIVE_POST), _norm(HOOK_TRACKED_POST)
    assert tracked.rstrip("\n") in live, (
        "在役 post-commit 与跟踪副本分叉：装的是别的内容或源更新后没重装。"
        "修复：python scripts/install_hooks.py --install（会先落 .bak-<时间戳>）")
    tail = live.split(tracked.rstrip("\n"), 1)[1] if tracked.rstrip("\n") in live else live
    residue = [ln.strip() for ln in tail.splitlines()
               if ln.strip() and not ln.strip().startswith(("# BEGIN", "# END", "repo_root=",
                                                          "ELECTRON_RUN_AS_NODE=", "export "))]
    assert not residue or (TRACKER_MARK in tail and not residue), (
        "钩子里除跟踪副本与 tracker 段之外还有第三种私货：%s" % residue[:3])


@pytest.mark.skipif(not os.path.exists(HOOK_LIVE_POST),
                    reason="本机无 .git/hooks/post-commit")
def test_push_retry_fix_is_actually_in_service():
    """不是"源里有"就算，而是"在役副本里有"才算 —— D-21/D-23 的钩子版。"""
    live = _norm(HOOK_LIVE_POST)
    for token in ("PUSH_ATTEMPTS", "PUSH_BUDGET_S", "SECONDS=0", "sleep"):
        assert token in live, "在役 post-commit 缺 %s（源里有 ≠ 在役里有）" % token


# ── D-120：派生件新鲜度以 advisory 形态进第 7 闸（报告而不阻断）──


class _Rc:
    def __init__(self, rc):
        self.returncode, self.stdout, self.stderr = rc, "checked\n", ""


def test_freshness_advisory_reports_stale_without_deciding(monkeypatch, capsys):
    hits = [{"source": "a-skill", "artifact": "bge.npy", "lag_s": 300.0},
            {"source": "b-skill", "artifact": "bge.npy", "lag_s": 90.0}]
    pch.freshness_advisory(hits)
    out = capsys.readouterr().out
    assert "新鲜度" in out and "2 个 SKILL.md 比编码件新" in out
    assert "a-skill, b-skill" in out                          # 点名可归因，不只给数
    assert pch.freshness_advisory(hits) == hits             # 返回值只是读数，不是判定


def test_freshness_advisory_is_silent_when_fresh(capsys):
    pch.freshness_advisory([])
    assert "新鲜度" not in capsys.readouterr().out


def test_missing_face_is_unverified_not_fresh(capsys):
    """取不到数不许写成"没问题"——UNVERIFIED 必须出现在报面上。"""
    pch.freshness_advisory(None)
    assert "UNVERIFIED" in capsys.readouterr().out


def test_unimportable_probe_is_unverified_and_never_raises(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "derivative_watch", None)   # import 期即 TypeError
    assert pch.freshness_advisory() is None
    assert "UNVERIFIED" in capsys.readouterr().out


def test_stale_freshness_does_not_flip_gate_verdict(monkeypatch, capsys):
    """advisory 的定义 = 派生件过期也不改本闸判定（要阻断得先量够误报率）。"""
    import types
    monkeypatch.setattr(pch, "_run", lambda cmd, **kw: _Rc(0))
    monkeypatch.setattr(pch, "ROOT", "/非分机路径")
    fake = types.SimpleNamespace(stale_sources=lambda root=None: [
        {"source": "a", "artifact": "b.npy", "lag_s": 1200.0}])
    monkeypatch.setitem(sys.modules, "derivative_watch", fake)
    assert pch.check_derived_indexes() is True
    assert "新鲜度" in capsys.readouterr().out
    monkeypatch.setattr(pch, "_run", lambda cmd, **kw: _Rc(1))
    monkeypatch.setattr(pch, "note_foreign_inflight", lambda tag: None)
    assert pch.check_derived_indexes() is False               # 红只来自 build_indexes 本身


def _stub_push_health(monkeypatch, verdict="pass", msg="与远端同步"):
    import push_health as ph
    monkeypatch.setattr(ph, "ahead_count", lambda *a, **k: 0)
    monkeypatch.setattr(ph, "judge", lambda n: (verdict, msg))
    return ph


def test_gate_16_surfaces_ci_receipts_without_blocking(monkeypatch, capsys):
    """D-121 的接线证据：回执必须出现在每次提交的第 16 闸输出里，而不是只有手工跑命令才看得到。"""
    ph = _stub_push_health(monkeypatch)
    monkeypatch.setattr(ph, "ci_state_health",
                        lambda *a, **k: ("warn", "BILLING：账单被卡 | CI-only 回执 0/5，PENDING=historical"))
    assert pch.check_push_health() is True
    out = capsys.readouterr().out
    assert "CI 回执（advisory）warn" in out and "PENDING=historical" in out


def test_gate_16_receipt_probe_failure_never_changes_verdict(monkeypatch, capsys):
    ph = _stub_push_health(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("状态文件被他人删了")

    monkeypatch.setattr(ph, "ci_state_health", boom)
    assert pch.check_push_health() is True
    assert "UNVERIFIED" in capsys.readouterr().out


def test_gate_16_still_blocks_on_ahead_fail(monkeypatch):
    """反向对照：advisory 只影响回执那一行，ahead≥3 的 fail 判定不得被顺手放宽。"""
    _stub_push_health(monkeypatch, verdict="fail", msg="本地领先 5 个提交")
    import push_health as ph
    monkeypatch.setattr(ph, "ci_state_health", lambda *a, **k: ("pass", "无关"))
    assert pch.check_push_health() is False
