#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_fragments.py — 批量修复触发词碎片（P0 即时行动）
策略: 只修「明��截断」类碎片（从 SKILL.md 提取时被截断的），
      不碰「极短泛化词」（同域共享词在 L2 域内匹配中是正常行为，
      需要 Batch 3 embedding 层来治本，不在此脚本处理范围）。
"""
import json
import glob
import os
from pathlib import Path

SKILL_CONTENT = r"<MEMORY_ROOT>\skill_content"

# ---- 截断碎片 → 修复映射（手工从 SKILL.md 提取正确语义短语） ----
FIX_MAP = {
    # memory/A-memory-start: "只加载所需内容减" → 截断
    "只加载所需内容减": "按需加载记忆文件",
    # memory/A-memory-start: "执行前必须确保相" → 截断
    "执行前必须确保相": "执行前确保所有必要skill已加载",
    # memory 类: 已卸载 skill 的碎片修复已归档
    "的自我认知镜像": "自我认知镜像分析",
    # memory/fenjue-memory-audit: "路由追问与经验查" → 截断
    "路由追问与经验查": "路由追问与经验查找审计",
    # automation/fenjue-cc-audit-cycle: "分达标时加载本" → 截断
    "分达标时加载本": "CC审计分数达标时加载本skill",
    # system/skill-defer-to-authority: 长碎片
    "任何skill与上级提示词产生矛盾的": "skill与权威提示词产生冲突时",
    # system/openclaw-dual-gate-quality-audit: 长碎片
    "任何需要openclaw质量评分的": "openclaw质量评分触发",
    # system/skill-routing-test-driven-fix: 碎片
    "测试驱动的": "测试驱动的路由修复",
    # system/skill-midtask-recheck: 碎片
    "发现当前未加载的": "发现任务中途未加载的专用skill",
    # system/prompt-consolidation: 碎片
    "的干净版本": "提示词清理去重",
    "清理多": "清理多层补丁提示词",
    # system/cross-platform-agent-sync: 碎片
    "改一处N端响应": "改一处四端同步响应",
    # system/skill-merge: 碎片
    "合并两个": "合并两个skill",
    # automation/vp-perspective-audit: 碎片
    "预判agent行为": "预判agent行为模式",
    # automation/hook-analyzer-skill: 碎片
    "运行脚本": "运行钩子分析脚本",
    # general_utils/audit-runner-safe-aggregate: 碎片
    "聚合脚本": "安全聚合审计脚本",
    # general_utils/executing-plans: 碎片
    "按计划实施": "按实施计划执行",
    # doc/report-generator-skill: 碎片
    "析报告": "生成分析报告",
    # creative/A-prompt-better: 长碎片
    "所有需要高质量 prompt 输出的": "高质量prompt输出优化",
    # system/openclaw-fenjue-weekly: 碎片
    "百维度评分": "百维度评分审计",
    "时触发": "周维护触发",
    # system/skill-drift-surgery: 碎片
    "术修复": "外科手术修复",
    # system/skills-security-check: 碎片
    "全审计": "安全审计",
    # memory 类: 已卸载 skill 的碎片修复已归档
    "叉分析中提取": "交叉分析中提取自我认知",
    # automation/fenjue-advisor-scoring: "建议者评分" 等 → 不算真碎片(语义完整)
    # (以"分"结尾的正常词: 评分/得分 是完整语义, 不修)
    # media 类: 已卸载 skill 的碎片修复已归档
    "动画的": "AI视频动画生成",
    # system/prompt-consolidation: 另一个碎片
    # "清理多" 已修, "的干净版本" 已修
    # web/chaoshi-admin-inline-edit: 短词不算碎片
    # "禁弹窗" 语义完整, 不修
}

def fix_skill(skill):
    """替换截断碎片为修复后的语义短语"""
    trigs = skill.get("triggers", [])
    fixed = []
    changed = False
    for tg in trigs:
        if tg in FIX_MAP:
            fixed.append(FIX_MAP[tg])
            changed = True
        else:
            fixed.append(tg)
    if changed:
        skill["triggers"] = fixed
    return changed

def main():
    files = sorted(glob.glob(os.path.join(SKILL_CONTENT, "*.json")))
    total_fixed = 0
    for fpath in files:
        data = json.loads(Path(fpath).read_text(encoding="utf-8"))
        domain_fixed = 0
        for s in data.get("skills", []):
            if fix_skill(s):
                domain_fixed += 1
        if domain_fixed:
            # 写回
            Path(fpath).write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            print(f"[FIXED] {os.path.basename(fpath)}: {domain_fixed} skills")
            total_fixed += domain_fixed
        else:
            print(f"[SKIP]  {os.path.basename(fpath)}: no fragments to fix")
    print(f"\n总计修复: {total_fixed} 个 skill 的触发词碎片")

if __name__ == "__main__":
    main()
