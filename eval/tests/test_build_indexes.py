#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_indexes + C10 单测（R193 阶段2）：dry-run 幂等/原子写/守恒/C10 正反例。"""

import json
import os
import sys

import numpy as np
import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import bge_onnx_engine as _bge_oe  # noqa: E402

_BGE_SNAPSHOT_OK = os.path.isdir(_bge_oe.BAAI_SNAPSHOT)  # R209-3: HF 模型缓存仅本机存在

import build_indexes as bi  # noqa: E402
import verify_truth_consistency as vtc  # noqa: E402


def _mini_state(tmp_path, with_residue=False):
    """构造 3-skill 迷你数据层（1 域两成员 + 1 插件），返回 records。"""
    gs = tmp_path / "global_skills"
    pl = tmp_path / "plugin_skills"
    sc = tmp_path / "skill_content"
    gs.mkdir()
    pl.mkdir()
    sc.mkdir()
    (tmp_path / "eval_out").mkdir()
    # GLOBAL_MEMORY 隔离桩：避免 conserve_check / inject 触碰真实 <MEMORY_ROOT>
    # （生产记忆文件 skill_routing.part1.md 计数污染），并让 mini 注册表(3 skill/2 域)
    # 与桩文件 总计行 自洽，使 conserve_check 可判定通过。
    gm = tmp_path / "gm"
    gm.mkdir()
    (gm / "skill_routing.part1.md").write_text(
        "**总计：3 个 skill / 2 个领域**\n", encoding="utf-8")
    reg = {
        "skills": {
            "alpha": {"domain": "01-x", "version": "1.0"},
            "beta": {"domain": "01-x", "version": "2.0"},
            "gamma": {"domain": "02-y", "version": "3.0"},
        }
    }
    reg_dir = tmp_path / "regdir"
    reg_dir.mkdir()
    reg_file = reg_dir / "unified-skills-index.json"
    reg_file.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    for name in ("alpha", "beta"):
        d = gs / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: 测试技能 {name}\ntriggers:\n  - {name}触发\nversion: 1.0\n---\n正文 {name}\n",
            encoding="utf-8",
        )
    pg = pl / "gamma"
    pg.mkdir()
    (pg / "SKILL.md").write_text(
        "---\nname: gamma\ndescription: 插件测试技能 gamma\ntriggers:\n  - gamma触发\n---\n正文 gamma\n",
        encoding="utf-8",
    )
    monkeypatch_targets = {
        "GLOBAL_SKILLS": str(gs),
        "PLUGIN_SKILLS_DIR": str(pl),
        "SKILL_CONTENT": str(sc),
        "REGISTRY": str(reg_dir),
        "REGISTRY_FILE": str(reg_file),
        "DISK_MANIFEST": str(reg_dir / "disk_manifest.json"),
        "EVAL_DIR": str(tmp_path / "eval_out"),
        "GLOBAL_MEMORY": str(gm),
    }
    return monkeypatch_targets


@pytest.fixture
def mini(tmp_path, monkeypatch):
    if not _BGE_SNAPSHOT_OK:
        pytest.skip("mini fixture 的 C10 链依赖本机 HF BGE 模型缓存（CI 跳过）")
    targets = _mini_state(tmp_path)
    for attr, val in targets.items():
        if hasattr(bi, attr):
            monkeypatch.setattr(bi, attr, val)
    return tmp_path


def test_dry_run_idempotent(mini):
    r1 = bi.collect_skills()
    r2 = bi.collect_skills()
    assert len(r1) == 3
    assert bi.plan_summary(r1) == bi.plan_summary(r2)
    assert [x["name"] for x in r1] == [x["name"] for x in r2]


