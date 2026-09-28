#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""push_health.py — 本地领先远端的量法（对标轮六 D-39）。

病灶（实测）：post-commit 自动推送写的是 `git push ... >/dev/null 2>&1 || true`，
失败**结构上不可见**。今晚 GM 仓就出现过一次：提交落地、钩子推送撞上他人并发推送失败，
本地领先 1 个提交而没有任何提示——本仓全部"破坏性操作有 Git 兜底"的前提，前提正是
**远端真有一份**。所以把"领先几个"变成每次提交都量的数，并在 pre-commit 显式暴露。

判定（纯函数，便于桩与测试）：
  无上游 / 无远端            -> pass（不是所有仓都托管，缺远端不该拦本地提交）
  ahead == 0                 -> pass
  1 <= ahead < FAIL_AHEAD    -> warn（多半是上一次推送撞车或临时断网，提示去 push）
  ahead >= FAIL_AHEAD        -> fail（连续 N 个提交都没落远端 = 备份链已断，禁止继续堆）
"""

from __future__ import annotations

import os
import re
import subprocess

FAIL_AHEAD = 3          # 领先这么多还没推上去，就认定备份链断了
MIN_PUSH_ATTEMPTS = 3   # 低于此重试次数不算"有界退避"（实测 5 败 1 成，3 是可用下限）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_git(args, cwd):
    try:
        r = subprocess.run(["git", "-C", cwd] + args, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return (r.stdout or b"").decode("utf-8", "replace").strip()


def ahead_count(cwd: str = ROOT):
    """本地领先上游的提交数；无远端/无上游返回 None（判 pass，不判红）。"""
    if run_git(["remote", "get-url", "origin"], cwd) is None:
        return None
    upstream = run_git(["rev-parse", "--abbrev-ref", "@{u}"], cwd)
    if not upstream:
        return None
    n = run_git(["rev-list", "--count", "@{u}..HEAD"], cwd)
    return int(n) if n is not None and n.isdigit() else None


def judge(ahead, fail_ahead: int = FAIL_AHEAD):
    """返回 (verdict, message)。verdict ∈ pass/warn/fail。"""
    if ahead is None:
        return "pass", "无远端或无上游，不判推送健康度"
    if ahead <= 0:
        return "pass", "与远端同步"
    if ahead < fail_ahead:
        return "warn", "本地领先远端 %d 个提交（自动推送可能失败）：git push" % ahead
    return "fail", ("本地领先远端 %d 个提交仍未落远端 ⇒ 备份链已断（"
                    "本仓「破坏性操作有 Git 兜底」的前提失效）：先 git push" % ahead)


def hook_static_problems(src: str) -> list:
    """静态审版本化 post-commit 钩子源码，返回问题清单（空 = 合格）。

    为什么放在模块里而不是只写在 pytest 里：钩子是 `.git/hooks/` 下的**未跟踪文件**，
    换机或重实装后与版本化副本漂移时，只有能被门禁调用的判据才会发现（D-39 的同族复发）。

    两条硬判据：
    1. 推送失败不得被吞（`|| true` / `>/dev/null 2>&1`），且必须落盘 `push-failure.log`；
    2. 必须带**有界**退避重试（GM P0-32）：`PUSH_ATTEMPTS` ≥3、有 `sleep` 退避、
       且有 `PUSH_BUDGET_S` 总时长上限——无上限的重试会把 `git commit` 挂死在钩子里。
    """
    bad = []
    if "push-failure.log" not in src:
        bad.append("失败未落盘（钩子必须写 .git/push-failure.log，否则又是不可见失败）")
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("#") or "git push" not in s:
            continue
        if "|| true" in s:
            bad.append("推送失败被吞回原样（D-39 复发）：%s" % s)
        if "/dev/null 2>&1" in s and "2>&1)" not in s:
            bad.append("推送失败被丢进黑洞（D-39 复发）：%s" % s)
    m = re.search(r"PUSH_ATTEMPTS\s*=\s*(\d+)", src)
    if not m:
        bad.append("无重试次数上限 PUSH_ATTEMPTS（间歇性 TLS 失败会把提交静默留在本地，P0-32）")
    elif int(m.group(1)) < MIN_PUSH_ATTEMPTS:
        bad.append("PUSH_ATTEMPTS=%s < %s，实测 5 败 1 成，太小的上限等于没重试"
                   % (m.group(1), MIN_PUSH_ATTEMPTS))
    if m and "sleep" not in src:
        bad.append("有重试但无退避间隔（无 sleep = 瞬时连打，撞同一个网络抖动窗口）")
    if m and not re.search(r"PUSH_BUDGET_S\s*=\s*(\d+)", src):
        bad.append("有重试但无总时长上限 PUSH_BUDGET_S（post-commit 阻塞用户命令行）")
    # 时长闸门的两个实测坑（03:13 首次上线即 attempts=1 只试一次就退出）：
    # SECONDS 可能被父进程带进来，且闸门不能在第 1 次之前就生效。
    if m and "SECONDS=0" not in src:
        bad.append("时长闸门未把 SECONDS 归零 ⇒ 继承来的值可让重试一开场就被掐死")
    if m and "[ $attempt -ge 2 ]" not in src:
        bad.append("时长闸门未设最小尝试数（实测 attempts=1 事故）：应先试满 2 次再让预算生效")
    return bad


def hook_health(path: str):
    """读版本化钩子并判定，返回 (verdict, detail)。文件缺失 -> fail（R240）。"""
    if not os.path.isfile(path):
        return "fail", "版本化钩子缺失：%s" % path
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
    except OSError as exc:
        return "fail", "钩子不可读：%s（%s）" % (path, exc)
    problems = hook_static_problems(src)
    if problems:
        return "fail", "；".join(problems)
    return "pass", "失败可见 + 有界退避重试俱在"



def ci_state_health(state_path: str | None = None, max_age_h: float = 48.0, now=None):
    """D-113：读 `eval/ci_block_reason.py` 落的状态，判"远端流水线是否还在给我们回执"。

    本函数**不打网络**（每次提交打远端 = 把墙钟与断网风险塞进钩子），只消费已有状态：
      absent   从没跑过分类器          -> unverified（不得当成"CI 正常"）
      stale    状态超过 max_age_h 小时  -> unverified（提示重跑）
      ok       GREEN                    -> pass
      其余分类（BILLING / NO_RECEIPT / REAL_FAILURE / PARTIAL / NO_RUNNER / NO_RUN / UNVERIFIED）
                                      -> warn，并把 reason 原文带出来
    一律**只警告不阻断**：CI 是否可用不是本次提交内容的属性（advisory 门不参与阻断）。
    """
    import datetime as _dt
    import json
    path = state_path or os.path.join(ROOT, "eval", "ci_health_state.json")
    if not os.path.isfile(path):
        return "unverified", "无 CI 状态文件（跑一次 python eval/ci_block_reason.py）"
    try:
        st = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return "unverified", "CI 状态文件不可读：%r" % e
    verdict = st.get("verdict") or "UNVERIFIED"
    reason = (st.get("reason") or "")[:150]
    ts = st.get("checked_at")
    if now is None:
        # 不传 now 也要算陈旧度：否则"上周的 GREEN"会永远报 pass，
        # 而 CI 早已恢复或早已再次卡住都看不出来（假绿的另一种形状）
        now = _dt.datetime.now()
    if ts:
        # 陈旧度判定必须**先于** verdict 分支 —— 旧状态不管是绿是红都只代表过去
        try:
            age = (now - _dt.datetime.fromisoformat(ts)).total_seconds() / 3600.0
        except ValueError:
            age = None
        if age is not None and age > max_age_h:
            return "unverified", ("CI 状态已 %.0f 小时未更新（原判定 %s）⇒ 重跑 "
                                  "python eval/ci_block_reason.py" % (age, verdict))
    if verdict == "GREEN":
        return "pass", _with_receipts("CI 最近一次 run 全绿（%s）" % (ts or "?"), st)
    return "warn", _with_receipts("%s：%s" % (verdict, reason), st)


def _with_receipts(msg: str, st: dict) -> str:
    """D-121：把"CI-only 判据有没有真跑出 steps"挂在同一行报面上（无回执字段时不改文案）。"""
    rec = st.get("receipts")
    if not isinstance(rec, dict) or "want" not in rec:
        return msg
    want = rec.get("want") or 0
    have = rec.get("have") or 0
    if want == have:
        return msg + " | CI-only 回执 %s/%s 全有" % (have, want)
    return msg + " | CI-only 回执 %s/%s，PENDING=%s（等 runner，非本地缺陷）" % (
        have, want, ",".join(rec.get("pending") or []))
def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="推送健康度（D-39）")
    ap.add_argument("--repo", default=ROOT)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check-hook", default=os.path.join(ROOT, "eval", "hooks", "post-commit"),
                    help="静态审版本化钩子（P0-32）；传空串跳过")
    a = ap.parse_args(argv)
    ahead = ahead_count(a.repo)
    verdict, msg = judge(ahead)
    hook_verdict, hook_msg = ("skip", "未要求")
    if a.check_hook:
        hook_verdict, hook_msg = hook_health(a.check_hook)
        if hook_verdict == "fail":
            verdict = "fail"
            msg = msg + " | 钩子不合格：" + hook_msg
    if a.json:
        import json
        print(json.dumps({"ahead": ahead, "verdict": verdict, "message": msg,
                          "hook": hook_verdict, "hook_detail": hook_msg},
                         ensure_ascii=False))
    else:
        print("[push-health] %s: %s" % (verdict, msg))
        print("[push-health] 钩子静态审 %s: %s" % (hook_verdict, hook_msg))
        ci_v, ci_msg = ci_state_health()
        print("[push-health] CI 回执（advisory）%s: %s" % (ci_v, ci_msg))
    return 0 if verdict != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
