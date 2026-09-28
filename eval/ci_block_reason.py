#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_block_reason.py —— CI 跑不起来时，先问「为什么没跑」而不是猜环境（对标轮十八 D-113）。

一手实测（本轮定案，2026-09-25 21:5x）：本仓自 06:57:56Z 起连红 20+ 次、job `steps=0` 且
`runner_name` 空。我前三轮的归因分别是「没拿到 runner」「配额耗尽」「环境问题」——**全错**。
真正的原因一直可从 API 读到，只是没人去读它：

    gh api repos/<owner>/<repo>/actions/runs/<run_id>/jobs  → 取 jobs[0].id
    gh api repos/<owner>/<repo>/check-runs/<job_id>/annotations

> "The job was not started because recent account payments have failed or your spending limit
> needs to be increased. Please check the 'Billing & plans' section in your settings"

也就是说：**账单/支出上限**（账号级、人在设置页处理，Agent 不该也无法代办）。
这类事实过去只能靠人肉想起来查，所以本锁把它做成一条命令 + 一个可被消费的 JSON 状态。

口径与边界：
  - 只读、只打远端 API；`gh` 不在 / 网络不通 / 无权限 ⇒ `UNVERIFIED`，退出码仍为 0
    （看守默认=报告，绝不变成拦任务的闸门；也绝不因取不到数就判"CI 是好的"）。
  - 分类靠 annotations 文案与 `steps` 长度两个证据面，不靠 run 的墙钟（墙钟会低估，见 GM 记忆）。
  - 结果落 `eval/ci_health_state.json` 供 daily_doctor / 报告读取（离线可消费，不再重复打网络）。

用法：
    python eval/ci_block_reason.py [--json] [--runs N] [--selftest]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVAL_DIR)
STATE = os.path.join(EVAL_DIR, "ci_health_state.json")
BILLING_RE = re.compile(r"payment|spending limit|Billing", re.I)
NO_RUNNER_RE = re.compile(r"no (?:runner|labels)|runner could not be found", re.I)
SELF_HOSTED_RE = re.compile(r"self-hosted", re.I)


