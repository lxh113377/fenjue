# -*- coding: utf-8 -*-
"""part_size_lock 隔离桩（对标轮十一 D-64 / D-69）——含中文路径夹具，锁死"普查漏报"这一类。"""
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'eval'))

import part_size_lock as p  # noqa: E402


def _mk(full, size):
    f = __import__("pathlib").Path(full)
    f.parent.mkdir(parents=True, exist_ok=True)
    body = ("x" * 20 + "\n")
    f.write_text(body * max(1, size // len(body)), encoding="utf-8")
    return f


@pytest.fixture
def git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True,
                   capture_output=True)
    return tmp_path


def test_nonascii_part_files_are_not_missed(git_repo):
    """D-69：中文命名的分卷件必须被数到（默认 quotepath 会把它们从普查里整批吞掉）。"""
    _mk(git_repo / "reports" / "对标第一卷_度量.md.part1.md", 5000)
    _mk(git_repo / "reports" / "ascii_name.part1.md", 5000)
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    names = p.list_parts(str(git_repo))
    assert any("对标第一卷_度量" in n for n in names), names
    sizes = p.scan(str(git_repo))
    assert len([n for n, v in sizes.items() if v > 4096]) == 2


def test_count_ratchet_and_single_file_growth():
    sizes = {"a.part1.md": 5000, "b.part1.md": 100}
    base = {"over": {"a.part1.md": 5000}}
    assert p.judge(sizes, 4096, base)["verdict"] == "PASS"
    v = p.judge({"a.part1.md": 6000, "b.part1.md": 100}, 4096, base)["violations"]
    assert any(x["kind"] == "size" for x in v), "登记件变胖必须红（防总数不变、内容变胖）"
    v2 = p.judge({"a.part1.md": 5000, "b.part1.md": 5000}, 4096, base)["violations"]
    assert any(x["kind"] == "count" for x in v2), "新增超限件必须红"


def test_shrinking_debt_is_allowed():
    base = {"over": {"a.part1.md": 5000, "b.part1.md": 5000}}
    res = p.judge({"a.part1.md": 4000, "b.part1.md": 5000}, 4096, base)
    assert res["verdict"] == "PASS" and res["oversize"] == 1, "只降不升：还债应当放行"


def test_empty_face_and_missing_baseline_fast_fail():
    r0 = p.judge({}, 4096, {"over": {}})
    assert r0["verdict"] == "FAIL-FAST" and "R247" in r0["reason"]
    r1 = p.judge({"a.part1.md": 5000}, 4096, None)
    assert r1["verdict"] == "FAIL-FAST" and "--update-baseline" in r1["reason"]


def test_limit_comes_from_truth_constants_not_bare_number():
    assert p.limit_bytes() == 4096


def test_cli_exit_codes(tmp_path, monkeypatch):
    _mk(tmp_path / "docs" / "x.part1.md", 5000)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setattr(p, "ROOT", str(tmp_path))
    monkeypatch.setattr(p, "BASELINE", str(tmp_path / "bl.json"))
    assert p.main([]) == 2, "无基线不得判绿"
    assert p.main(["--update-baseline"]) == 0
    assert p.main([]) == 0