def test_atomic_writes_leave_no_tmp(mini, tmp_path):
    target = tmp_path / "x.json"
    bi.write_json_atomic(str(target), {"a": 1})
    assert target.exists() and not (tmp_path / "x.json.tmp").exists()

    npy = tmp_path / "x.npy"
    bi.write_npy_atomic(str(npy), np.zeros((2, 4)))
    assert npy.exists() and not (tmp_path / "x.npy.tmp.npy").exists()

    pkl = tmp_path / "x.pkl"
    bi.write_pkl_atomic(str(pkl), {"v": 1})
    assert pkl.exists() and not (tmp_path / "x.pkl.tmp").exists()

    from scipy import sparse
    npz = tmp_path / "x.npz"
    bi.write_npz_atomic(str(npz), sparse.csr_matrix(np.eye(2)))
    assert npz.exists() and not (tmp_path / "x.npz.tmp.npz").exists()


@pytest.mark.skipif(not _BGE_SNAPSHOT_OK,
                    reason="依赖本机 HF BGE 模型缓存（CI 跳过）")
def test_write_all_and_conserve_pass(mini, tmp_path):
    records = bi.collect_skills()
    matrix, vectorizer = bi.build_tfidf([r["body"] for r in records])
    embeddings = np.zeros((3, 512))
    bi._write_all(records, embeddings, matrix, vectorizer)
    assert bi.conserve_check() == []


@pytest.mark.skipif(not _BGE_SNAPSHOT_OK,
                    reason="依赖本机 HF BGE 模型缓存（CI 跳过）")
def test_conserve_detects_residue(mini, tmp_path):
    records = bi.collect_skills()
    matrix, vectorizer = bi.build_tfidf([r["body"] for r in records])
    bi._write_all(records, np.zeros((3, 512)), matrix, vectorizer)
    os.makedirs(str(tmp_path / "eval_out"), exist_ok=True)
    (tmp_path / "eval_out" / "skill_ids.json").write_text("[]", encoding="utf-8")
    assert any("退役残留" in i for i in bi.conserve_check())


@pytest.mark.skipif(not _BGE_SNAPSHOT_OK,
                    reason="依赖本机 HF BGE 模型缓存（CI 跳过）")
def test_conserve_detects_missing_artifact(mini, tmp_path):
    records = bi.collect_skills()
    matrix, vectorizer = bi.build_tfidf([r["body"] for r in records])
    bi._write_all(records, np.zeros((3, 512)), matrix, vectorizer)
    os.remove(os.path.join(bi.SKILL_CONTENT, "skill_ids.json"))
    assert any("skill_ids" in i for i in bi.conserve_check())


# ===== C10 正反例 =====
@pytest.fixture
def c10_mini(tmp_path, monkeypatch):
    if not _BGE_SNAPSHOT_OK:
        pytest.skip("c10 链的 _write_all 依赖本机 HF BGE 模型缓存（CI 跳过）")
    targets = _mini_state(tmp_path)
    for attr, val in targets.items():
        if hasattr(bi, attr):
            monkeypatch.setattr(bi, attr, val)
        if hasattr(vtc, attr):
            monkeypatch.setattr(vtc, attr, val)
    records = bi.collect_skills()
    matrix, vectorizer = bi.build_tfidf([r["body"] for r in records])
    bi._write_all(records, np.zeros((3, 512)), matrix, vectorizer)
    return tmp_path


def test_c10_pass(c10_mini):
    status, detail = vtc.check_c10_three_way_data_layer(False)
    assert status == "PASS"


def test_c10_fail_on_residue(c10_mini, tmp_path):
    (tmp_path / "eval_out" / "skill_ids.json").write_text("[]", encoding="utf-8")
    status, detail = vtc.check_c10_three_way_data_layer(False)
    assert status == "FAIL" and "退役残留" in detail


def test_c10_fail_on_shape_mismatch(c10_mini, tmp_path):
    np.save(str(tmp_path / "eval_out" / "bge_fullbody_embeddings.npy"), np.zeros((2, 512)))
    status, detail = vtc.check_c10_three_way_data_layer(False)
    assert status == "FAIL"


def test_c10_skip_in_ci_mode(c10_mini):
    status, _ = vtc.check_c10_three_way_data_layer(True)
    assert status == "SKIP"
