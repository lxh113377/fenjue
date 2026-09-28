# -*- coding: utf-8 -*-
"""claim_count_lock 隔离桩（D-71）——正例/反例都要有，防"永不判红的假锁"。"""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'eval'))
import claim_count_lock as c  # noqa: E402


def _git_or_skip(args, cwd):
    r"""在本机沙箱里跑不动 git 时按「面不可达」降级并点名（D-40 同口径，禁假绿）。

    实测本机 `AppData\Local\Temp\pytest-of-*` 下 `git add -A` 返回 128（safe-delete 保护钩子
    拦截 TEMP 批量写入，R278 同源），而同一序列在 /tmp 与 CI(ubuntu) 均正常 —— 属宿主环境
    限制，不是被测逻辑失败，故 skip 而非 pass。
    """
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"沙箱内 git 不可用（宿主限制，非判据失败）: {r.stderr.strip()[:120]}")
    return r


def _commit_seed(tmp_path):
    (tmp_path / "reports").mkdir(exist_ok=True)
    (tmp_path / "reports" / "seed.md").write_text("# 种子\n老账 12 个不追\n", encoding="utf-8")
    _git_or_skip(["add", "-A"], tmp_path)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"],
                   cwd=tmp_path, check=True, capture_output=True)


def _staged(tmp_path, name, body):
    p = tmp_path / "reports" / name
    p.write_text(body, encoding="utf-8")
    _git_or_skip(["add", "-A"], tmp_path)


def test_bare_claim_is_flagged(tmp_path, monkeypatch):
    _commit_seed(tmp_path)
    _staged(tmp_path, "a.md", "# x\n本轮共 15 道闸全绿\n")
    monkeypatch.setattr(c, "ROOT", str(tmp_path))
    rows = c.added_lines("staged", "HEAD~1")
    bad = c.judge(rows)
    assert len(bad) == 1 and "15 道" in bad[0]["claim"], rows


def test_inline_command_and_proof_refs_pass(tmp_path, monkeypatch):
    _commit_seed(tmp_path)
    _staged(tmp_path, "b.md",
            "# x\n实测 15 道：`git ls-files -z | wc -l`\n"
            "存量 8 卷超限（口径见 eval/part_size_lock.py:12）\n"
            "提交 abc1234 修掉 3 处\n")
    monkeypatch.setattr(c, "ROOT", str(tmp_path))
    assert c.judge(c.added_lines("staged", "HEAD~1")) == []


def test_out_of_face_and_context_lines_not_judged(tmp_path, monkeypatch):
    _commit_seed(tmp_path)
    (tmp_path / "eval").mkdir(exist_ok=True)
    (tmp_path / "eval" / "note.md").write_text("face 外 9 个\n", encoding="utf-8")
    _staged(tmp_path, "c.md", "# x\n上下文行 7 个\n")
    monkeypatch.setattr(c, "ROOT", str(tmp_path))
    rows = c.added_lines("staged", "HEAD~1")
    assert all(not f.startswith("eval/") for f, _n, _t in rows)


def test_chinese_path_is_not_missed(tmp_path, monkeypatch):
    """D-69 同族：中文命名的报告卷不得被 quotepath 转义吞掉。"""
    _commit_seed(tmp_path)
    _staged(tmp_path, "对标第十二轮_度量.md", "# x\n本轮 21 处改动\n")
    monkeypatch.setattr(c, "ROOT", str(tmp_path))
    rows = c.added_lines("staged", "HEAD~1")
    assert any("对标第十二轮" in f for f, _n, _t in rows), rows
    assert len(c.judge(rows)) == 1


def test_unreachable_face_fast_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "ROOT", str(tmp_path))     # 非 git 仓
    assert c.main(["--staged"]) == 2


def test_removed_lines_are_ignored(tmp_path, monkeypatch):
    _commit_seed(tmp_path)
    _staged(tmp_path, "seed.md", "# 种子\n（老账那行被删掉）\n")
    monkeypatch.setattr(c, "ROOT", str(tmp_path))
    assert c.judge(c.added_lines("staged", "HEAD~1")) == []
