#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送健康度测试（对标轮六 D-39）。

这一路的失效方式是**沉默**：钩子把 push 的 stdout/stderr 全丢进 /dev/null 并 `|| true`，
所以测试要锁的不是"能不能推上去"（那是网络的事），而是"推不上去时账面会不会说话"。
故重心：领先数判定的边界（0 / 1~2 / ≥3）、无远端不得判红、以及钩子模板里
**不允许再出现**把失败吞掉的写法。
"""

import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)
import push_health as ph  # noqa: E402


def test_boundary_of_the_three_verdicts():
    assert ph.judge(None)[0] == "pass", "无远端/无上游不该拦本地提交"
    assert ph.judge(0)[0] == "pass"
    assert ph.judge(1)[0] == "warn" and ph.judge(2)[0] == "warn"
    assert ph.judge(3)[0] == "fail" and ph.judge(9)[0] == "fail"


def test_fail_message_names_the_action():
    verdict, msg = ph.judge(5)
    assert verdict == "fail" and "git push" in msg, msg


def test_negative_input_does_not_panic():
    assert ph.judge(-1)[0] == "pass", "rev-list 异常值按已同步处理，不制造假红"


def test_hook_template_is_not_silently_swallowing_failures():
    """静态锁：版本化钩子里不得再出现 `push ... || true` 这类吞失败的写法。"""
    path = os.path.join(EVAL_DIR, "hooks", "post-commit")
    src = open(path, encoding="utf-8").read()
    assert "push-failure.log" in src, "钩子必须把失败落盘，否则又是不可见失败"
    for line in src.splitlines():
        if line.strip().startswith("#"):
            continue      # 注释里引用旧写法是文档，不是执行面
        if "git push" in line:
            assert "|| true" not in line and "/dev/null 2>&1" not in line, \
                "推送失败被吞回原样（D-39 复发）：%s" % line


def test_real_repo_reports_something():
    """端到端：对真实仓取一次数，判定必须落在三值之内（判据面对现实有效）。"""
    ahead = ph.ahead_count(EVAL_DIR)
    verdict, msg = ph.judge(ahead)
    assert verdict in ("pass", "warn", "fail")
    assert msg
    assert ahead is None or isinstance(ahead, int)


# ── GM P0-32：钩子必须带**有界**退避重试（实测单次 push 会静默漏推）──────────
# 负对照夹具 = 改造前的真实版本化钩子（`git show HEAD:eval/hooks/post-commit` 的执行段），
# 用它证明判据不是恒真：把旧写法拉回来必须判红。
_PRE_P032_HOOK = """#!/bin/sh
GITDIR=$(git rev-parse --git-dir)
OUT=$(git push --quiet origin HEAD 2>&1)
RC=$?
if [ $RC -ne 0 ]; then
  printf '%s rc=%s %s\\n' "$(date -Iseconds)" "$RC" "$OUT" >> "$GITDIR/push-failure.log"
fi
exit 0
"""


def test_hook_template_has_bounded_backoff_retry():
    """正对照：真实版本化钩子必须过静态审（失败可见 + 重试 + 退避 + 总时长上限）。"""
    path = os.path.join(EVAL_DIR, "hooks", "post-commit")
    verdict, detail = ph.hook_health(path)
    assert verdict == "pass", detail


def test_retry_judge_is_not_vacuous():
    """负对照：改造前的单次 push 钩子必须判红，否则本判据等于没装。"""
    bad = ph.hook_static_problems(_PRE_P032_HOOK)
    assert any("PUSH_ATTEMPTS" in b for b in bad), "旧写法拉回来却判过 = 恒真判据：%s" % bad


def test_retry_without_budget_is_rejected():
    """负对照：只有次数没有总时长 = 会把 git commit 挂死在钩子里，同样判红。"""
    src = _PRE_P032_HOOK.replace(
        "OUT=$(git push --quiet origin HEAD 2>&1)",
        "PUSH_ATTEMPTS=5\nattempt=1\nwhile : ; do\n"
        "  OUT=$(git push --quiet origin HEAD 2>&1)\n  RC=$?\n"
        "  [ $attempt -ge $PUSH_ATTEMPTS ] && break\n  sleep $((attempt * 2))\n"
        "  attempt=$((attempt + 1))\ndone")
    bad = ph.hook_static_problems(src)
    assert any("PUSH_BUDGET_S" in b for b in bad), "无总时长上限未被拦：%s" % bad


def test_budget_gate_cannot_be_poisoned_by_inherited_seconds():
    """负对照（03:13 实发事故形态）：有重试、有预算，但 SECONDS 未归零且闸门无最小尝试数
    ⇒ 必须判红。真实事故记录：`push-failure.log ... rc=1 attempts=1`（只试一次就退出）。"""
    src = open(os.path.join(EVAL_DIR, "hooks", "post-commit"), encoding="utf-8").read()
    poisoned = src.replace("SECONDS=0\n", "").replace("[ $attempt -ge 2 ]", "1 -eq 1")
    assert poisoned != src, "夹具未能在真实钩子上构造事故形态，先核对模板"
    bad = ph.hook_static_problems(poisoned)
    assert any("SECONDS" in b for b in bad), bad
    assert any("最小尝试数" in b for b in bad), bad


def test_missing_hook_file_fails_loudly():
    """R240：文档写了 ≠ 磁盘有。钩子文件缺失必须 fail 而不是 pass/skip。"""
    verdict, detail = ph.hook_health(os.path.join(EVAL_DIR, "hooks", "no-such-hook"))
    assert verdict == "fail" and "缺失" in detail, detail


def test_swallowing_push_still_caught_after_refactor():
    """旧 D-39 判据在重试改造后依然生效（`|| true` 混进循环体也要被抓）。"""
    src = open(os.path.join(EVAL_DIR, "hooks", "post-commit"), encoding="utf-8").read() \
        + "\ngit push origin HEAD >/dev/null 2>&1 || true\n"
    bad = ph.hook_static_problems(src)
    assert any("D-39" in b for b in bad), "吞失败的写法混进重试版后未被拦：%s" % bad

