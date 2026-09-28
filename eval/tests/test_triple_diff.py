#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_triple_diff.py — triple_diff 纯函数 + fixture 集成测试（零单机依赖）

覆盖:
  - compute_triple_diff 四元组语义（orphan_bge/ghost_bge/orphan_reg/ghost_reg）
  - _is_legit 过滤（__skillhub 后缀 / _ 前缀系统目录）
  - oc_only 过滤（OC 内置插件只在 OC，不应算 ghost_reg）
  - load_* + compute 的 fixture 集成路径（用 tmp_path，不触碰 <SKILLS_ROOT>）
"""
import json

from triple_diff import (
    compute_triple_diff,
    load_bge,
    load_disk_skills,
    load_reg,
)


def test_all_consistent_returns_empty():
    disk = {'foo', 'bar'}
    o_bge, g_bge, o_reg, g_reg = compute_triple_diff(disk, disk, disk)
    assert (o_bge, g_bge, o_reg, g_reg) == (set(), set(), set(), set())


def test_orphan_bge():
    # 磁盘有、BGE 无 → orphan_bge
    o_bge, g_bge, o_reg, g_reg = compute_triple_diff({'foo', 'x'}, {'foo'}, {'foo'})
    assert o_bge == {'x'}
    assert g_bge == set()


def test_ghost_bge():
    # BGE 有、磁盘无 → ghost_bge
    o_bge, g_bge, o_reg, g_reg = compute_triple_diff({'foo'}, {'foo', 'y'}, {'foo'})
    assert g_bge == {'y'}
    assert o_bge == set()


def test_orphan_and_ghost_reg():
    o_bge, g_bge, o_reg, g_reg = compute_triple_diff({'foo', 'x'}, {'foo'}, {'foo', 'y'})
    assert o_reg == {'x'}      # 磁盘有、注册表无
    assert g_reg == {'y'}      # 注册表有、磁盘无


def test_legit_excluded_from_orphan_and_ghost():
    # __skillhub 后缀=第三方安装；_ 前缀=系统目录，都不应算差异
    disk = {'real', '_sysdir', 'third__skillhub'}
    o_bge, g_bge, o_reg, g_reg = compute_triple_diff(disk, {'real'}, {'real'})
    assert o_bge == set() and o_reg == set()
    # 反向：BGE/注册表含 legit 名但磁盘没有 → 也不算 ghost
    o_bge, g_bge, o_reg, g_reg = compute_triple_diff({'real'}, {'real', 'ghost__skillhub'}, {'real'})
    assert g_bge == set() and g_reg == set()


def test_oc_only_filtered_from_ghost_reg():
    reg = {'real', 'ocplugin'}
    # 无 reg_state: ocplugin 在注册表但不在磁盘 → 算 ghost_reg
    _, _, _, g_reg_no = compute_triple_diff({'real'}, {'real'}, reg, reg_state=None)
    assert g_reg_no == {'ocplugin'}
    # 传 reg_state 标记 oc=true 且 td/hm 非 true: 不再是 ghost
    reg_state = {'ocplugin': {'oc': True, 'td': False, 'hm': False}}
    _, _, _, g_reg_yes = compute_triple_diff({'real'}, {'real'}, reg, reg_state=reg_state)
    assert g_reg_yes == set()


def test_return_shape_is_four_sets():
    result = compute_triple_diff({'a'}, {'a'}, {'a'})
    assert isinstance(result, tuple) and len(result) == 4
    assert all(isinstance(s, set) for s in result)


def test_integration_via_loaders(tmp_path):
    """用 tmp_path fixture 跑 完整 I/O + 纯函数 链路，零真实路径依赖。"""
    skills_dir = tmp_path / 'skills'
    skills_dir.mkdir()
    (skills_dir / 'alpha').mkdir()
    (skills_dir / 'alpha' / 'SKILL.md').write_text('x', encoding='utf-8')
    (skills_dir / 'beta').mkdir()
    (skills_dir / 'beta' / 'SKILL.md').write_text('x', encoding='utf-8')
    # gamma 只在磁盘 → 预期 orphan
    (skills_dir / 'gamma').mkdir()
    (skills_dir / 'gamma' / 'SKILL.md').write_text('x', encoding='utf-8')

    bge_file = tmp_path / 'bge.json'
    bge_file.write_text(json.dumps([
        {'name': 'alpha'}, {'name': 'beta'}, {'name': 'delta'}  # delta 只在 BGE → ghost
    ], ensure_ascii=False), encoding='utf-8')

    reg_file = tmp_path / 'reg.json'
    reg_file.write_text(json.dumps({
        'skills': {'alpha': {}, 'beta': {}, 'epsilon': {}}  # epsilon 只在注册表 → ghost
    }, ensure_ascii=False), encoding='utf-8')

    disk = load_disk_skills(str(skills_dir))
    bge = load_bge(str(bge_file))
    reg = load_reg(str(reg_file))
    assert disk == {'alpha', 'beta', 'gamma'}

    o_bge, g_bge, o_reg, g_reg = compute_triple_diff(disk, bge, reg)
    assert o_bge == {'gamma'}
    assert g_bge == {'delta'}
    assert g_reg == {'epsilon'}
