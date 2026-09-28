#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 Skill Tag 倒排索引 — 从 SKILL.md 描述 + 领域分类 + 上下文标签提取"""
import json
import os
import re
from pathlib import Path

SKILLS_DIR = r'<SKILLS_ROOT>'
EVAL_DIR = os.path.dirname(os.path.abspath(__file__))

# 基础标签来源
TAG_SOURCES = {
    # 1) 从 unified_router DOMAIN_KEYWORDS 提取领域标签
    'domain_tags': {
        'system': ['系统', 'skill管理', '路由', '审计', '评分', 'openclaw', '跨平台同步'],
        'local': ['本地计算', 'NPU', 'TTS', 'ASR', 'OCR', '文生图', '图生图', '语音'],
        'code': ['代码', '调试', '重构', '测试', '编码', 'bug修复', 'Python', 'Node.js'],
        'automation': ['自动化', '微信', '工作流', 'agent编排', '预检'],
        'design': ['设计', 'UI', '前端', 'Figma', 'SVG', 'shadcn', '落地页', '图标'],
        'memory': ['记忆', '经验反哺', '任务复盘', '自我认知', '大文件拆分'],
        'media': ['视频', '音频', 'ffmpeg', '字幕', 'whisper', '视频生成'],
        'web': ['Web开发', 'GitHub', 'GSAP', '浏览器', 'gstack', '截图', '部署', '插件'],
        'data': ['数据', '图表', 'Excel', '可视化', 'xlsx', '数据分析'],
        'research': ['研究', '搜索', '天眼查', '深度研究', '网页提取', '会议'],
        'doc': ['文档', 'PPT', 'Obsidian', 'Notion', 'Word', 'PDF', '演示文稿', '项目交接'],
        'creative': ['创意', '动画', 'hyperframes', '提示词优化'],
        'general_utils': ['通用工具', '计划', '头脑风暴', 'MCP', '执行计划'],
    },
}

# 2) 从 CONTEXT_SKILL_MAP 反向构建 tag→skill
# (这些已在 unified_router.py 中，复制过来保持一致)
CONTEXT_SKILL_MAP = {
    "报错": ["debugging-fixing"],
    "部署": ["chaoshi-web-deploy"],
    "记忆": ["A-get-memory", "A-memory-start", "fenjue-memory-audit"],
    "路由": ["fenjue-routing-health-check", "skill-routing-test-driven-fix"],
    "编码": ["utf8-encoding-fix"],
    "乱码": ["utf8-encoding-fix", "shell-encoding-pitfalls"],
    "拆分": ["bigfile-split"],
    "拆小": ["bigfile-split"],
    "安装": ["skill-install"],
    "装个": ["skill-install"],
    "创建skill": ["skill-creator"],
    "同步": ["cross-platform-skill-sync", "cross-platform-agent-sync"],
    "审计": ["fenjue-memory-audit", "fenjue-advisor-scoring", "prompt-system-audit"],
    "评分": ["fenjue-advisor-scoring"],
    "超市": ["chaoshi-web-deploy", "chaoshi-admin-inline-edit", "chaoshi-image-optimization"],
    "命中率": ["skill-hitrate-full-audit", "skill-routing-test-driven-fix"],
    "提升": ["fenjue-routing-health-check", "skill-hitrate-full-audit"],
    "重构": ["refactoring"],
    "测试": ["testing", "test-driven-development"],
    "debug": ["debugging-fixing"],
    "修复": ["debugging-fixing"],
    "分析": ["data-analysis", "consulting-analysis"],
    "报告": ["report-generator-skill", "consulting-analysis", "internal-comms"],
    "视频": ["video-frames", "video-whisper-transcribe"],
    "生成.*视频": ["byted-seedance-video-generate"],
    "生成.*图片": ["byted-seedream-image-generate"],
    "文生图": ["byted-seedream-image-generate"],
    "图生图": ["byted-seedream-image-generate"],
    "优化": ["A-prompt-better", "fenjue-routing-health-check"],
    "画图": ["chart-visualization", "diagram-maker", "canvas-design"],
    "图表": ["chart-visualization", "data-visualization"],
    "表格": ["xlsx", "data-analysis"],
    "项目": ["A-project-handoff"],
    "交接": ["A-project-handoff"],
    "prompt": ["A-prompt-better"],
    "提示词": ["A-prompt-better"],
}

