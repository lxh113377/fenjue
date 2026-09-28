#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_tdd_gate.py — tdd_gate（⑥执行 RED-GREEN 强制）回归测试。

TDD RED 先行。判定契约（任务④）：
  1. 生产.py 改动（staged+未暂存）无对应测试改动 → FAIL（无测试代码 deny）
  2. 纯文档/基线改动（无生产.py）→ PASS
  3. 生产改动 + 对应测试文件同改 → PASS
  4. 生产改动 + 已存在测试引用该模块（非同改）→ PASS（存量测试覆盖）
  5. 新增测试行含毁库 git 操作（force-push / worktree 毒化类，详见实现内
     MUTATING_RES 注释）→ FAIL（2026-09-23 远端被 fixture 推平事故，R-INCIDENT）
     注：本文件内故意用拼接构造恶意串，防自扫描误报（扫毒器测试惯例）。
  6. 空改动面 → PASS（明示）
"""
import os
import subprocess
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(EVAL_DIR)
if EVAL_DIR not in sys.path:
    sys.path.insert(0, EVAL_DIR)

import tdd_gate as tg  # noqa: E402


def _git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 0, "git %s failed: %s" % (args, r.stderr[-500:])
    return r.stdout


def _repo(tmp_path):
    d = tmp_path / "proj"
    (d / "eval").mkdir(parents=True)
    (d / "eval" / "tests").mkdir(parents=True)
    _git(d, "init", "-b", "main")
    _git(d, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "init")
    return d


def _commit_all(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", msg)


def test_deny_prod_without_test(tmp_path):
    """生产.py 新增/修改无测试同行 → FAIL 并点名文件（含 Iron Law）。"""
    repo = _repo(tmp_path)
    (repo / "eval" / "feat.py").write_text("X = 1\n", encoding="utf-8")
    rc, msg = tg.check(str(repo))
    assert rc == 1, msg[-600:]
    assert "feat.py" in msg
    assert "FAILING TEST FIRST" in msg


def test_docs_only_passes(tmp_path):
    """纯文档改动 → PASS。"""
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("# hi\n", encoding="utf-8")
    rc, msg = tg.check(str(repo))
    assert rc == 0, msg[-600:]


def test_prod_with_cotouched_test_passes(tmp_path):
    """生产 + 对应测试同改 → PASS。"""
    repo = _repo(tmp_path)
    (repo / "eval" / "feat.py").write_text("X = 1\n", encoding="utf-8")
    (repo / "eval" / "tests" / "test_feat.py").write_text("def test_x():\n assert True\n", encoding="utf-8")
    rc, msg = tg.check(str(repo))
    assert rc == 0, msg[-600:]


def test_prod_with_existing_covering_test_passes(tmp_path):
    """生产改动但存量测试已引用该模块 → PASS（存量覆盖，不误拦重构）。"""
    repo = _repo(tmp_path)
    (repo / "eval" / "feat.py").write_text("X = 1\n", encoding="utf-8")
    (repo / "eval" / "tests" / "test_feat.py").write_text("import feat\n", encoding="utf-8")
    _commit_all(repo, "base")
    (repo / "eval" / "feat.py").write_text("X = 2\n", encoding="utf-8")
    rc, msg = tg.check(str(repo))
    assert rc == 0, msg[-600:]


def test_deny_repo_mutating_test(tmp_path):
    """测试含毁库 git 操作 → FAIL（远端推平事故复发拦截）。"""
    repo = _repo(tmp_path)
    evil_op = "push " + "--force"  # 拼接构造：防本文件被自扫描误报
    (repo / "eval" / "tests" / "test_evil.py").write_text(
        "def test_x():\n subprocess.run(['git', '%s'])\n" % evil_op, encoding="utf-8")
    rc, msg = tg.check(str(repo))
    assert rc == 1, msg[-600:]
    assert "force" in msg or "毁库" in msg or "repo-mutating" in msg


def test_empty_changeset_passes_with_note(tmp_path):
    """空改动面 → PASS（明示，非静默）。"""
    repo = _repo(tmp_path)
    rc, msg = tg.check(str(repo))
    assert rc == 0
    assert "0" in msg or "空" in msg or "无" in msg
