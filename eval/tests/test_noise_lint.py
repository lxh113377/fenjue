#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""噪声门禁的目录边界测试（对标轮六 D-43）。

病灶实测：D-39 给 `.git/` 加了个 `push-failure.log`（推送失败留痕），下一次提交就被
`[GATE:noise-fail]` 拦住——判据把 git 内部件当成"散落产物"要求迁去 _trash。
一级扫描早就把 `.git` 写进 PROJECT_CORE，**二级散落检测却没跟上**；一直没暴露，
是因为 .git 下从没出现过"长得像散落件"的新文件。

两头都要锁：`.git/` 内的机制件不得判红（否则推送留痕、钩子备份 .bak 全都没地方放）；
但豁免名单必须小到只有 VCS 内部目录——工作区目录一个都不许顺带放行，否则这条豁免
就成了掏空判据的后门。（"根目录真散落件仍判红"由 `[GATE:noise-*]` 每次提交自证，
本文件不复制那条判据：`scan_root` 裸调用不查 .gitignore，会把已忽略项误报成违规。）
"""

import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # .../eval
REPO_ROOT = os.path.dirname(EVAL_DIR)
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
import noise_lint as nl  # noqa: E402


def _hit(res, needle):
    return [v for v in res["violation"]
            if needle in os.path.normpath(str(v.get("path", "")))
            or needle in str(v.get("name", ""))]


def test_git_internals_are_not_workspace_surface(tmp_path):
    """D-43 主锁：.git 下的留痕文件与钩子备份都不得再判散落。"""
    gitdir = tmp_path / ".git"
    (gitdir / "hooks").mkdir(parents=True)
    (gitdir / "hooks" / "post-commit").write_text("#!/bin/sh\n", encoding="utf-8")
    (gitdir / "push-failure.log").write_text("2026-09-25 rc=128 TLS\n", encoding="utf-8")
    (gitdir / "post-commit.bak-d39").write_text("old\n", encoding="utf-8")
    res = nl.scan_root(str(tmp_path), nl.PROJECT_CORE, quiet=True)
    assert not _hit(res, "push-failure"), "git 内部留痕被判成散落产物（D-43 复发）"
    assert not _hit(res, ".bak-d39"), "钩子版本留档被误伤"


def test_exemption_list_stays_minimal():
    """豁免只准放行 VCS 内部目录：任何工作区目录混进来都等于给噪声门禁开后门。"""
    assert nl.NON_WORKSPACE_DIRS == {".git"}, nl.NON_WORKSPACE_DIRS
    assert ".git" in nl.PROJECT_CORE["dirs"], "一级/二级口径必须一致，否则改一处漏一处"
    for leak in ("eval", "reports", "memory", "scripts", "_temp", "skill"):
        assert leak not in nl.NON_WORKSPACE_DIRS, "%s 不得豁免二级散落检测" % leak