def _gh(args, timeout=30):
    """跑 gh api；任何失败返回 None（调用方按 UNVERIFIED 处理，不抛)。"""
    if shutil.which("gh") is None:
        return None
    try:
        r = subprocess.run(["gh", "api", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, cwd=ROOT)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def repo_slug():
    """仓 slug 从 remote URL 推，不写死（写死就又造了一个"换机即坏"的判据）。"""
    try:
        out = subprocess.run(["git", "-C", ROOT, "remote", "get-url", "origin"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    url = (out.stdout or "").strip() if out.returncode == 0 else ""
    m = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def classify(jobs, annotations) -> tuple:
    """纯函数：给定 jobs 与 annotations 文本列表，给出 (verdict, reason)。"""
    if not jobs:
        return "NO_RUN", "该 run 没有 job 记录（可能刚入队或已被清理）"
    steps0 = [j for j in jobs if not (j.get("steps") or [])]
    text = " ;; ".join(a.get("message", "") for a in (annotations or []))
    if BILLING_RE.search(text):
        return "BILLING", "账单/支出上限被卡（账号设置页处理，Agent 不代办）"
    if NO_RUNNER_RE.search(text):
        return "NO_RUNNER", "没有匹配到可用的 runner（labels/自托管配置）"
    if steps0 and len(steps0) == len(jobs):
        return "NO_RECEIPT", ("全部 job steps=0 且 annotations 无阻塞说明 ⇒ "
                             '外部态未证；不可据此判 CI 正常')
    if steps0:
        return "PARTIAL", "%d/%d 个 job 没拿到 runner" % (len(steps0), len(jobs))
    failed = [j for j in jobs if j.get("conclusion") not in ("success", None)]
    if failed:
        return "REAL_FAILURE", "%d 个 job 真跑了并判红（看各 job log，不看 conclusion 字符串）" % len(failed)
    return "GREEN", "job 全部拿到 runner 且通过"


def probe(runs=3):
    slug = repo_slug()
    if not slug:
        return {"verdict": "UNVERIFIED", "reason": "origin remote 解析不到 owner/repo",
                "run": None, "jobs": 0}
    recent = _gh(["repos/%s/actions/runs" % slug, "--jq",
                  "[.[].workflow_runs[]|{id,head_sha,conclusion,created_at}][:1]"]) or []
    if not recent:
        # 不同 gh 版本的返回形状差异：退化成整包再截
        raw = _gh(["repos/%s/actions/runs?per_page=%d" % (slug, max(1, runs))]) or {}
        recent = (raw.get("workflow_runs") or [])[:1]
    if not recent:
        return {"verdict": "UNVERIFIED", "reason": "列不出最近 run（权限/网络）",
                "run": None, "jobs": 0}
    run = recent[0]
    jobs_data = _gh(["repos/%s/actions/runs/%s/jobs" % (slug, run["id"])]) or {}
    jobs = jobs_data.get("jobs") or []
    annotations = []
    if jobs:
        annotations = _gh(["repos/%s/check-runs/%s/annotations" % (slug, jobs[0].get("id"))]) or []
    verdict, reason = classify(jobs, annotations)
    return {"verdict": verdict, "reason": reason, "run": run, "jobs": len(jobs),
            "checked_at": datetime.datetime.now().isoformat(timespec="seconds")}


RUN_KEYS = ("id", "conclusion", "created_at", "head_sha", "display_title")

# 只在 CI 里跑、本地第 18 闸没有镜像的判据（D-121：account 计费一卡，这 5 条就静默没有回执）。
# 写死清单会被改名悄悄绕过 ⇒ 由 test_ci_block_reason 钉住"每个 slug 必须仍出现在 ci.yml 的 --expect 名单里"。
CI_ONLY_SLUGS = ("adversarial", "attribution", "historical", "negative", "portability-diff")


def step_hit(job_steps, slug):
    """steps 里是否有名字命中该 slug 的步（命中判据 = 步名含 slug，且步真的跑过）。"""
    for st in job_steps or []:
        name = (st.get("name") or "")
        if slug in name.lower().replace("_", "-"):
            return {"seen": True, "step": name, "conclusion": st.get("conclusion"),
                    "number": st.get("number")}
    return {"seen": False}


def scan_receipts(run_jobs, want=CI_ONLY_SLUGS):
    """run_jobs = [(run_id, [job,...]), ...]（新→旧）。纯函数，不碰网络。

    每个 want 取**第一个真跑出 steps 的 run**做回执；全都没 steps（job 没拿到 runner）
    ⇒ pending。这里绝不把"没数据"记成"没通过"或"已通过"：只记 PENDING + 原因。
    """
    got, pending = {}, []
    ordered = sorted(run_jobs or [], key=lambda t: -(t[0] or 0))   # 新→旧，不依赖调用方给的顺序
    for slug in want:
        hit = None
        for run_id, jobs in ordered:
            for job in jobs or []:
                r = step_hit(job.get("steps") or [], slug)
                if r["seen"]:
                    r["run"] = run_id
                    r["job_state"] = job.get("status")
                    hit = r
                    break
            if hit:
                break
        if hit:
            got[slug] = hit
        else:
            pending.append(slug)
    return {"receipts": got, "pending": pending,
            "have": len(got), "want": len(list(want))}


def collect_run_jobs(slug, runs=5):
    """打 API 取最近 runs 的 jobs（含 steps）。取不到 ⇒ []（scan 端会记成全 PENDING）。"""
    out = []
    recent = _gh(["repos/%s/actions/runs?per_page=%d" % (slug, max(1, runs))]) or {}
    for run in (recent.get("workflow_runs") or [])[:max(1, runs)]:
        jobs_data = _gh(["repos/%s/actions/runs/%s/jobs" % (slug, run["id"])]) or {}
        out.append((run["id"], jobs_data.get("jobs") or []))
    return out


def trim(res: dict) -> dict:
    """状态文件只留必要字段：整包 run 对象有 40+ 键（15KB+），每次提交都换 title 会造成无意义漂移。"""
    run = res.get("run") or {}
    out = {k: res.get(k) for k in ("verdict", "reason", "jobs", "checked_at")}
    out["run"] = {k: run.get(k) for k in RUN_KEYS if run}
    if res.get("receipts") is not None:          # D-121：回执读数一起落盘，离线可消费
        out["receipts"] = res["receipts"]
    return out


def verify_receipts(runs: int = 5, path: str = STATE, do_write: bool = True) -> dict:
    """一条命令回答"CI-only 判据到底有没有跑过"：阻塞原因 + 每条的回执，缺的一律记 PENDING。"""
    slug = repo_slug()
    res = probe()
    if not slug:
        res["receipts"] = {"want": list(CI_ONLY_SLUGS), "error": "origin remote 解析不到 owner/repo"}
        res["receipts_pending"] = list(CI_ONLY_SLUGS)
        return res
    scan = scan_receipts(collect_run_jobs(slug, runs))
    res["receipts"] = {"have": scan["have"], "want": scan["want"],
                       "pending": scan["pending"], "by_slug": scan["receipts"]}
    res["receipts_pending"] = scan["pending"]
    if do_write:
        write_state(res, path)
    return res


def write_state(res: dict, path: str = STATE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trim(res), f, ensure_ascii=False, indent=1, sort_keys=True)


def selftest() -> int:
    """判别力自证（没有反例的判据等于没有判据）。"""
    ok = True
    billing = [{"id": 1, "steps": [], "conclusion": "failure"}]
    ann = [{"message": "The job was not started because recent account payments have failed "
                       "or your spending limit needs to be increased."}]
    if classify(billing, ann)[0] != "BILLING":
        ok = False
        print("[selftest] FAIL: 账单类 annotation 没被分类成 BILLING")
    if classify(billing, [])[0] != "NO_RECEIPT":
        ok = False
        print('[selftest] FAIL: steps=0 且无说明被判成可用（外部态不得判正常）')
    if classify([{"id": 1, "steps": [{"conclusion": "failure"}] * 5,
                  "conclusion": "failure"}], [])[0] != "REAL_FAILURE":
        ok = False
        print("[selftest] FAIL: 真跑过的红没被分类成 REAL_FAILURE")
    if classify([{"id": 1, "steps": [{"conclusion": "success"}],
                  "conclusion": "success"}], [])[0] != "GREEN":
        ok = False
        print("[selftest] FAIL: 全绿面被判错")
    if classify([], [])[0] != "NO_RUN":
        ok = False
        print('[selftest] FAIL: 无 job 记录被当成可用状态')
    print("[selftest] %s 5 例（账单 / 无回执 / 真红 / 全绿 / 无 job）"
          % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CI 阻塞原因分类器（advisory，只读）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--verify-receipts", action="store_true",
                    help="额外核对 CI-only 判据有没有 steps>0 的回执（多打几次 API，仍不阻断）")
    ns = ap.parse_args(argv)
    if ns.selftest:
        return selftest()
    res = verify_receipts(ns.runs, ns.state) if ns.verify_receipts else probe(ns.runs)
    try:
        if not ns.verify_receipts:
            write_state(res, ns.state)
    except OSError as e:
        res["state_write_error"] = str(e)
    if ns.json:
        # 回执模式下按 trim() 输出：整包 run 对象 40+ 键，机读面只留必要字段
        print(json.dumps(trim(res) if ns.verify_receipts else res, ensure_ascii=False, indent=1))
    else:
        print("[ci-health] %s: %s" % (res["verdict"], res["reason"]))
        if res.get("run"):
            print("           最近 run=%s %s @ %s" % (
                res["run"].get("id"), res["run"].get("conclusion"),
                res["run"].get("created_at")))
        rec = res.get("receipts")
        if isinstance(rec, dict) and "want" in rec:
            print("           回执 %s/%s：%s" % (
                rec["have"], rec["want"],
                "全有" if not rec["pending"] else "PENDING=" + ",".join(rec["pending"])))
        print("           状态已落 %s（advisory：本命令不参与阻断）" % ns.state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
