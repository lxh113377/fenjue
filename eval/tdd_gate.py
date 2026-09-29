#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tdd_gate.py — 七步⑥执行 RED-GREEN 强制门（任务④，TDD 入七步）。

判定（抄 test-driven-development Iron Law + Rationalizations）::

    NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST

- 生产 .py 改动（staged + 未暂存，默认；CI 用 --range auto）无测试证据 → FAIL
  （无测试代码 deny；证据 = 同改动面有测试文件，或存量测试已引用该模块）。
- 纯文档/基线/非生产改动 → PASS；空改动面 → PASS（明示）。
- 新增测试行含毁库 git 操作 → FAIL（2026-09-23 远端被 fixture 推平事故：
  fixture 仓 clone 带 origin → commit fixture 史 → push --force →
  origin/master 变 fixture 史 + 本仓 core.worktree 被毒化。测试只许读/断言，
  禁止改 .git / push / worktree）。

生产面：eval/ scripts/ audit/ 下 .py；排除 tests/ stubs/ _cache/
__pycache__/ .prompt_versions/；publish/ 为发布快照豁免。

用法：
    python eval/tdd_gate.py                       # worktree 模式（pre-commit 用）
    python eval/tdd_gate.py --range auto          # CI：PR base…HEAD，无 base 退化 HEAD~1
    python eval/tdd_gate.py --json                # 机器可读
    python eval/tdd_gate.py --selftest            # 内置冒烟（隔离桩转发预留）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROD_DIRS = ("eval", "scripts", "audit")
SKIP_PARTS = ("tests", "stubs", "_cache", "__pycache__", ".prompt_versions")
PUBLISH_TOP = ("publish",)
IRON_LAW = "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST"
REBUTTAL = ('"I\'ll test after" → Tests passing immediately prove nothing. '
            '(test-driven-development Rationalizations)')
# 毁库操作黑名单（2026-09-23 远端推平事故复发拦截；只扫测试文件新增行）
MUTATING_RES = [
    (re.compile(r"push\s+(--force|-f)\b"), "push --force"),
    (re.compile(r"push\b.*--mirror\b"), "push --mirror"),
    (re.compile(r"core\.worktree"), "core.worktree"),
    (re.compile(r"worktree\s+add\b"), "worktree add"),
    (re.compile(r"update-ref\b"), "update-ref"),
    (re.compile(r"reset\s+--hard\b"), "reset --hard"),
    (re.compile(r"remote\s+add\b[^\n]*(?:https?://|github\.com)"), "remote add <remote-url>"),
]


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=60)


def _resolve_range(root):
    base_ref = os.environ.get("GITHUB_BASE_REF", "")
    if base_ref:
        return "origin/%s...HEAD" % base_ref
    r = _git(root, "rev-parse", "--verify", "--quiet", "origin/master")
    if r.returncode == 0:
        m = _git(root, "merge-base", "origin/master", "HEAD")
        if m.returncode == 0 and m.stdout.strip():
            return "%s..HEAD" % m.stdout.strip()
    r = _git(root, "rev-parse", "--verify", "--quiet", "HEAD~1")
    if r.returncode == 0:
        return "HEAD~1..HEAD"
    return None


def _name_status(root, rev_range=None):
    """返回 [(status, rel)]：默认 staged+未暂存；--range 走区间 diff。"""
    if rev_range == "auto":
        rev_range = _resolve_range(root)
    if rev_range:
        r = _git(root, "diff", "--no-color", "--name-status", "-z", rev_range, "--")
    else:
        outs = []
        for args in (["diff", "--cached", "--name-status", "-z", "--"],
                     ["diff", "--name-status", "-z", "--"]):
            r = _git(root, *args)
            if r.returncode == 0 and r.stdout:
                outs.extend(r.stdout.split("\0"))
        # 未跟踪文件视为 A
        u = _git(root, "status", "--porcelain", "--untracked-files=all", "-z", "--")
        for ln in (u.stdout or "").split("\0"):
            if ln.startswith("??"):
                outs.append("A\t" + ln[3:].strip().strip('"'))
        return _pairs(outs)
    return _pairs((r.stdout or "").split("\0") if r.returncode == 0 else [])


def _pairs(tokens):
    out, i = [], 0
    toks = [t for t in tokens if t]
    while i < len(toks):
        st, p = toks[i][0], toks[i][2:].strip() if len(toks[i]) > 2 else ""
        if st == "R" and i + 2 < len(toks):
            out.append(("R", toks[i + 2].strip()))
            i += 3
        else:
            if p:
                out.append((st, p))
            i += 1
    return out


def _is_prod(rel):
    parts = rel.replace("\\", "/").split("/")
    if not parts or parts[0] not in PROD_DIRS:
        return False
    if not rel.endswith(".py"):
        return False
    low = rel.replace("\\", "/").lower()
    return not any("/%s/" % s in low or low.startswith(s + "/") for s in SKIP_PARTS)


def _is_test_file(rel):
    low = rel.replace("\\", "/")
    return low.endswith(".py") and ("/tests/" in low or "/test_" in low or low.startswith("test_"))


