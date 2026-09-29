#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_reexport_surface_guard.py — L-1 前提的第一半（2026-09-29）。

立它的理由（docs/DEBT_UNWIRED.md L-1）：`ruff --fix` 曾经真删过
`verify_checks/*_layer.py` 分片共用的 import 前言，其中若干名字由
`verify_truth_consistency._CHECK_HOME` 跨片属性代理晚绑定，ruff 看不见
这个读者 ⇒ 删完 4 条用例当场 `AttributeError`，整族回退。
前提原文：「先给该代理补一条『删任一分片的 import 必须变红』的守卫腿，
再逐行 `# noqa: F401`」——本文件即那条腿；noqa 落子见各文件行内。

守卫语义（故意保守，分两层）：
  ① 基线等式：`eval/reexport_surface_baseline.json` 登记每文件「导入但
     词法未用」的名字集合（ruff F401 在本仓的简单形状，现算生成、随仓提交）。
     活算 surface 与基线逐文件精确相等 —— 删任一行 import（autofix/手删）
     surface 变小即红；新增未用 import 变大也红（改基线须是 deliberate 动作）。
     注意：活算 surface 本身抓不住删除（删完自然变小），所以必须对基线。
  ② 属性在位：基线里的每个名字仍是模块属性（防命名空间漂移）。
期望一律精确等式（②-e），不用成员判定。
"""
import ast
import importlib
import json
import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

BASELINE = os.path.join(EVAL_DIR, "reexport_surface_baseline.json")

GUARDED_MODULES = (
    ["verify_truth_consistency"]
    + [f"verify_checks.{n}_layer" for n in (
        "registry", "data", "doc", "governance", "skill",
        "status", "workflow", "workspace")]
)


def _rel_of(modname):
    # 跨平台固定用 `/`（Windows 的 os.path.join 会产出 `\`，基线在 Linux 面对不上即红，R247）：
    if modname == "verify_truth_consistency":
        return "verify_truth_consistency.py"
    return "verify_checks/" + modname.split(".")[1] + ".py"


def imported_names(tree):
    """顶层 import / from-import 引入的名字（asname 优先）。"""
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend((a.asname or a.name.split(".")[0]) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.extend((a.asname or a.name) for a in node.names
                         if a.name != "*")
    return names


def f401_surface(source):
    """「导入但词法未用」的名字（保序去重；import 行自身不算使用）。"""
    tree = ast.parse(source)
    names = imported_names(tree)
    used = set()

    class V(ast.NodeVisitor):
        def visit_Import(self, node):
            return

        def visit_ImportFrom(self, node):
            return

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load):
                used.add(node.id)

    V().visit(tree)
    seen, out = set(), []
    for n in names:
        if n not in used and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def live_surface():
    out = {}
    for modname in GUARDED_MODULES:
        rel = _rel_of(modname)
        with open(os.path.join(EVAL_DIR, *rel.split("/")),
                  encoding="utf-8") as fh:
            out[rel] = f401_surface(fh.read())
    return out


def load_baseline():
    with open(BASELINE, encoding="utf-8") as fh:
        return json.load(fh)


def test_baseline_file_present_and_shaped():
    base = load_baseline()
    assert sorted(base.keys()) == sorted(_rel_of(m) for m in GUARDED_MODULES)


def test_live_surface_equals_baseline_exactly():
    assert live_surface() == load_baseline()


def test_baselined_names_are_module_attributes():
    base = load_baseline()
    gaps = {}
    for modname in GUARDED_MODULES:
        mod = importlib.import_module(modname)
        missing = [n for n in base[_rel_of(modname)] if not hasattr(mod, n)]
        if missing:
            gaps[modname] = missing
    assert gaps == {}, gaps


def test_mutation_removed_import_breaks_baseline_equality():
    base = load_baseline()
    rel = "verify_truth_consistency.py"
    assert "SKILL_CONTENT" in base[rel]
    with open(os.path.join(EVAL_DIR, rel), encoding="utf-8") as fh:
        src = fh.read()
    mutated = src.replace(
        "from config import GLOBAL_SKILLS, GLOBAL_MEMORY, SKILL_CONTENT, PLUGIN_SKILLS_DIR",
        "from config import GLOBAL_SKILLS, GLOBAL_MEMORY, PLUGIN_SKILLS_DIR")
    assert mutated != src
    live = f401_surface(mutated)
    assert live == [n for n in base[rel] if n != "SKILL_CONTENT"]
    assert {n for n in base[rel] if n not in live} == {"SKILL_CONTENT"}


def test_mutation_missing_attribute_named_exactly():
    class NS:
        pass
    assert [n for n in ("SKILL_CONTENT", "os") if not hasattr(NS, n)] == [
        "SKILL_CONTENT", "os"]
