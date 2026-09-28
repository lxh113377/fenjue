# -*- coding: utf-8 -*-
"""归因锁 + run_gate 全文落盘的隔离桩（对标轮十五 D-81）。

含一条真子进程集成用例：闸门失败时必须能指到写了自己输出的文件 —— 这就是"FAILED 被 tail
窗口截掉"那一类失效的反例（不加这条，锁只能测到自己骗自己）。
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'eval'))
import attribution_lock as a  # noqa: E402

RUN_GATE = os.path.join(REPO, 'scripts', 'run_gate.py')


def _rec(slug, status, log=None, extra=None):
    r = {"slug": slug, "status": status, "exit_code": 0 if status == "pass" else 1}
    if log is not None:
        r["log"] = log
    r.update(extra or {})
    return (slug, r, None)


def test_fail_record_without_log_is_flagged():
    res = a.judge([_rec("pytest", "fail")])
    assert res["verdict"] == "FAIL" and any("无 log 字段" in v for v in res["violations"])


def test_fail_record_with_missing_file_is_flagged(tmp_path):
    gone = str(tmp_path / "gone.log")
    res = a.judge([_rec("truth", "fail", gone)])
    assert res["verdict"] == "FAIL" and any("log 不存在" in v for v in res["violations"])


def test_pass_records_and_loggable_failures_pass(tmp_path):
    good = tmp_path / "pytest.log"
    good.write_text("FAILED eval/tests/x.py::t\n", encoding="utf-8")
    res = a.judge([_rec("pytest", "fail", str(good)), _rec("secrets", "pass", "")])
    assert res["verdict"] == "PASS"
    assert res["failed_gates"] == 1 and res["checked"] == 2


def test_empty_face_is_not_a_green(tmp_path):
    """A2：没有任何记录 = 闸门没落盘，绝不等于全绿（R247 同族）。"""
    assert a.judge([])["verdict"] == "FAIL"
    assert a.main(["--results-dir", str(tmp_path / "nope")]) == 1


def test_unparsable_record_is_a_violation():
    res = a.judge([("broken", None, "Expecting value")])
    assert res["verdict"] == "FAIL" and any("记录不可解析" in v for v in res["violations"])


@pytest.mark.parametrize("code", [0, 7])
def test_run_gate_writes_full_output_and_points_to_it(tmp_path, code):
    """真跑 run_gate：PASS 与 FAIL 两种都要留下可读全文，且 json 里 log 指向它。

    路径一律换成 `/`（D-82：`run_gate` 用 POSIX 语义 `shlex.split`，Windows 反斜杠会被当转义
    吃掉，本机任何含 `C:\\...` 的闸命令都跑不动 —— 该缺陷由本用例第一版撞出，另行处置）。
    """
    script = tmp_path / "child.py"
    script.write_text(f"import sys\nprint('gate-child-out' if {code} == 0 "
                      f"else 'FAILED something-specific')\nsys.exit({code})\n", encoding="utf-8")
    exe = sys.executable.replace(os.sep, "/")
    out = subprocess.run(
        [sys.executable, RUN_GATE, "selftest", f"{exe} {str(script).replace(os.sep, '/')}",
         "--results-dir", str(tmp_path).replace(os.sep, "/")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO)
    assert out.returncode == code, out.stdout + out.stderr
    rec = json.loads((tmp_path / "selftest.json").read_text(encoding="utf-8"))
    assert rec["status"] == ("pass" if code == 0 else "fail")
    assert os.path.isfile(rec["log"]), "闸门失败却没有可指到的全文 = D-81 复发"
    body = open(rec["log"], encoding="utf-8").read()
    needle = "gate-child-out" if code == 0 else "FAILED something-specific"
    assert needle in body and needle in out.stdout, "落盘不得替代实时可见"
