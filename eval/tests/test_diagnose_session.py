#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_diagnose_session.py — diagnose_session（会话自诊）回归测试。

判定契约（任务⑥：抄 diagnosing-superpowers 行级证据 + 打包 bundle）：
  1. 按 session-id 定位记忆日志 footer 区（begin/end），找不到 → exit 2 并列候选
  2. 每条 finding 必带 path:line 引用（无引用无结论）
  3. 维度至少覆盖：stumbles（FAIL/报错）、repeated-work（重复命令）、skills（调用清单）
  4. --bundle 产出 zip（含报告 + 引用原文），缺报告即 FAIL
  5. 只读：不修改任何会话文件
"""
import os
import re
import sys
import zipfile

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if EVAL_DIR not in sys.path:
    sys.path.insert(0, EVAL_DIR)

import diagnose_session as dg  # noqa: E402


def _mem(root, name, body):
    p = os.path.join(root, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return p


def _tree(tmp_path):
    mem = os.path.join(tmp_path, "memory")
    wb = os.path.join(tmp_path, ".workbuddy", "memory")
    os.makedirs(mem)
    os.makedirs(wb)
    body = ("# log\n\n## work\n- 跑 pytest 30/30 PASS\n"
            "<!-- footer:begin session=sess_AAA ts=2026-09-23T00:00:00+08:00 -->\n"
            "[skill清单] 本轮调用=2 个 (A-memory-start, testing)\n"
            "[升级建议] 无命中\n"
            "<!-- footer:end -->\n\n"
            "## failcase\n- 跑 pytest 28/30 FAIL 两处报错\n"
            "<!-- footer:begin session=sess_BBB ts=2026-09-23T01:00:00+08:00 -->\n"
            "[skill清单] 本轮调用=1 个 (testing)\n"
            "<!-- footer:end -->\n")
    _mem(mem, "2026-09-23.md", body)
    _mem(wb, "2026-09-23.md", "## other\n- 无关\n")
    return tmp_path


def test_locate_session(tmp_path):
    """按 id 定位到 footer 区并返回 path:line。"""
    root = str(_tree(str(tmp_path)))
    secs = dg.locate(root, "sess_AAA")
    assert len(secs) == 1
    assert secs[0]["session"] == "sess_AAA"
    assert secs[0]["path"].endswith("2026-09-23.md") and secs[0]["line"] >= 1


def test_missing_session_lists_candidates(tmp_path):
    """不存在的 id → exit 2 路径：locate 返回空，candidates 列出已有 id。"""
    root = str(_tree(str(tmp_path)))
    assert dg.locate(root, "sess_NOPE") == []
    cands = dg.list_candidates(root)
    assert "sess_AAA" in cands and "sess_BBB" in cands


def test_findings_cite_path_line(tmp_path):
    """每条 finding 必带 path:line（ diagnosing-superpowers 硬规则）。"""
    root = str(_tree(str(tmp_path)))
    rep = dg.diagnose(root, "sess_BBB")
    assert rep["findings"], "sess_BBB 有 FAIL 行，必须有发现"
    for f in rep["findings"]:
        assert re.match(r".+:\d+", f["cite"]), "finding 缺 path:line: %s" % f


def test_dimensions_present(tmp_path):
    """维度覆盖 stumbles/skills（sess_AAA 有 skill 清单 + PASS）。"""
    root = str(_tree(str(tmp_path)))
    rep = dg.diagnose(root, "sess_AAA")
    dims = {f["dim"] for f in rep["findings"]}
    assert "skills" in dims, dims


def test_bundle_contains_report_and_evidence(tmp_path):
    """--bundle 产出 zip（含报告 + 引用原文），只读不改源文件。"""
    root = str(_tree(str(tmp_path)))
    before = {p: os.path.getmtime(os.path.join(dp, p))
              for dp, _dn, fn in os.walk(root) for p in fn}
    out = os.path.join(str(tmp_path), "out.zip")
    rc = dg.bundle(root, "sess_AAA", out)
    assert rc == 0 and zipfile.is_zipfile(out)
    names = zipfile.ZipFile(out).namelist()
    assert any(n.endswith(".md") for n in names), names
    after = {p: os.path.getmtime(os.path.join(dp, p))
             for dp, _dn, fn in os.walk(root) for p in fn if not p.endswith(".zip")}
    assert before == after, "bundle 必须只读，不得改动会话文件"
