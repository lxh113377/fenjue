# -*- coding: utf-8 -*-
"""install_hooks.py 的隔离桩测试（对标轮七 D-50）——全部在 tmp_path 造的小 git 仓里跑。

禁读真实三受管仓（D-40 教训：断言不得依赖本机专有件，否则本地绿/CI 红，或反过来把他人环境
当成判据面）。被测面 = 检查判定 + 安装语义（备份、tracker 段保留、未提交源拒装）。
"""
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, 'scripts'))

import install_hooks as ih  # noqa: E402


def _mini_repo(tmp_path, *, with_hooks=True):
    repo = tmp_path / "repo"
    (repo / "eval" / "hooks").mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / ".git" / "hooks").mkdir()
    src = repo / "eval" / "hooks" / "pre-commit"
    src.write_text("#!/bin/sh\n# 版本化副本 v2\nexit 0\n", encoding="utf-8", newline="\n")
    if with_hooks:
        (repo / ".git" / "hooks" / "pre-commit").write_text(
            "#!/bin/sh\n# 旧版 v1\nexit 0\n", encoding="utf-8", newline="\n")
    return repo


def _patch_repo(monkeypatch, repo, hooks=None):
    hooks = hooks or [("pre-commit", "eval/hooks/pre-commit")]
    monkeypatch.setattr(ih, "REPOS", [(repo.name, str(repo), hooks)])
    monkeypatch.setattr(ih, "HOOKS_PATH_REPOS", [])
    monkeypatch.setattr(ih, "_dirty", lambda root, rel: False)


def test_drift_detected_when_installed_differs(tmp_path, monkeypatch):
    repo = _mini_repo(tmp_path)
    _patch_repo(monkeypatch, repo)
    rows, rc = ih.check(quiet=True)
    assert rc == 1 and rows[0][2] == 'drift'


def test_missing_detected_when_hook_not_installed(tmp_path, monkeypatch):
    repo = _mini_repo(tmp_path, with_hooks=False)
    _patch_repo(monkeypatch, repo)
    rows, rc = ih.check(quiet=True)
    assert rc == 1 and rows[0][2] == 'missing'


def test_install_backs_up_and_verifies_equal(tmp_path, monkeypatch):
    repo = _mini_repo(tmp_path)
    _patch_repo(monkeypatch, repo)
    rows, rc = ih.check(install=True, quiet=True)
    assert rc == 0 and rows[0][2] == 'installed'
    installed = (repo / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert installed == (repo / "eval" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert list((repo / ".git" / "hooks").glob("pre-commit.bak-*")), "旧钩子必须留备份"


def test_install_preserves_host_tracker_segment(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "eval" / "hooks").mkdir(parents=True)
    (repo / ".git" / "hooks").mkdir(parents=True)
    src = repo / "eval" / "hooks" / "pre-commit"
    src.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    target = repo / ".git" / "hooks" / "pre-commit"
    target.write_text("#!/bin/sh\n# BEGIN Qoder AI tracker\nTRACK me\n# END Qoder AI tracker\n",
                      encoding="utf-8", newline="\n")
    _patch_repo(monkeypatch, repo)
    ih.check(install=True, quiet=True)
    body = target.read_text(encoding="utf-8")
    assert "# BEGIN Qoder AI tracker" in body and "TRACK me" in body, "宿主追踪段不得被覆写掉"
    assert body.startswith("#!/bin/sh\nexit 0"), "主体必须是版本化副本内容"


def test_install_refuses_dirty_source(tmp_path, monkeypatch):
    repo = _mini_repo(tmp_path)
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(ih, "_dirty", lambda root, rel: True)
    before = (repo / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    rows, rc = ih.check(install=True, quiet=True)
    assert rc == 1 and rows[0][2] == 'blocked'
    assert (repo / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8") == before, \
        "未提交的中间态绝不进本机钩子"


def test_no_repo_is_env_failure(tmp_path, monkeypatch):
    repo = tmp_path / "notarepo"
    repo.mkdir()
    _patch_repo(monkeypatch, repo)
    rows, rc = ih.check(quiet=True)
    assert rows[0][2] == 'no-repo' and rc == 2


def test_stripped_comparison_ignores_tracker_tail(tmp_path, monkeypatch):
    """tracker 段不同不算漂移（同一台机器装了同一份钩子，宿主追踪段本就各异）。"""
    repo = tmp_path / "repo"
    (repo / "eval" / "hooks").mkdir(parents=True)
    (repo / ".git" / "hooks").mkdir(parents=True)
    body = "#!/bin/sh\nexit 0\n"
    (repo / "eval" / "hooks" / "pre-commit").write_text(body, encoding="utf-8", newline="\n")
    (repo / ".git" / "hooks" / "pre-commit").write_text(
        body + "# BEGIN Qoder AI tracker\nX\n# END Qoder AI tracker\n",
        encoding="utf-8", newline="\n")
    _patch_repo(monkeypatch, repo)
    rows, rc = ih.check(quiet=True)
    assert rc == 0 and rows[0][2] == 'ok'


def test_global_skills_hooks_path_face_reported(tmp_path, monkeypatch):
    """core.hooksPath 口径：配置缺失/副本缺失都必须点名，不得静默 ok。"""
    repo = tmp_path / "gs"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(ih, "REPOS", [])
    monkeypatch.setattr(ih, "HOOKS_PATH_REPOS", [("gs", str(repo), "hooks", "pre-commit")])
    monkeypatch.setattr(ih, "_git", lambda root, *a: subprocess.CompletedProcess(
        a, 1, stdout="", stderr=""))
    rows, rc = ih.check(quiet=True)
    assert rc == 1 and 'core.hooksPath' in rows[0][3]


@pytest.mark.parametrize("argv", (["--check"], ["--doctor"]))
def test_cli_smoke(argv, tmp_path, monkeypatch, capsys):
    repo = _mini_repo(tmp_path, with_hooks=False)
    _patch_repo(monkeypatch, repo)
    assert ih.main(argv) == 1
    assert repo.name in capsys.readouterr().out
