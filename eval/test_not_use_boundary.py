#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_not_use_boundary.py — NOT USE 边界测试(R19)
================================================
验证 15 对 NOT USE 互斥规则：正例（应触发NOT USE→排除）vs 反例（不应触发→保留）。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unified_router import _build_negative_index

# 测试用例: (skill_name, query, should_exclude) 
# should_exclude=True: NOT USE 应触发排除
# should_exclude=False: NOT USE 不应触发(正常保留)
TEST_CASES = [
    # === 1. frontend-skill vs brainstorming ===
    ("frontend-skill", "帮我头脑风暴一下这个设计方案", True),
    ("frontend-skill", "帮我想几个创意点子", True),
    ("frontend-skill", "设计一个落地页的UI界面", False),  # 真正的设计任务
    ("brainstorming", "根据这个figma设计稿写代码", True),
    ("brainstorming", "帮我构思一个产品功能", False),  # 真正的头脑风暴

    # === 2. knowledge-capture vs research-documentation ===
    ("knowledge-capture", "写一份市场研究报告", True),
    ("knowledge-capture", "把今天的会议纪要整理一下", False),  # 真正的知识捕获
    ("research-documentation", "帮我整理最近的聊天记录", True),
    ("research-documentation", "搜索论文写文献综述", False),

    # === 3. slides vs pptx ===
    ("slides", "准备一下季度商务汇报", True),
    ("slides", "做一个创意产品发布演示", False),  # 创意演示=slides
    ("pptx", "做一份互动式的动画提案", True),
    ("pptx", "做个年度工作总结PPT", False),

    # === 4. writing-plans vs spec-to-implementation ===
    ("writing-plans", "帮我执行这个开发计划", True),
    ("writing-plans", "写一份项目规划大纲", False),
    ("spec-to-implementation", "写一份文档写作大纲", True),
    ("spec-to-implementation", "把这个技术规格转成代码实现", False),

    # === 5. byted-seedream 负标签边界（local-img2img 已删，R201）===
    # R-fix(2026-08-16): 离线/本地类负标签已移除——local-txt2img 不可达，断网/本地生成
    # 经 direct_route 本地守卫回落 byted-seedream（唯一文生图技能），NOT USE 不再拦截。
    ("byted-seedream-image-generate", "用 seedream 在线生成图片", False),
    ("byted-seedream-image-generate", "断网状态下生成图片", False),
    ("byted-seedream-image-generate", "在线 AI 画一张图", False),

    # === 6. skill-install vs install-skill-dependency ===
    ("skill-install", "npm install 报错帮我修", True),
    ("skill-install", "帮我装一个 skill", False),
    ("install-skill-dependency", "帮我安装一下这个 skill", True),
    ("install-skill-dependency", "这个二进制依赖缺失了帮我修", False),

    # === 7. obsidian-cli vs obsidian-markdown ===
    ("obsidian-cli", "帮我管理一下 Obsidian 笔记", True),
    ("obsidian-cli", "用命令行打开 Obsidian vault", False),
    ("obsidian-markdown", "搜索 Obsidian vault 中的文件", True),
    ("obsidian-markdown", "编辑这篇 Obsidian 笔记", False),

    # === 8. test-driven-development vs testing ===
    ("test-driven-development", "写���自动化测试覆盖这个功能", True),
    ("test-driven-development", "用 TDD 先写测试再写实现", False),
    ("testing", "先写测试再写代码", True),
    ("testing", "写个自动化测试脚本", False),

    # === 9. canvas-design vs algorithmic-art ===
    ("canvas-design", "用 p5.js 生成艺术作品", True),
    ("canvas-design", "设计一个海报", False),
    ("algorithmic-art", "设计一个公司 logo", True),
    ("algorithmic-art", "用代码生成视觉艺术", False),

    # === 10. frontend-skill (实现) vs ui-ux-pro-max (设计) ===
    ("frontend-skill", "帮我写一个 React 组件", False),
    ("frontend-skill", "设计一套 UI 视觉规范", True),
    ("ui-ux-pro-max", "帮我设计界面风格", False),
    ("ui-ux-pro-max", "实现一个响应式页面", True),

    # === 反面案例: 无关查询不应误杀 ===
    ("frontend-skill", "今天天气怎么样", False),  # 完全不相关
    ("brainstorming", "1+1等于几", False),
    ("pptx", "这个视频怎么剪辑", False),
    ("refactoring", "帮我装个 skill", False),
]

def check_not_use(skill_name, query):
    """检查 query 是否命中 skill 的 NOT USE 规则"""
    _build_negative_index()
    from unified_router import _NEGATIVE_SKILL_TAGS
    if skill_name not in _NEGATIVE_SKILL_TAGS:
        return False
    for pattern in _NEGATIVE_SKILL_TAGS[skill_name]:
        if pattern.search(query):
            return True
    return False

def main():
    results = {'pass': 0, 'fail': 0, 'false_pos': 0, 'false_neg': 0}
    failures = []

    for skill_name, query, should_exclude in TEST_CASES:
        actual = check_not_use(skill_name, query)
        
        if actual == should_exclude:
            results['pass'] += 1
            status = '✅'
        else:
            results['fail'] += 1
            status = '❌'
            if should_exclude and not actual:
                error = '漏杀'
                results['false_neg'] += 1
            else:
                error = '误杀'
                results['false_pos'] += 1
            failures.append((status, skill_name, query, should_exclude, actual, error))
    
    print("=" * 70)
    print("NOT USE 边界测试结果 (R19)")
    print("=" * 70)
    print(f"总计: {results['pass']+results['fail']} 条 | 通过: {results['pass']} | 失败: {results['fail']}")
    print(f"  误杀(不该排除却排除): {results['false_pos']} | 漏杀(该排除未排除): {results['false_neg']}")
    print()

    if failures:
        for status, sk, q, exp, act, err in failures:
            print(f"{status} [{err}] {sk}: \"{q}\" → 期望排除={exp} 实际={act}")
    else:
        print("✅ 全部通过 — 15对NOT USE规则无误杀/漏杀")

    return results['fail'] == 0

if __name__ == '__main__':
    passed = main()
    sys.exit(0 if passed else 1)
