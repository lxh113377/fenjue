#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_dual_tree.py — 双树协同（Memory Tree + Skill Tree）概念验证
================================================================
模拟: 当 Memory 上下文（用户画像/历史教训）注入 Skill 路由时，
     命中率能提升多少。

Memory 信号来源（模拟）:
  - user_patterns: 辉哥常用 skill 列表
  - lessons-p0: 历史教训中的上下文标签
  - 最近对话: 当前会话已提及的 skill（上下文窗口）
"""
import json
import os
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from scipy import sparse
from index_integrity import restricted_loads, verify_pickle_hash, verify_vectorizer_structure
from config import SKILL_CONTENT


# ---- 模拟 Memory Tree 输出 ----

# 用户常用 skill（从 user_patterns.md 和项目实际使用频率推断）
USER_FAVORITES = {
    "fenjue-routing-health-check": 0.9,
    "A-get-memory": 0.85,
    "A-memory-start": 0.95,
    "skill-install": 0.8,
    "debugging-fixing": 0.85,
    "bigfile-split": 0.75,
    "chaoshi-web-deploy": 0.85,
    "fenjue-memory-audit": 0.8,
    "skill-trigger-diagnosis": 0.75,
    "fenjue-advisor-scoring": 0.7,
    "utf8-encoding-fix": 0.8,
    "cross-platform-skill-sync": 0.7,
}

# 上下文标签映射（教训→skill 关联）
# 实际从 lessons-p0.md / lessons_index.md 的 JSON 化输出中提取
CONTEXT_SKILL_MAP = {
    "报错": ["debugging-fixing", "fenjue-cc-audit-cycle"],
    "部署": ["chaoshi-web-deploy"],
    "记忆": ["A-get-memory", "A-memory-start", "fenjue-memory-audit"],
    "路由": ["fenjue-routing-health-check", "skill-trigger-diagnosis", "skill-routing-test-driven-fix"],
    "编码": ["utf8-encoding-fix", "shell-encoding-pitfalls"],
    "拆分": ["bigfile-split"],
    "skill": ["skill-install", "skill-creator", "skill-merge", "skill-trigger-diagnosis"],
    "同步": ["cross-platform-skill-sync", "cross-platform-agent-sync"],
    "审计": ["fenjue-memory-audit", "fenjue-advisor-scoring", "prompt-system-audit"],
    "评分": ["fenjue-advisor-scoring", "openclaw-dual-gate-quality-audit"],
    "超市": ["chaoshi-web-deploy", "chaoshi-admin-inline-edit", "chaoshi-image-optimization"],
}

# ---- 加载 ----

matrix = sparse.load_npz(os.path.join(SKILL_CONTENT, "tfidf_matrix.npz"))
verify_pickle_hash(os.path.join(SKILL_CONTENT, "tfidf_vectorizer.pkl"), "tfidf_vectorizer.pkl")
with open(os.path.join(SKILL_CONTENT, "tfidf_vectorizer.pkl"), "rb") as f:
    vectorizer = restricted_loads(f.read())  # R209: 白名单受限反序列化
verify_vectorizer_structure(vectorizer, matrix.shape[1], "tfidf_vectorizer.pkl")
with open(os.path.join(SKILL_CONTENT, "skill_ids.json"), encoding="utf-8") as _f:
    skill_index = json.load(_f)
TEST_QUERIES = os.path.join(os.path.dirname(__file__), "test_queries.json")

def tfidf_match(query, threshold=0.10):
    q_vec = vectorizer.transform([query])
    sims = cosine_similarity(q_vec, matrix)[0]
    idxs = np.argsort(sims)[::-1][:15]
    return [(skill_index[i]["name"], float(sims[i])) for i in idxs if sims[i] > threshold]

def extract_context_tags(query):
    """从 query 中提取上下文标签（模拟 Memory Tree 结构化输出）"""
    tags = []
    for tag, skills in CONTEXT_SKILL_MAP.items():
        if tag in query:
            tags.append(tag)
    return tags

def memory_boost(query, tfidf_results):
    """
    双树协同核心:
    1. 从 query 提取上下文标签
    2. 根据标签找到关联 skill
    3. 对这些 skill 的 TF-IDF 分数做加权提升
    """
    tags = extract_context_tags(query)
    if not tags:
        return tfidf_results  # 无上下文，不增强
    
    # 收集所有标签关联的 skill + 用户偏好 skill
    boost_skills = {}
    for tag in tags:
        for sk in CONTEXT_SKILL_MAP.get(tag, []):
            boost_skills[sk] = max(boost_skills.get(sk, 0), 0.3)  # 上下文标签 boost
    
    # 用户偏好 boost
    for sk, weight in USER_FAVORITES.items():
        if sk in [r[0] for r in tfidf_results]:
            boost_skills[sk] = max(boost_skills.get(sk, 0), weight * 0.15)  # 偏好 boost
    
    # 应用 boost
    boosted = []
    for name, score in tfidf_results:
        b = boost_skills.get(name, 0)
        new_score = min(score + b, 1.0)  # 加分但不超 1.0
        boosted.append((name, new_score))
    
    boosted.sort(key=lambda x: -x[1])
    return boosted

# ---- 评估 ----

with open(TEST_QUERIES, encoding="utf-8") as _f:
    data = json.load(_f)
all_q = []
for tier in data:
    all_q.extend(tier["queries"])

def run_eval(match_fn, label):
    tp = fp = fn = 0
    fp_neg = 0
    for q in all_q:
        matched = match_fn(q["query"])
        names = [m[0] for m in matched]
        exp = q.get("expected_skill")
        if exp is None:
            if names:
                fp_neg += 1
            continue
        exp_set = {exp} if isinstance(exp, str) else set(exp)
        top1 = names[0] if names else None
        if top1 and top1 in exp_set:
            tp += 1
        elif top1:
            fp += 1
        if not names:
            fn += 1
    n_exp = sum(1 for q in all_q if q.get("expected_skill") is not None)
    n_neg = sum(1 for q in all_q if q.get("expected_skill") is None)
    p = tp/(tp+fp)*100 if (tp+fp) else 0
    r = tp/(tp+fn)*100 if (tp+fn) else 0
    f1 = 2*p*r/(p+r) if (p+r) else 0
    return {"label": label, "top1": tp/n_exp*100, "f1": f1, 
            "fp_rate": fp_neg/n_neg*100 if n_neg else 0,
            "tp": tp, "fp": fp, "fn": fn}

# ---- 运行 ----
print("=" * 65)
print("双树协同对比: TF-IDF 基线 vs Memory 增强")
print("=" * 65)

r_base = run_eval(lambda q: tfidf_match(q, 0.10), "TF-IDF 基线")
r_mem  = run_eval(lambda q: memory_boost(q, tfidf_match(q, 0.10)), "TF-IDF + Memory")

print(f"{'方法':<25} {'Top-1':>7} {'F1':>7} {'误触发':>7} {'TP':>5} {'FP':>5} {'FN':>3}")
print(f"{'-'*25} {'-'*7} {'-'*7} {'-'*7} {'-'*5} {'-'*5} {'-'*3}")
for r in [r_base, r_mem]:
    print(f"{r['label']:<25} {r['top1']:>6.1f}% {r['f1']:>6.1f}% {r['fp_rate']:>6.1f}% "
          f"{r['tp']:>5} {r['fp']:>5} {r['fn']:>3}")

print(f"\n📈 Memory 增强提升: Top-1 +{r_mem['top1']-r_base['top1']:.1f}pp, "
      f"F1 +{r_mem['f1']-r_base['f1']:.1f}pp")

# 逐条展示 Memory 增强效果
print("\n📋 Memory 增强生效的 query:")
for q in all_q:
    query = q["query"]
    tags = extract_context_tags(query)
    if not tags:
        continue
    base = [m[0] for m in tfidf_match(query, 0.10)][:3]
    boosted = [m[0] for m in memory_boost(query, tfidf_match(query, 0.10))][:3]
    exp = q.get("expected_skill")
    exp_str = exp if isinstance(exp, str) else " | ".join(exp) if exp else "(无)"
    if base != boosted:
        print(f"  '{query}' 标签:{tags}")
        print(f"    期望: {exp_str}")
        print(f"    基线: {base}")
        print(f"    增强: {boosted}")
