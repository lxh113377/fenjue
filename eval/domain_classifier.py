#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
domain_classifier.py — L0 领域分类器共享模块（单一真相源）
=====================================================
所有 eval/ audit/ 脚本引用本模块，不再各自拷贝 DOMAIN_KEYWORDS。

维护规则:
  - 关键词变更只改此文件
  - 新增脚本: `from domain_classifier import classify_domain, DOMAIN_KEYWORDS`
  - 现有脚本逐步迁移引用

当前: 13域 + 5子域, 覆盖145 skill (R169 +hermes-installer 并校准旧漂移)
版本: V1.0 | 2026-07-28 | 从 eval_bge_ultimate.py 提取+优化
"""

import re

# ====== L0 13域关键词分类器 ======
DOMAIN_KEYWORDS = {
    'system': [
        'skill', '安装', '管理', '安全', 'openclaw', 'audit', 'prompt',
        '焚诀', '路由', '评分', '优化.*路由', '优化.*记忆', '优化.*skill',
        '维护', '改造', '咋装', '装个', '这玩意儿',
    ],
    'local': [
        '本地', 'local', 'npu', 'tts', 'asr', 'ocr', '离线',
        '语音识别', '显存', '文生图', '图生图',
    ],
    'code': [
        '代码', '开发', 'debug', '重构', '测试', 'tdd', '编码',
        '乱码', 'utf', 'bom', '调试', 'bug', 'python', 'node',
        '清理', '修复', '报错', '修.*bug', '修.*错',
    ],
    'automation': [
        '自动化', 'dogfood', '微信', '项目记忆', 'taskflow',
        '审计闭环', 'preflight', '预检', '工作流', 'agent',
    ],
    'design': [
        '设计', 'ui', 'ux', '主题', '前端', '视觉', 'figma',
        '画布', '图标', 'svg', 'excalidraw', 'shadcn', '落地页',
        '架构图', '画个图', '艺术作品', '用代码画',
    ],
    'memory': [
        '记忆', 'memory', '写入', '反思', '对齐', '经验反哺',
        '任务复盘', '启动加载', '跨端同步', '自我认知',
        'markdown拆分', '拆小', '大文件拆分', '经验教训',
    ],
    'media': [
        '视频', '音频', '转码', 'ffmpeg', '字幕', 'whisper',
        '视频生成', 'seedance', 'seedream', '抽帧',
        '生成.*图片', '图片生成',
    ],
    'web': [
        'web', '网站', '动画', 'github', 'gsap', '浏览器',
        '���头', 'gstack', 'electron', '截图', '插件', 'clawhub',
        '部署上线', '上线', '填表单', '部署到',
    ],
    'data': [
        '数据', '图表', 'excel', '可视化', '数据统计', 'xlsx', '数据分析',
    ],
    'research': [
        '研究', 'research', '报告', '搜索', '企业查询', '天眼查',
        '深度研究', '网页提取', '虚拟机恢复', 'oracle', 'defuddle',
        '公司背景', '会议准备', '会议',
    ],
    'doc': [
        '文档', 'ppt', '论文', 'obsidian', 'notion', 'word',
        'docx', 'pdf', '演示文稿', '幻灯片', '笔记管理',
        '交接文档', '项目交接', '写个ppt',
    ],
    'creative': [
        '创意', '动画', '演示', 'hyperframes',
        '提示词优化', '优化提示词', '提示词.*优化', '视频文案',
    ],
    'general_utils': [
        '通用', '工具', '计划', '头脑风暴', 'mcp', 'mcporter',
        '创建技能', '执行计划',
    ],
}

# ====== System 域子域分类 ======
SUB_DOMAIN_KEYWORDS = {
    'skill管理': [
        '安装', '装个', '咋装', '装skill', 'skill安装',
        '创建skill', 'skill creator', 'skill安全', '依赖',
        'dependency', '合并skill', 'skill管理', 'skill清单',
        '管理skill', '删除skill',
    ],
    '路由+审计': [
        '路由', '命中率', '触发词', '诊断', '审计', '评分',
        '健康度', 'routing', 'audit', 'hitrate', 'trigger',
        '漂移', '修复路由',
    ],
    'OpenClaw控制': [
        'openclaw', 'oc disp', '派发', '双门禁', '监督', '周维护',
    ],
    '跨平台同步': [
        '跨平台', '同步', 'cross-platform', '四端', 'junction',
    ],
    '系统+桌面': [
        '桌面', 'computer use', 'windows', 'prompt', '提示词',
        '工作流', 'preflight', '数据层', 'consistency',
    ],
}

# ====== 域统计（与 skill_content 同步） ======
DOMAIN_SKILL_COUNTS = {
    'system': 27, 'local': 13, 'web': 13, 'automation': 11,
    'design': 11, 'doc': 11, 'code': 11, 'general_utils': 11,
    'research': 10, 'creative': 10, 'media': 7, 'memory': 6, 'data': 4,
}
TOTAL_SKILLS = sum(DOMAIN_SKILL_COUNTS.values())  # 145 (R169: +hermes-installer, 顺带校准 local/general_utils/research/creative/memory 旧漂移)


def classify_domain(query: str) -> str | None:
    """
    L0 领域分类: 关键词+正则匹配 → 13域之一
    
    参数:
      query: 用户查询文本
    
    返回:
      域名字符串，或 None（无匹配）
    """
    scores = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = 0
        for kw in keywords:
            try:
                if re.search(kw, query, re.IGNORECASE):
                    score += 1
            except re.error:
                if kw.lower() in query.lower():
                    score += 1
        if score > 0:
            scores[domain] = score
    
    if not scores:
        return None
    
    # 多域命中时，选得分最高的；同分选更具体的（关键词数少的域优先）
    max_score = max(scores.values())
    candidates = [d for d, s in scores.items() if s == max_score]
    
    if len(candidates) == 1:
        return candidates[0]
    
    # 同分破平: 选关键词表更精炼的域（更具体）
    return min(candidates, key=lambda d: len(DOMAIN_KEYWORDS[d]))


def classify_sub_domain(query: str) -> str | None:
    """
    System 域内子域分类
    
    参数:
      query: 用户查询文本
    
    返回:
      子域名字符串，或 None
    """
    scores = {}
    for sub, keywords in SUB_DOMAIN_KEYWORDS.items():
        score = 0
        for kw in keywords:
            try:
                if re.search(kw, query, re.IGNORECASE):
                    score += 1
            except re.error:
                if kw.lower() in query.lower():
                    score += 1
        if score > 0:
            scores[sub] = score
    
    if not scores:
        return None
    return max(scores, key=lambda d: scores[d])


# ====== 自检 ======
if __name__ == '__main__':
    test_queries = [
        ("帮我装个skill", "system"),
        ("figma设计稿转代码", "design"),
        ("Excel数据分析", "data"),
        ("刚才那个报错怎么修？", "code"),
        ("Notion会议准备", "research"),     # 修复后: 会议准备→research
        ("优化提示词", "creative"),          # 修复后: 优化提示词→creative
        ("检查路由健康度", "system"),
        ("大文件拆分", "memory"),
        ("全球记忆加载", "memory"),
        ("部署到线上", "web"),
        ("今天天气怎么样", None),
        ("生成视频", "media"),
        ("微信消息自动化", "automation"),
    ]
    
    print("L0 域分类器自检:")
    print("-" * 50)
    passed = 0
    for query, expected in test_queries:
        result = classify_domain(query)
        status = "✅" if result == expected else f"❌ (got {result})"
        if result == expected:
            passed += 1
        print(f"  {status} \"{query}\" → {result}")
    
    print(f"\n结果: {passed}/{len(test_queries)} 通过")
    
    # 子域测试
    print("\n子域分类自检:")
    sub_tests = [
        ("检查路由健康度", "路由+审计"),
        ("咋装这个skill", "skill管理"),
        ("openclaw派发任务", "OpenClaw控制"),
    ]
    for query, expected in sub_tests:
        result = classify_sub_domain(query)
        status = "✅" if result == expected else f"❌ (got {result})"
        print(f"  {status} \"{query}\" → {result}")
