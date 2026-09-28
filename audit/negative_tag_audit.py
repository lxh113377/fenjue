#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
negative_tag_audit.py — 负标签健康检测（融合评分卡 维度19）

检查 negative_constraints.json 的健康度:
  1. Ghost 引用: negative 字段提到的 skill 磁盘不存在（如已删除的 plugin-creator）
  2. 自冲突: negative 字段包含 skill 自身的正触发词（自我否决）
  3. 缺失条目: 磁盘上有 negative_constraints 但没有对应 skill

输出:
  - 冲突数 / 健康率
  - 退出码: 0=健康, 1=有 WARN, 2=有 FAIL
"""
import json
import os
import re
import sys

AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(AUDIT_DIR)
SKILLS_DIR = r'<SKILLS_ROOT>'
OC_PLUGIN_DIR = r'<NPM_GLOBAL>\node_modules\openclaw\skills'
# R-fix(2026-08-16): TRAE 内置 skill 快照——2026-08-15 孤儿根目录清理把系统内置 skill
# (brand-guidelines/obsidian-*/notion-*/local-* 等) 从 <SKILLS_ROOT> 移入 _trash，
# 但系统仍加载它们。审计若不纳入则误报 ghost，负标签健康率虚低。
ORPHAN_BUILTIN_DIR = os.path.join(PROJECT_DIR, '_trash', '20260815_orphan_root_removal')
NEG_FILE = os.path.join(AUDIT_DIR, 'negative_constraints.json')

# 通用技术词白名单（出现在 negative 里但不是 skill 名）
COMMON_WORDS = {
    'Python', 'Node', 'Shell', 'Bash', 'PDF', 'Notion', 'Obsidian', 'PPT',
    'TTS', 'OCR', 'ASR', 'UI', 'SVG', 'VM', 'GitHub', 'GSAP', 'MCP',
    'skill', 'skills', 'Skill', 'CLI', 'JSON', 'MD', 'KB', 'GB', 'KB',
    'seedance', 'seedream', 'whisper', 'mediakit', 'hyperframes', 'taskflow',
    'obsidian-', 'nano-pdf', 'pdf', 'ppt', 'pptx', 'notion', 'github', 'gsap',
}

# 常见的"那是XX的活"引用模式
REF_PATTERN = re.compile(r'[\w-]+(?:/[\w-]+)*')


def load_negatives():
    if not os.path.exists(NEG_FILE):
        return {}
    with open(NEG_FILE, encoding='utf-8') as f:
        return json.load(f)


def main():
    negs = load_negatives()
    if not negs:
        print('negative_constraints.json 不存在或为空')
        return 2

    # 磁盘 skill 集合（global_skills + OC 插件目录双源，与 triple_diff/build_registry 同口径）
    disk_skills = set()
    for base in (SKILLS_DIR, OC_PLUGIN_DIR):
        if not os.path.isdir(base):
            continue
        for entry in os.listdir(base):
            full = os.path.join(base, entry)
            if os.path.isdir(full) and os.path.exists(os.path.join(full, 'SKILL.md')):
                disk_skills.add(entry)
    # TRAE 内置 skill 快照（孤儿根目录清理移入 _trash，系统仍加载）
    if os.path.isdir(ORPHAN_BUILTIN_DIR):
        for entry in os.listdir(ORPHAN_BUILTIN_DIR):
            full = os.path.join(ORPHAN_BUILTIN_DIR, entry)
            if os.path.isdir(full) and os.path.exists(os.path.join(full, 'SKILL.md')):
                disk_skills.add(entry)

    # 1. 条目本身是否 ghost（skill 已被删除但 negative 还有条目）
    ghost_entries = []
    for name in negs:
        # 兼容 __skillhub 后缀
        base = name.split('__')[0]
        if name not in disk_skills and base not in disk_skills:
            ghost_entries.append(name)

    # 2. negative 文本中引用的其他 skill 是否 ghost
    # skill 名是 ASCII kebab-case（如 skill-creator / node-inspect-debugger）
    # 只匹配 ASCII 字符构成的连续 token，避免中文短语误报
    ghost_refs = []
    for name, cfg in negs.items():
        neg_text = cfg.get('negative', '') if isinstance(cfg, dict) else ''
        # 模式1: "那是xx/yy/zz的活"（斜杠分隔的 skill 引用）
        for m in re.finditer(r'[A-Za-z][A-Za-z0-9_-]*(?:/[A-Za-z][A-Za-z0-9_-]*)+', neg_text):
            for token in m.group(0).split('/'):
                if token in COMMON_WORDS or token.split('__')[0] in COMMON_WORDS:
                    continue
                if token and token not in disk_skills and token.split('__')[0] not in disk_skills and token not in ghost_refs:
                    ghost_refs.append(token)
        # 模式2: 单个 ASCII skill 名出现在 "那是XX的活" 里
        for m in re.finditer(r'那是([A-Za-z][A-Za-z0-9_/-]*)的活', neg_text):
            for token in m.group(1).split('/'):
                if token in COMMON_WORDS or token.split('__')[0] in COMMON_WORDS:
                    continue
                if token and token not in disk_skills and token.split('__')[0] not in disk_skills and token not in ghost_refs:
                    ghost_refs.append(token)

    # 3. 自冲突: negative 把"自己"列为排斥对象（如 "不要用于XX——那是XX的活" 里 XX=自己）
    #    误报排除: "chaoshi-web-deploy是超市项目专用" 是说明性文字，不是自我否决
    self_conflicts = []
    for name, cfg in negs.items():
        neg_text = cfg.get('negative', '') if isinstance(cfg, dict) else ''
        if not neg_text:
            continue
        # 真正的问题模式: 自己是"那是"引用的一部分且出现在"不要用于"语境
        # 简化: 检测 "不要用于...那是<name>的活" 或 "<name>的活" 紧跟在"那是"后
        for m in re.finditer(r'那是' + re.escape(name) + r'的活', neg_text):
            self_conflicts.append((name, 'negative 把自己列为排斥对象'))
            break

    issues = len(ghost_entries) + len(ghost_refs) + len(self_conflicts)
    total_entries = len(negs)

    print('=' * 60)
    print('负标签健康检测 (negative_tag_audit)')
    print('=' * 60)
    print(f'总条目: {total_entries}')
    print(f'Ghost 条目(skill已删但仍有负标签): {len(ghost_entries)}')
    for g in ghost_entries:
        print(f'  [GHOST-ENTRY] {g}')
    print(f'Ghost 引用(负标签提到不存在的skill): {len(ghost_refs)}')
    for g in ghost_refs:
        print(f'  [GHOST-REF] {g}')
    print(f'自冲突: {len(self_conflicts)}')
    for s in self_conflicts:
        print(f'  [SELF-CONFLICT] {s}')
    print(f'健康率: {(1 - issues / max(total_entries, 1)) * 100:.1f}%')

    if issues == 0:
        print('\nRESULT: PASS — 负标签全部健康')
        return 0
    elif issues <= 3:
        print('\nRESULT: WARN — 少量问题需关注')
        return 1
    else:
        print('\nRESULT: FAIL — 负标签存在系统性问题')
        return 2


if __name__ == '__main__':
    sys.exit(main())
