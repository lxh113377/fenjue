#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skill_hitrate_eval_v2.py — 语义路由评估（TF-IDF 轻量版）
========================================================
对比: 关键词匹配 vs TF-IDF 语义 vs 混合路由
零额外依赖（numpy + sklearn + scipy，系统 Python 自带）
"""
import json
import os
import glob as _glob
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from scipy import sparse
from index_integrity import restricted_loads, verify_pickle_hash, verify_vectorizer_structure
from config import SKILL_CONTENT

TEST_QUERIES = os.path.join(os.path.dirname(__file__), "test_queries.json")

# ---- 加载 ----

def load_skills():
    skills = []
    for fpath in sorted(_glob.glob(os.path.join(SKILL_CONTENT, "*.json"))):
        bn = os.path.basename(fpath)
        if bn in ("embeddings.npy", "skill_ids.json", "tfidf_matrix.npz", "tfidf_vectorizer.pkl"):
            continue
        with open(fpath, encoding="utf-8") as _f:
            data = json.load(_f)
        for s in data.get("skills", []):
            skills.append({
                "name": s["name"],
                "domain": os.path.splitext(bn)[0],
                "triggers": s.get("triggers", []),
                "desc": s.get("desc", "")[:500]
            })
    return skills

def load_tfidf():
    """加载 TF-IDF 向量索引"""
    matrix = sparse.load_npz(os.path.join(SKILL_CONTENT, "tfidf_matrix.npz"))
    verify_pickle_hash(os.path.join(SKILL_CONTENT, "tfidf_vectorizer.pkl"), "tfidf_vectorizer.pkl")
    with open(os.path.join(SKILL_CONTENT, "tfidf_vectorizer.pkl"), "rb") as f:
        vectorizer = restricted_loads(f.read())  # R209: 白名单受限反序列化
    verify_vectorizer_structure(vectorizer, matrix.shape[1], "tfidf_vectorizer.pkl")
    with open(os.path.join(SKILL_CONTENT, "skill_ids.json"), encoding="utf-8") as _f:
        skill_index = json.load(_f)
    return vectorizer, matrix, skill_index

# ---- 匹配方法 ----

def keyword_match(query, skills):
    """关键词子串匹配"""
    q_lower = query.lower()
    scores = []
    for s in skills:
        score = 0
        for tg in s["triggers"]:
            tg_lower = tg.lower()
            if tg_lower in q_lower or (len(tg_lower) >= 2 and q_lower in tg_lower):
                score += 1
        if score > 0:
            scores.append((s["name"], score, s["domain"]))
    scores.sort(key=lambda x: -x[1])
    return [s[0] for s in scores]

def tfidf_match(query, vectorizer, matrix, skill_index, top_k=10, threshold=0.05):
    """TF-IDF 余弦相似度 Top-K 召回"""
    q_vec = vectorizer.transform([query])
    sims = cosine_similarity(q_vec, matrix)[0]
    top_indices = np.argsort(sims)[::-1][:top_k]
    results = []
    for idx in top_indices:
        if sims[idx] > threshold:
            results.append((skill_index[idx]["name"], float(sims[idx])))
    return [r[0] for r in results]

def hybrid_match(query, skills, vectorizer, matrix, skill_index):
    """混合路由: keyword 优先 + tfidf 补充"""
    kw = keyword_match(query, skills)
    tf = tfidf_match(query, vectorizer, matrix, skill_index)
    seen = set()
    result = []
    for name in kw:
        if name not in seen:
            result.append(name)
            seen.add(name)
    for name in tf:
        if name not in seen:
            result.append(name)
            seen.add(name)
    return result

# ---- 评估 ----

def load_registry_names():
    """加载实时注册表 skill 名集合（<MEMORY_ROOT>\\skill_content\\skill_ids.json），
    用于侦测评测集污染：期望标签不在注册表 = 该 query 永远不可判对 = 污染项。"""
    try:
        with open(os.path.join(SKILL_CONTENT, "skill_ids.json"), encoding="utf-8") as _f:
            ids = json.load(_f)
        if isinstance(ids, list):
            return set(e["name"] for e in ids if isinstance(e, dict) and "name" in e)
        if isinstance(ids, dict):
            names = set(ids.keys())
            for v in ids.values():
                if isinstance(v, list):
                    names.update(v)
                elif isinstance(v, dict):
                    names.update(v.keys())
            return names
    except Exception:
        return set()

def eval_method(queries_all, match_fn, registry=None, **kwargs):
    results = []
    for tier_data in queries_all:
        for q in tier_data["queries"]:
            query = q["query"]
            expected = q.get("expected_skill")
            if isinstance(expected, str):
                expected_set = {expected}
            elif isinstance(expected, list):
                expected_set = set(expected)
            else:
                expected_set = set()

            # 评测集污染侦测：期望标签全部不在实时注册表 → 该 query 不可判对，标记 contaminated
            if registry is not None and expected_set:
                valid = expected_set & registry
                contaminated = len(valid) == 0
            else:
                contaminated = False

            matched = match_fn(query, **kwargs) if kwargs else match_fn(query)

            top1 = matched[0] if matched else None
            top1_correct = top1 in expected_set if expected_set else (top1 is None)
            top3_correct = any(n in expected_set for n in matched[:3]) if expected_set else True
            any_hit = bool(matched)

            results.append({
                "query": query, "expected": list(expected_set),
                "matched": matched[:5], "top1": top1,
                "top1_correct": top1_correct, "top3_correct": top3_correct,
                "any_hit": any_hit, "contaminated": contaminated
            })
    
    # 排除被污染的 query（期望标签全不在注册表，不可判对），避免污染分母虚低命中率
    exp_r = [r for r in results if r["expected"] and not r["contaminated"]]
    n_exp = len(exp_r)
    tp = sum(1 for r in exp_r if r["top1_correct"])
    fp = sum(1 for r in exp_r if r["top1"] and not r["top1_correct"])
    fn = sum(1 for r in exp_r if not r["any_hit"])
    p = tp/(tp+fp)*100 if (tp+fp) else 0
    r_ = tp/(tp+fn)*100 if (tp+fn) else 0
    f1 = 2*p*r_/(p+r_) if (p+r_) else 0

    contaminated_n = sum(1 for r in results if r["contaminated"])

    neg_r = [r for r in results if not r["expected"]]
    fp_neg = sum(1 for r in neg_r if r["any_hit"])

    return {
        "top1_acc": round(sum(1 for r in exp_r if r["top1_correct"])/n_exp*100,1) if n_exp else 0,
        "top3_acc": round(sum(1 for r in exp_r if r["top3_correct"])/n_exp*100,1) if n_exp else 0,
        "hit_rate": round(sum(1 for r in exp_r if r["any_hit"])/n_exp*100,1) if n_exp else 0,
        "precision": round(p,1), "recall": round(r_,1), "f1": round(f1,1),
        "fp_rate": round(fp_neg/len(neg_r)*100,1) if neg_r else 0,
        "contaminated": contaminated_n,
        "results": results, "tp": tp, "fp": fp, "fn": fn
    }

def print_failures(results, label):
    failures = [r for r in results if r["expected"] and not r["top1_correct"]]
    if failures:
        print(f"\n  [{label}] Top-1 未命中 ({len(failures)}):")
        for r in failures[:10]:  # 最多显示10条
            exp = " | ".join(r["expected"])
            got = r["top1"] or "(无匹配)"
            print(f"    ❌ '{r['query']}' → 期望[{exp}] 命中[{got}]")
        if len(failures) > 10:
            print(f"    ... 还有 {len(failures)-10} 条")

def main():
    skills = load_skills()
    with open(TEST_QUERIES, encoding="utf-8") as _f:
        data = json.load(_f)
    registry = load_registry_names()
    print(f"[registry] 实时注册表 skill 数 = {len(registry)}")

    # ---- 方法1: 关键词 ----
    print("=" * 65)
    print("方法1: 纯关键词匹配")
    r1 = eval_method(data, lambda q: keyword_match(q, skills), registry=registry)

    # ---- 方法2: TF-IDF ----
    print("\n加载 TF-IDF 索引...")
    vectorizer, matrix, skill_index = load_tfidf()

    print("\n" + "=" * 65)
    print("方法2: TF-IDF 语义匹配")
    r2 = eval_method(data,
                     lambda q: tfidf_match(q, vectorizer, matrix, skill_index), registry=registry)

    print("\n" + "=" * 65)
    print("方法3: 混合路由 (keyword + TF-IDF)")
    r3 = eval_method(data,
                     lambda q: hybrid_match(q, skills, vectorizer, matrix, skill_index), registry=registry)
    
    # ---- 逐条对比 ----
    print(f"\n{'='*65}")
    print("📋 逐条对比 (仅显示有差异的)")
    print(f"{'='*65}")
    for tier_data in data:
        tier = tier_data["tier"]
        print(f"\n--- {tier.upper()} ---")
        for q in tier_data["queries"]:
            query = q["query"]
            kw = keyword_match(query, skills)[:3]
            tf = tfidf_match(query, vectorizer, matrix, skill_index)[:3]
            hy = hybrid_match(query, skills, vectorizer, matrix, skill_index)[:3]
            if kw != tf:
                exp = q.get("expected_skill", "")
                exp_str = exp if isinstance(exp, str) else " | ".join(exp) if exp else "(无)"
                print(f"  '{query}' → 期望[{exp_str}]")
                print(f"    KW: {kw or '(无)'}")
                print(f"    TF: {tf or '(无)'}")
                print(f"    HY: {hy or '(无)'}")
    
    # ---- 对比表 ----
    print(f"\n{'='*65}")
    print("📊 三种方法对比")
    print(f"{'='*65}")
    print(f"{'方法':<20} {'Top-1':>7} {'Top-3':>7} {'命中率':>7} {'P':>7} {'R':>7} {'F1':>7} {'误触发':>7}")
    print(f"{'-'*20} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")
    for r, label in [(r1,"关键词"), (r2,"TF-IDF"), (r3,"混合路由")]:
        print(f"{label:<20} {r['top1_acc']:>6.1f}% {r['top3_acc']:>6.1f}% {r['hit_rate']:>6.1f}% "
              f"{r['precision']:>6.1f}% {r['recall']:>6.1f}% {r['f1']:>6.1f}% {r['fp_rate']:>6.1f}%")

    # 评测集污染报告（期望标签不在实时注册表的不可判对项，已从准确率分母剔除）
    print("\n⚠️  评测集污染（期望 skill 不在实时注册表，已从分母剔除）:")
    for r, label in [(r1,"关键词"), (r2,"TF-IDF"), (r3,"混合路由")]:
        print(f"    {label:<10} contaminated = {r['contaminated']}")
    
    # 提升幅度
    print("\n📈 提升幅度:")
    for metric, name in [("top1_acc","Top-1"), ("top3_acc","Top-3"), ("f1","F1")]:
        kw_v = r1[metric]
        tf_v = r2[metric]
        hy_v = r3[metric]
        print(f"  {name}:  {kw_v}% (KW) → {tf_v}% (TF-IDF, +{tf_v-kw_v:.1f}pp) → {hy_v}% (混合, +{hy_v-kw_v:.1f}pp)")
    
    # 失败详情
    print_failures(r1["results"], "关键词")
    print_failures(r2["results"], "TF-IDF")

if __name__ == "__main__":
    main()
