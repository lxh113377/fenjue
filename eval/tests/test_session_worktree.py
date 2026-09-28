#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会话隔离工作树工具测试（对标轮五 P0-23 的 P1 配套）。

这个脚本的产出是"别人会在别的目录里执行"的命令，所以测试重心不在 git 本身（那是 git 的
责任），而在**它会不会把人带到不该去的地方**：路径穿越、落在仓内污染判据面、以及对
`git worktree list --porcelain` 的解析（解析错就会 rm 错目录）。
"""

import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # .../焚诀/eval
REPO = os.path.dirname(EVAL_DIR)                                           # .../焚诀
sys.path.insert(0, os.path.join(REPO, "scripts"))
import pytest  # noqa: E402
import session_worktree as sw  # noqa: E402


def test_name_must_not_escape_the_isolation_root():
    for bad in ("../evil", "a/b", "", "-lead", "x" * 41, "中文", "a b"):
        with pytest.raises(ValueError):
            sw.target(bad)
    ok = sw.target("r7-metric")
    assert os.path.basename(ok) == "r7-metric"


def test_isolation_dir_lives_outside_the_repo():
    """建在仓内会被噪声门禁与各类实扫面当成产物，也会让 worktree 自我嵌套。"""
    root = os.path.normpath(sw.wt_root())
    repo = os.path.normpath(sw.REPO)
    assert not root.startswith(repo + os.sep), root
    assert os.path.basename(root).endswith(".wt"), root


def test_existing_parses_porcelain_output(monkeypatch):
    sample = (
        "worktree C:/repo/fenjue\n"
        "HEAD abc123\n"
        "branch refs/heads/master\n"
        "\n"
        "worktree C:/repo/fenjue.wt/r7\n"
        "HEAD def456\n"
        "detached\n"
        "\n")

    class R:
        stdout, returncode = sample, 0

    monkeypatch.setattr(sw, "_git", lambda args, cwd=None: R())
    rows = sw.existing("C:/repo/fenjue")
    assert rows["C:/repo/fenjue"] == "master"
    assert rows["C:/repo/fenjue.wt/r7"] == "", "detached 工作树不该带分支名"
    assert len(rows) == 2
