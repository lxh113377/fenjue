#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_check_index_refs.py — check_index_refs 路径解析规则回归测试（R196-05 固化）

覆盖：正例（焚诀\\ 前缀 / lessons / meta 子目录）/ 搜索式引用跳过 / 缺失捕获 /
绝对路径 / 目录引用 / 默认目标真实检查。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest  # noqa: E402

# R209-3: 目标解析树在本机 <MEMORY_ROOT> / <SKILLS_ROOT>（junction 权威源），
# CI checkout 无此环境 → 整组跳过（本地照跑不衰减）。
pytestmark = pytest.mark.skipif(
    not (os.path.isdir(r"<MEMORY_ROOT>") and os.path.isdir(r"<SKILLS_ROOT>")),
    reason="依赖本机 global_memory/global_skills 真实环境（CI 跳过）")

import pytest  # noqa: E402

# R209-3: 目标解析树在本机 <MEMORY_ROOT> / <SKILLS_ROOT>（junction 权威源），
# CI checkout 无此环境 → 整组跳过（本地照跑不衰减）。
pytestmark = pytest.mark.skipif(
    not (os.path.isdir(r"<MEMORY_ROOT>") and os.path.isdir(r"<SKILLS_ROOT>")),
    reason="依赖本机 global_memory/global_skills 真实环境（CI 跳过）")

import check_index_refs as cir  # noqa: E402


def test_norm():
    assert cir._norm(r"D:\a\b") == "D:/a/b"
    assert cir._norm("D:/a/b") == "D:/a/b"


def test_is_path_ref():
    # 明确路径（.md 后缀）→ True
    assert cir._is_path_ref("meta/foo.md")
    assert cir._is_path_ref(r"焚诀\eval\bge_onnx_engine.py")
    # 搜索式引用 → False
    assert not cir._is_path_ref("lessons.partN 搜 BGE|ONNX")
    assert not cir._is_path_ref("partN")
    assert not cir._is_path_ref("TOP3")
    # glob 通配符 → False
    assert not cir._is_path_ref("lessons-p1-*.md")
    # 命令示例 → False
    assert not cir._is_path_ref('rg -l -i "<kw>" <MEMORY_ROOT>\\lessons')
    # 纯关键词（无反引号路径特征）→ False
    assert not cir._is_path_ref("http://x.com")
    assert not cir._is_path_ref("skills/")  # 目录引用带后缀才校验


def test_resolve_fenjue_prefix():
    # 「焚诀\」前缀 → 项目根（候选含项目绝对路径，不含「焚诀\」前缀本身）
    cands = cir.resolve_candidates(r"焚诀\eval\bge_onnx_engine.py")
    assert len(cands) == 1
    assert "workspace" in cands[0], f"应解析到项目根: {cands[0]}"
    assert not cands[0].startswith("焚诀/"), "不应保留焚诀前缀"
    assert os.path.exists(cands[0]), "bge_onnx_engine.py 应存在"


def test_resolve_lessons_subdir():
    # lessons 相对引用 → lessons/ 子目录候选根命中
    cands = cir.resolve_candidates("lessons-p0.md")
    assert any("lessons" in c for c in cands)
    assert any(os.path.exists(c) for c in cands), "lessons-p0.md 应存在"


def test_resolve_meta_subdir():
    # meta 相对引用 → meta/ 候选根命中
    cands = cir.resolve_candidates("VERSION_LOCK.part17.md")
    assert any("meta" in c for c in cands)
    assert any(os.path.exists(c) for c in cands), "VERSION_LOCK.part17.md 应存在"


def test_resolve_abs():
    cands = cir.resolve_candidates(r"D:\trae\user_profile.md")
    assert len(cands) == 1 and os.path.exists(cands[0])


def test_extract_refs_dedup():
    content = "`a.md` `a.md` `b.md`"
    refs = cir.extract_refs(content)
    assert refs == ["a.md", "b.md"]


def test_check_file_missing_captured(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("`不存在的文件xyz.md`\n", encoding="utf-8")
    r = cir.check_file(f)
    assert r["checked"] == 1
    assert r["missing"] == ["不存在的文件xyz.md"]


def test_check_file_search_ref_skipped(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("`lessons.partN` 搜 `BGE|ONNX`\n", encoding="utf-8")
    r = cir.check_file(f)
    assert r["checked"] == 0, "搜索式引用应跳过"


def test_default_targets_all_pass():
    """默认主索引真实检查：49 个路径引用全部可循（2026-08-16 基线）。"""
    for t in cir.DEFAULT_TARGETS:
        assert t.exists(), f"默认目标缺失: {t}"
        r = cir.check_file(t)
        assert not r["missing"], f"{t.name} 缺失: {r['missing']}"


def test_cli_json():
    """CLI --json 输出可解析且 all_pass。"""
    import json
    import subprocess
    script = os.path.join(os.path.dirname(cir.__file__), "check_index_refs.py")
    r = subprocess.run([sys.executable, script, "--json"],
                       capture_output=True, text=True, encoding="utf-8",
                       cwd=os.path.dirname(os.path.dirname(script)))
    data = json.loads(r.stdout)
    assert data["schema"] == "fenjue-check-index-refs-v1"
    assert data["all_pass"] is True
    assert r.returncode == 0
