#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速碎片检测 — 扫描所有 skill_content/*.json 触发词，标记可疑碎片
输出: skill name + 可疑触发词 + 理由
"""
import json
import re
import glob
import os

SKILL_CONTENT = r"<MEMORY_ROOT>\skill_content"

def is_suspicious_fragment(trig, skill_name):
    reasons = []
    t = trig.strip()

    # 1. 长度过短: 中文 ≤2 字且不含品牌 token（3字短语如 报错了/流程图/提PR 语义完整，路由实测有效，不标）
    if len(t) <= 2 and re.search(r'[\u4e00-\u9fff]', t):
        reasons.append("极短中文(≤2字)")

    # 2. 截断尾特征: 以虚词/量词/连接词结尾
    # 2026-08-01 修复: normal_endings_2char 扩充——评分/审查/拆分/提取/文本/行为 等正常双字动词名词尾
    # 不再误报（路由实测 '代码审查'→github-code-review、'透视表'→data-analysis 均正确）
    truncation_endings = ['减', '的', '含', '分', '本', '相', '查', '改',
                          '将', '是', '为', '已', '应', '此', '个', '条',
                          '种', '次', '按', '对', '向', '从', '在']
    if len(t) >= 3 and t[-1] in truncation_endings:
        # 排除正常结尾词: "安装"/"管理"/"同步" 等完整词
        normal_endings_2char = ['安装', '管理', '同步', '检查', '修复', '优化',
                                '审计', '生成', '创建', '部署', '设计', '开发',
                                '测试', '搜索', '分析', '配置', '更新', '删除',
                                '发布', '调试', '构建', '迁移', '转换', '压缩',
                                '评分', '审查', '拆分', '提取', '文本', '行为',
                                '计划', '修改', '处理', '判断', '对比', '收集',
                                '编写', '制作', '整理', '导出', '导入', '验证',
                                '确认', '提交', '推送', '合并', '克隆', '备份',
                                '恢复', '清理', '归档', '汇总', '展示', '绘制',
                                '渲染', '分类', '统计', '过滤', '分组', '排序',
                                '编写', '汇编', '编排', '编排', '转录', '转写',
                                '转译', '翻译', '朗读', '播放', '编辑', '改写',
                                '缩减', '扩写', '总结', '概括', '挑选', '推荐']
        if t[-2:] not in normal_endings_2char:
            reasons.append(f"截断尾特征(以'{t[-1]}'结尾)")

    # 3. 以结构词开头的不完整短语
    incomplete_starts = ['的', '了', '在', '和', '或', '等', '及', '与',
                        '将', '把', '被', '让', '从', '对', '向', '按']
    if t[0] in incomplete_starts and len(t) <= 5:
        reasons.append(f"不完整开头(以'{t[0]}'开头的短语碎片)")

    # 4. 明显的 kebab 英文碎片(非品牌 token)
    brand_tokens = {'figma','docx','pptx','notion','obsidian','github','gsap','whisper',
                    'deploy','openclaw','skill','json','node','local','preflight','canvas',
                    'cli','asr','tts','ocr','npu','api','sdk','ui','ux','web','git','docker',
                    'k8s','code','data','test','debug','agent','mail','wechat','tencent',
                    'cloudbase','mcp','prompt','memory','audit','handoff','router','bootstrap'}
    low = t.lower()
    if re.match(r'^[a-z][a-z0-9_.-]+$', low) and low not in brand_tokens and len(low) <= 4:
        reasons.append("极短英文碎片(非品牌token)")

    return reasons if reasons else None

def main():
    files = sorted(glob.glob(os.path.join(SKILL_CONTENT, "*.json")))
    total_skills = 0
    total_fragments = 0
    rows = []

    for f in files:
        if os.path.basename(f) == "skill_ids.json":
            continue
        domain = os.path.splitext(os.path.basename(f))[0]
        data = json.load(open(f, encoding="utf-8"))
        for s in data.get("skills", []):
            total_skills += 1
            name = s["name"]
            frags = []
            for tg in s.get("triggers", []):
                reasons = is_suspicious_fragment(tg, name)
                if reasons:
                    frags.append((tg, reasons))
            if frags:
                total_fragments += len(frags)
                rows.append((domain, name, frags))

    # 输出
    print(f"=== 碎片检测结果 === ({total_skills} skill, {total_fragments} 可疑碎片)\n")
    for domain, name, frags in sorted(rows, key=lambda x: -len(x[2])):
        print(f"[{domain}] {name}")
        for tg, reasons in frags:
            print(f"  ⚠️ '{tg}' → {', '.join(reasons)}")
        print()

    print(f"总计: {total_fragments} 个可疑触发词碎片 / {total_skills} 个 skill")
    print(f"碎片率: {total_fragments}/{total_skills} = {total_fragments/total_skills:.1f} 个/skill")

if __name__ == "__main__":
    main()
