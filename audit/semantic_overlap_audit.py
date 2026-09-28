#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语义重叠自动审计 — MECE 合规检查
==============================
Bilibili方法论 §1: "相似竞争者比绝对数量更致命 — 30个互不相似的Skill比15个两两相似的还稳"

本脚本:
  1. 计算 135 skill BGE embeddings 的余弦相似度矩阵
  2. 标记相似度 > 0.7 的技能对（高重叠风险）
  3. 标记相似度 0.5-0.7 的技能对（中重叠风险，需要边界描述）
  4. 生成 MECE 合规报告 + 修复建议

用法:
  python audit/semantic_overlap_audit.py               # 全量审计
  python audit/semantic_overlap_audit.py --threshold 0.65 # 自定义阈值
  python audit/semantic_overlap_audit.py --json        # JSON输出
"""
import os
import sys
import json
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

THRESHOLDS = {
    'high': 0.70,   # 高重叠: 必须合并或明确边界
    'mid': 0.55,    # 中重叠: 建议强化"不适用场景"描述
    'low': 0.40,    # 低重叠: 健康
}

# ====== Load BGE index ======
eval_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'eval')
emb_path = os.path.join(eval_dir, 'bge_fullbody_embeddings.npy')
skills_path = os.path.join(eval_dir, 'bge_fullbody_skills.json')

embeddings = np.load(emb_path)
with open(skills_path, 'r', encoding='utf-8') as f:
    skills = json.load(f)

def load_skill_md(name):
    """读取 SKILL.md 获取描述和不适用场景"""
    md_path = os.path.join(r'<SKILLS_ROOT>', name, 'SKILL.md')
    if os.path.exists(md_path):
        with open(md_path, 'r', encoding='utf-8') as f:
            return f.read()
    return None

def extract_negative_constraints(md_text):
    """从 SKILL.md 提取 '不适用' / 'NOT USE' 约束"""
    if not md_text:
        return []
    constraints = []
    lines = md_text.split('\n')
    in_section = False
    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in ['不适用', 'not use', 'when not', 'not for', 'do not use']):
            in_section = True
            constraints.append(line.strip())
        elif in_section and line.strip() and not line.startswith('#'):
            constraints.append(line.strip())
        elif in_section and (line.startswith('#') or not line.strip()):
            in_section = False
    return constraints

def run_audit(threshold=None):
    if threshold:
        THRESHOLDS['high'] = float(threshold)
    
    # 计算相似度矩阵
    sim_matrix = cosine_similarity(embeddings)
    n = len(skills)
    
    high_risk = []
    mid_risk = []
    
    for i in range(n):
        for j in range(i + 1, n):
            sim = sim_matrix[i][j]
            pair = {
                'skill_a': skills[i]['name'],
                'domain_a': skills[i].get('domain', '?'),
                'skill_b': skills[j]['name'],
                'domain_b': skills[j].get('domain', '?'),
                'similarity': round(float(sim), 4),
                'same_domain': skills[i].get('domain') == skills[j].get('domain'),
            }
            
            if sim >= THRESHOLDS['high']:
                high_risk.append(pair)
            elif sim >= THRESHOLDS['mid']:
                mid_risk.append(pair)
    
    # Sort by similarity descending
    high_risk.sort(key=lambda x: -x['similarity'])
    mid_risk.sort(key=lambda x: -x['similarity'])
    
    # 生成报告
    print('=' * 75)
    print('🔍 语义重叠自动审计报告 (MECE Compliance)')
    print('=' * 75)
    print(f'总 Skill 数: {n}')
    print(f'高重叠阈值: {THRESHOLDS["high"]}  |  中重叠阈值: {THRESHOLDS["mid"]}')
    print()
    
    # ====== 高重叠风险 ======
    print(f'🔴 高重叠风险 (sim >= {THRESHOLDS["high"]}): {len(high_risk)} 对')
    print('-' * 75)
    
    if high_risk:
        print(f'{"Skill A":<35} {"Skill B":<35} {"相似度":>6} {"同域"}'  )
        print('-' * 75)
        for p in high_risk:
            same = '✓' if p['same_domain'] else '✗跨域'
            print(f'{p["skill_a"]:<35} {p["skill_b"]:<35} {p["similarity"]:>6.3f} {same}')
        print()
        
        # 详细建议
        print('🔧 修复建议 (按优先级):')
        print('-' * 75)
        for i, p in enumerate(high_risk[:10], 1):  # Top 10 only
            a, b = p['skill_a'], p['skill_b']
            
            # 读取两者的 SKILL.md 检查是否有负约束
            md_a = load_skill_md(a)
            md_b = load_skill_md(b)
            neg_a = extract_negative_constraints(md_a) if md_a else []
            neg_b = extract_negative_constraints(md_b) if md_b else []
            
            has_neg = bool(neg_a) or bool(neg_b)
            
            if p['same_domain']:
                action = '⚠️ 合并或明确边界' if not has_neg else '✅ 已有负约束，建议审计'
            else:
                action = '⚠️ 跨域重叠！检查域分类是否会误导'
            
            print(f'{i}. {a} ↔ {b} (sim={p["similarity"]:.3f}, {p["domain_a"]}/{p["domain_b"]})')
            print(f'   动作: {action}')
            if neg_a:
                print(f'   {a} 负约束: {neg_a[0][:80]}...')
            if neg_b:
                print(f'   {b} 负约束: {neg_b[0][:80]}...')
            if not has_neg and p['same_domain']:
                print('   💡 建议: 在每个 SKILL.md 中明确 "NOT USE WHEN" 场景')
            print()
    else:
        print('  ✅ 无高重叠技能对')
        print()
    
    # ====== 中重叠风险 ======
    print(f'🟡 中重叠风险 (sim {THRESHOLDS["mid"]}-{THRESHOLDS["high"]}): {len(mid_risk)} 对')
    print('-' * 75)
    
    if mid_risk:
        # 按域分组统计
        from collections import Counter
        domain_counts = Counter()
        for p in mid_risk:
            domain_counts[p['domain_a']] += 1
            if p['domain_a'] != p['domain_b']:
                domain_counts[p['domain_b']] += 1
        
        print(f'涉及领域: {", ".join(f"{d}({c})" for d, c in domain_counts.most_common(8))}')
        print('Top-5 重叠对:')
        for p in mid_risk[:5]:
            print(f'  {p["skill_a"]} ↔ {p["skill_b"]} (sim={p["similarity"]:.3f})')
        print(f'  ... 共 {len(mid_risk)} 对')
        print()
    else:
        print('  ✅ 无中重叠技能对')
        print()
    
    # ====== MECE 健康度 ======
    total_pairs = n * (n - 1) // 2
    high_pct = len(high_risk) / total_pairs * 100
    mid_pct = len(mid_risk) / total_pairs * 100
    
    print('📊 MECE 健康度总评')
    print('-' * 75)
    print(f'技能对总数: {total_pairs}')
    print(f'高重叠占比: {len(high_risk)}/{total_pairs} = {high_pct:.2f}%')
    print(f'中重叠占比: {len(mid_risk)}/{total_pairs} = {mid_pct:.2f}%')
    print(f'健康技能对: {total_pairs - len(high_risk) - len(mid_risk)} = {100 - high_pct - mid_pct:.2f}%')
    print()
    
    if high_pct > 1.0:
        print('🔴 评级: 需治理 — 高重叠占比 >1%')
    elif mid_pct > 5.0:
        print('🟡 评级: 需关注 — 中重叠占比 >5%')
    else:
        print('🟢 评级: 健康 — 重叠占比在合理范围')
    
    print()
    print('=' * 75)
    
    return {
        'high_risk': high_risk,
        'mid_risk': mid_risk,
        'summary': {
            'total_skills': n,
            'high_risk_count': len(high_risk),
            'mid_risk_count': len(mid_risk),
            'high_pct': round(high_pct, 2),
            'mid_pct': round(mid_pct, 2),
        }
    }

if __name__ == '__main__':
    threshold = None
    output_json = '--json' in sys.argv
    
    for arg in sys.argv[1:]:
        if arg.startswith('--threshold'):
            threshold = arg.split('=')[1] if '=' in arg else sys.argv[sys.argv.index(arg) + 1]
    
    result = run_audit(threshold)
    
    if output_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
