#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_check_gate_wiring_face.py — L-2 子集面的正反两例（2026-09-29）。

立它的理由（DEBT_UNWIRED.md L-2）：`check_gate_wiring.py` 在公开面恒红，
红因是「判据量了另一个面」（本机钩子/GM 仓），不是门禁未接入。
修法 = 按面选目标：detect_face() 判定 full/subset，run_checks() 单实现。
本文件钉死三件事：
  ① 真面（本仓干净签出）subset 零失败；
  ② 每个子集项都有专属反例（删副本/掏空 CI 引用/零钩子 ⇒ 恰好该项红，别项不红）；
  ③ full 面逻辑未被子集改造带偏（无 subset 标签泄漏）。
期望一律写成精确等式（sorted(fails)==点名集），不用 `in` 成员判定（②-e）。
"""
import os
import shutil
import sys
import tempfile

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)
import check_gate_wiring as cgw  # noqa: E402

NEED_FILES = [
    os.path.join("eval", "hooks", "pre-commit"),
    os.path.join(".github", "workflows", "ci.yml"),
    os.path.join(".pre-commit-config.yaml"),
    os.path.join("eval", "verify_truth_consistency.py"),
    # W4-subset 还要核对「引用了的脚本在场」，合成树必须与真面同人口
    # （缺件造成的红不是该腿的判定力，②-e）：
    os.path.join("eval", "doc_claim_face.py"),
    os.path.join("eval", "command_face_parity.py"),
    os.path.join("scripts", "ci_workflow_spec_check.py"),
]


def _clone_real_tree():
    """把真面四个文件拷进临时合成树（仓外，不污染受管根）。"""
    tmp = tempfile.mkdtemp(prefix="cgw_face_")
    for rel in NEED_FILES:
        src = os.path.join(cgw.PROJECT_DIR, rel)
        dst = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    return tmp


def _fails(face, root):
    fails, _notes, _skips = cgw.run_checks(face, project_dir=root)
    return sorted(fails)


def test_subset_face_real_tree_zero_failures():
    assert _fails("subset", cgw.PROJECT_DIR) == []


def test_face_detector_both_directions():
    assert cgw.detect_face(gm_root="<MEMORY_ROOT>") == "subset"
    with tempfile.TemporaryDirectory() as tmp:
        assert cgw.detect_face(gm_root=tmp) == "full"
    assert cgw.detect_face() == "subset"  # 本仓 GM 根不可达，当前面即 subset


def test_mutation_missing_hook_copy_names_w1_only():
    root = _clone_real_tree()
    os.remove(os.path.join(root, "eval", "hooks", "pre-commit"))
    fails = _fails("subset", root)
    assert len(fails) == 1 and fails[0].startswith("W1-subset"), fails


def test_mutation_ci_without_gate_refs_names_w4_only():
    root = _clone_real_tree()
    ci = os.path.join(root, ".github", "workflows", "ci.yml")
    with open(ci, "w", encoding="utf-8") as fh:
        fh.write("name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
                 "    steps:\n      - run: echo hello\n")
    fails = _fails("subset", root)
    assert len(fails) == 1 and fails[0].startswith("W4-subset"), fails


def test_mutation_ci_refs_missing_script_names_w4_only():
    root = _clone_real_tree()
    ci = os.path.join(root, ".github", "workflows", "ci.yml")
    with open(ci, "a", encoding="utf-8") as fh:
        fh.write("\n# run: python eval/doc_claim_face.py\n")
    os.remove(os.path.join(root, "eval", "doc_claim_face.py"))
    # 注：删的是仓外合成树里的副本，真仓文件不动
    fails = _fails("subset", root)
    assert len(fails) == 1 and fails[0].startswith("W4-subset"), fails


def test_mutation_zero_hooks_names_w7_only():
    root = _clone_real_tree()
    pc = os.path.join(root, ".pre-commit-config.yaml")
    with open(pc, "w", encoding="utf-8") as fh:
        fh.write("repos: []\n")
    fails = _fails("subset", root)
    assert len(fails) == 1 and fails[0].startswith("W7-subset"), fails


def test_full_face_has_no_subset_labels():
    fails = _fails("full", cgw.PROJECT_DIR)
    assert fails, "本仓无本地钩子，full 面应红（否则自检恒绿）"
    assert all(f.startswith(("W1 ", "W2 ", "W3 ", "W4 ", "W6", "W7 "))
               for f in fails), fails
    assert not any("subset" in f for f in fails), fails
