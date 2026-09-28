#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
triple_diff.py — 数据层三方一致性检测（融合评分卡 维度6）

对比三个数据源:
  A. 磁盘实际 skill 目录（含 SKILL.md）
  B. BGE 路由索引 (bge_fullbody_skills.json)
  C. 注册表 (cross_platform_map.json 的 skills 键)

为支持无单机依赖的单元测试（CI 可跑），逻辑拆分为：
  - I/O:   load_disk_skills(path) -> set
           load_bge(path)        -> set
           load_reg(path)        -> set
           load_reg_state(path)  -> dict   # name -> install_state
  - 纯函数: compute_triple_diff(disk, bge, reg, reg_state=None)
            -> (orphan_bge, ghost_bge, orphan_reg, ghost_reg)
            四个 set，零盘依赖，可直接用内存 set 注入单测。

main() 退化为薄编排，打印/退出码与旧版完全一致（STATUS 口径不变）。
"""
import json
import os
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
SKILLS_DIR = r'<SKILLS_ROOT>'
OC_PLUGIN_DIR = r'<NPM_GLOBAL>\node_modules\openclaw\skills'
BGE_FILE = os.path.join(PROJECT_DIR, 'eval', 'bge_fullbody_skills.json')
REG_FILE = os.path.join(PROJECT_DIR, 'skill', 'registry', 'cross_platform_map.json')


# ===== I/O 层（可注入路径，便于 fixture 测试）=====

def load_disk_skills(skills_dir):
    """扫描磁盘 skill 目录，返回含 SKILL.md 的子目录名集合。"""
    disk = set()
    if not os.path.isdir(skills_dir):
        return disk
    for entry in os.listdir(skills_dir):
        full = os.path.join(skills_dir, entry)
        if os.path.isdir(full) and os.path.exists(os.path.join(full, 'SKILL.md')):
            disk.add(entry)
    return disk


def load_bge(bge_file):
    """读取 BGE 路由索引，返回 skill 名集合。"""
    bge = set()
    if not os.path.exists(bge_file):
        return bge
    with open(bge_file, encoding='utf-8') as f:
        data = json.load(f)
    for s in data:
        if isinstance(s, dict) and s.get('name'):
            bge.add(s['name'])
        elif isinstance(s, str):
            bge.add(s)
    return bge


def load_reg(reg_file):
    """读取注册表，返回 skill 名集合。"""
    reg = set()
    if not os.path.exists(reg_file):
        return reg
    with open(reg_file, encoding='utf-8') as f:
        data = json.load(f)
    for name in (data.get('skills') or {}):
        reg.add(name)
    return reg


def load_reg_state(reg_file):
    """读取注册表 install_state，返回 {name: install_state_dict}。"""
    reg_state = {}
    if not os.path.exists(reg_file):
        return reg_state
    with open(reg_file, encoding='utf-8') as f:
        data = json.load(f)
    for name, info in (data.get('skills') or {}).items():
        if isinstance(info, dict):
            reg_state[name] = info.get('install_state', {}) or {}
    return reg_state


# ===== 纯函数层（零盘依赖，可单测）=====

def _is_legit(s):
    """已知合法差异: __skillhub 后缀=第三方安装；_ 前缀=系统目录。"""
    return '__skillhub' in s or s.startswith('_')


def _is_oc_only(name, reg_state):
    """OC 内置插件: oc=true 且 td/hm 均非 true（按设计只在 OC，不在 global_skills）。"""
    st = reg_state.get(name, {})
    return bool(st.get('oc')) and not st.get('td') and not st.get('hm')


def compute_triple_diff(disk, bge, reg, reg_state=None):
    """
    纯函数：计算三源差异，零盘依赖。

    返回 (orphan_bge, ghost_bge, orphan_reg, ghost_reg) 四个 set。
    reg_state 缺省时 OC-only 过滤不生效（与无注册表状态等价）；
    main() 会传入真实 reg_state 以保持 STATUS 口径完全一致。

    用法示例（pytest，无单机依赖）:
        disk = {'foo', '_sys'}
        bge  = {'foo', 'bar'}
        reg  = {'foo', 'bar'}
        o_bge, g_bge, o_reg, g_reg = compute_triple_diff(disk, bge, reg)
        assert o_bge == set() and g_bge == {'bar'}
    """
    reg_state = reg_state or {}
    orphan_bge = {s for s in (disk - bge) if not _is_legit(s)}
    ghost_bge = {s for s in (bge - disk) if not _is_legit(s)}
    orphan_reg = {s for s in (disk - reg) if not _is_legit(s)}
    ghost_reg = {s for s in (reg - disk) if not _is_legit(s) and not _is_oc_only(s, reg_state)}
    return orphan_bge, ghost_bge, orphan_reg, ghost_reg


# ===== 编排层（行为不变）=====

def main():
    # R-fix(2026-08-16): 磁盘口径对齐 build_registry——global_skills + OC 插件目录双源。
    # 旧口径仅扫 <SKILLS_ROOT>，42 个 OC 插件技能恒判 GHOST-BGE，三方一致被磁盘侧瓶颈锁死。
    disk = load_disk_skills(SKILLS_DIR) | load_disk_skills(OC_PLUGIN_DIR)
    bge = load_bge(BGE_FILE)
    reg = load_reg(REG_FILE)
    reg_state = load_reg_state(REG_FILE)

    orphan_bge, ghost_bge, orphan_reg, ghost_reg = compute_triple_diff(disk, bge, reg, reg_state)

    print('=' * 60)
    print('数据层三方一致性检测 (triple_diff)')
    print('=' * 60)
    print(f'磁盘: {len(disk)} | BGE索引: {len(bge)} | 注册表: {len(reg)}')
    print()
    print(f'孤儿(磁盘有/BGE无): {len(orphan_bge)}')
    for s in sorted(orphan_bge):
        print(f'  [ORPHAN-BGE] {s}')
    print(f'Ghost(BGE有/磁盘无): {len(ghost_bge)}')
    for s in sorted(ghost_bge):
        print(f'  [GHOST-BGE] {s}')
    print(f'孤儿(磁盘有/注册表无): {len(orphan_reg)}')
    for s in sorted(orphan_reg):
        print(f'  [ORPHAN-REG] {s}')
    print(f'Ghost(注册表有/磁盘无): {len(ghost_reg)}')
    for s in sorted(ghost_reg):
        print(f'  [GHOST-REG] {s}')

    total_issues = len(orphan_bge) + len(ghost_bge) + len(orphan_reg) + len(ghost_reg)
    # 健康率: 以磁盘为基准，三方一致的比例
    all_names = disk | bge | reg
    healthy = disk & bge & reg
    health_rate = len(healthy) / max(len(all_names), 1) * 100
    print(f'\n三方一致: {len(healthy)} | 健康率: {health_rate:.1f}%')

    if total_issues == 0:
        print('\nRESULT: PASS — 三方完全一致')
        return 0
    else:
        print(f'\nRESULT: {total_issues} 处差异需关注')
        return 1


if __name__ == '__main__':
    sys.exit(main())