# 3) 从 SKILL.md description 提取触发词
def extract_triggers_from_skill_md(skill_name):
    """从 SKILL.md 提取触发词"""
    triggers = []
    md_path = os.path.join(SKILLS_DIR, skill_name, 'SKILL.md')
    if not os.path.exists(md_path):
        return triggers
    
    body = Path(md_path).read_text(encoding='utf-8')
    
    # 从 frontmatter 提取
    if body.startswith('---'):
        end = body.find('---', 3)
        if end > 0:
            fm = body[3:end]
            for line in fm.split('\n'):
                if 'trigger' in line.lower() or '触发' in line:
                    triggers.append(line.strip())
    
    # 从正文 description 段提取触发词
    for line in body.split('\n'):
        stripped = line.strip()
        if '触发词' in stripped or 'triggers' in stripped.lower():
            # 提取冒号后的内容
            parts = stripped.split('：') if '：' in stripped else stripped.split(':')
            if len(parts) > 1:
                trigger_text = parts[1]
                for t in re.split(r'[,，/、]', trigger_text):
                    t = t.strip().strip('"\'「」')
                    if t and len(t) >= 2:
                        triggers.append(t)
    
    return triggers


def build_tag_index():
    """构建 tag→[skill_names] 倒排索引"""
    tag_index = {}
    
    # 从 bge_fullbody_skills.json 获取所有 skill 名和领域
    skills = json.loads(Path(os.path.join(EVAL_DIR, 'bge_fullbody_skills.json')).read_text(encoding='utf-8'))
    
    # 来源1: Context tag映射
    for tag, skill_list in CONTEXT_SKILL_MAP.items():
        # 清理正则模式→纯文本标签
        clean_tag = tag.replace('.*', '').replace('\\', '')
        if len(clean_tag) >= 2:
            tag_index.setdefault(clean_tag, set()).update(skill_list)
    
    # 来源2: 每个skill自身的触发词
    for s in skills:
        name = s['name']
        triggers = extract_triggers_from_skill_md(name)
        for t in triggers:
            if len(t) >= 2:
                tag_index.setdefault(t, set()).add(name)
    
    # 来源3: 领域标签
    for domain, tags in TAG_SOURCES['domain_tags'].items():
        domain_skills = [s['name'] for s in skills if s.get('domain') == domain]
        for tag in tags:
            tag_index.setdefault(tag, set()).update(domain_skills)
    
    # 转为 list（JSON序列化）
    tag_index_serializable = {k: sorted(list(v)) for k, v in tag_index.items()}
    
    # 统计
    total_tags = len(tag_index_serializable)
    avg_skills = sum(len(v) for v in tag_index_serializable.values()) / total_tags if total_tags > 0 else 0
    
    output = {
        '_meta': {
            'total_tags': total_tags,
            'total_skills': len(skills),
            'avg_skills_per_tag': round(avg_skills, 1),
            'sources': ['CONTEXT_SKILL_MAP', 'SKILL.md triggers', 'domain_tags'],
        },
        'index': tag_index_serializable,
    }
    
    out_path = os.path.join(EVAL_DIR, 'skill_tags.json')
    Path(out_path).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    
    print(f"Tag索引已生成: {out_path}")
    print(f"  标签数: {total_tags}")
    print(f"  覆盖skill数: {len(skills)}")
    print(f"  平均每标签: {avg_skills} 个skill")
    
    # Top-10 最紧密的标签（对应skill最少=最精确的标签）
    tight_tags = sorted(tag_index_serializable.items(), key=lambda x: len(x[1]))[:10]
    print("\n最精确的标签（Top-10）:")
    for tag, skills in tight_tags:
        print(f"  [{tag}] → {len(skills)} skills: {', '.join(skills[:3])}")
    
    return output


if __name__ == '__main__':
    build_tag_index()