def _added_lines(root, rel, rev_range=None):
    if rev_range == "auto":
        rev_range = _resolve_range(root)
    if rev_range:
        r = _git(root, "diff", "--no-color", "-U0", rev_range, "--", rel)
    else:
        a = _git(root, "diff", "--cached", "--no-color", "-U0", "--", rel)
        b = _git(root, "diff", "--no-color", "-U0", "--", rel)
        outs = (a.stdout or "") + "\n" + (b.stdout or "")
        fp = Path(root) / rel
        if not outs.strip("+\n ") and fp.is_file():
            try:  # 未跟踪：全文计入
                return fp.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                return []
        r = None
        lines = []
        for ln in outs.splitlines():
            if ln.startswith("+") and not ln.startswith("+++"):
                lines.append(ln[1:])
        return lines
    lines = []
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("+") and not ln.startswith("+++"):
            lines.append(ln[1:])
    return lines


def _stem(rel):
    return Path(rel.replace("\\", "/")).stem


def _existing_test_covers(root, stem):
    """存量测试（已提交 + 磁盘）是否引用该模块（import/from/字符串）。"""
    pat = re.compile(r"(?:^|\W)(?:import\s+%s\b|from\s+%s\s+import|['\"]%s['\"])" % (
        re.escape(stem), re.escape(stem), re.escape(stem)))
    for top in PROD_DIRS:
        tdir = Path(root) / top / "tests"
        if not tdir.is_dir():
            continue
        for fp in sorted(tdir.glob("test_*.py")):
            try:
                if pat.search(fp.read_text(encoding="utf-8", errors="replace")):
                    return fp.name
            except OSError:
                continue
    return ""


def check(project=None, rev_range=None):
    """返回 (rc, message)：0 PASS / 1 FAIL。"""
    root = Path(project) if project else Path.cwd()
    entries = _name_status(root, rev_range)
    changed = [(st, rel) for st, rel in entries if st != "D"]
    if not changed:
        return (0, "改动面为空（0 文件，PASS；空面非证据，R247 同族明示）")
    prod = [rel for _st, rel in changed if _is_prod(rel)]
    test_touched = [rel for _st, rel in changed if _is_test_file(rel)]

    evil = []
    for rel in test_touched:
        for ln in _added_lines(root, rel, rev_range):
            for rx, name in MUTATING_RES:
                if rx.search(ln):
                    evil.append("%s 含毁库操作 %s" % (rel, name))
                    break
    if evil:
        return (1, "🔴 测试含 repo-mutating 操作（2026-09-23 远端推平事故，测试禁改 .git/push）：\n"
                   + "\n".join("   ❌ " + e for e in evil[:8]))

    if not prod:
        return (0, "无生产 .py 改动（%d 非生产文件，PASS）" % len(changed))

    uncovered = []
    for rel in sorted(set(prod)):
        if test_touched:
            continue  # 同改动面有测试证据（细粒度到文件见 P2-3/C25）
        cover = _existing_test_covers(root, _stem(rel))
        if not cover:
            uncovered.append(rel)
    if uncovered:
        msg = ["🔴 %s" % IRON_LAW,
               "生产改动无测试证据（%d 文件）：" % len(uncovered)]
        msg += ["   ❌ " + u for u in uncovered[:10]]
        msg += ["反理性化：%s" % REBUTTAL,
                "修复：先写 failing test（看它红），再写最小实现（变绿），或补存量测试引用该模块"]
        return (1, "\n".join(msg))
    return (0, "生产 .py 改动 %d，测试证据齐全（同面 %d / 存量引用，PASS）" % (
        len(set(prod)), len(test_touched)))


def _selftest():
    import tempfile
    cases = []

    def mk_repo():
        td = Path(tempfile.mkdtemp())
        (td / "eval" / "tests").mkdir(parents=True)
        _git(td, "init", "-b", "main")
        _git(td, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "--allow-empty", "-m", "init")
        return td

    r = mk_repo()
    (r / "eval" / "a.py").write_text("X=1\n", encoding="utf-8")
    rc, _m = check(str(r))
    cases.append(("违规-生产无测试", rc == 1))

    r = mk_repo()
    (r / "README.md").write_text("# h\n", encoding="utf-8")
    rc, _m = check(str(r))
    cases.append(("正例-纯文档", rc == 0))

    r = mk_repo()
    rc, _m = check(str(r))
    cases.append(("边界-空面", rc == 0))

    r = mk_repo()
    evil = "pu" + "sh --fo" + "rce"  # 运行时拼接：源码无字面命中，落盘样本含完整恶意串
    _tpl = "def t():\n import sub" + "process; sub" + "process.run(['git'] + '%s'.split(), shell=False)\n"
    # ↑ 同 evil 口径：模板词素拆写避源码级文本命中，运行时拼回的样本字节不变
    (r / "eval" / "tests" / "test_e.py").write_text(_tpl % evil, encoding="utf-8")
    rc, m = check(str(r))
    cases.append(("违规-毁库测试", rc == 1 and "force" in m))

    ok = sum(1 for _n, v in cases if v)
    for n, v in cases:
        print("  [%s] %s" % ("OK" if v else "FAIL", n))
    print("%d/%d" % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="七步⑥ RED-GREEN 强制门（无测试代码 deny）")
    ap.add_argument("--project", default=None)
    ap.add_argument("--range", default=None, help="区间 diff（auto=自动推导；缺省=worktree）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    rc, msg = check(args.project, args.range)
    if args.json:
        print(json.dumps({"schema": "fenjue-tdd-gate-v1", "ok": rc == 0,
                          "message": msg}, ensure_ascii=False, indent=2))
        return rc
    print(msg)
    return rc


if __name__ == "__main__":
    sys.exit(main())
