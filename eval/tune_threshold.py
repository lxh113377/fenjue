#!/usr/bin/env python3
"""TF-IDF 阈值扫描 — 找 Top-1/F1 最优 & 误触发 ≤5% 的阈值"""
import json
import os
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from scipy import sparse
from index_integrity import restricted_loads, verify_pickle_hash, verify_vectorizer_structure
from config import SKILL_CONTENT

TEST_QUERIES = os.path.join(os.path.dirname(__file__), "test_queries.json")

matrix = sparse.load_npz(os.path.join(SKILL_CONTENT, "tfidf_matrix.npz"))
verify_pickle_hash(os.path.join(SKILL_CONTENT, "tfidf_vectorizer.pkl"), "tfidf_vectorizer.pkl")
with open(os.path.join(SKILL_CONTENT, "tfidf_vectorizer.pkl"), "rb") as f:
    vectorizer = restricted_loads(f.read())  # R209: 白名单受限反序列化
verify_vectorizer_structure(vectorizer, matrix.shape[1], "tfidf_vectorizer.pkl")
with open(os.path.join(SKILL_CONTENT, "skill_ids.json"), encoding="utf-8") as _f:
    skill_index = json.load(_f)

def tfidf_match(query, threshold):
    q_vec = vectorizer.transform([query])
    sims = cosine_similarity(q_vec, matrix)[0]
    idxs = np.argsort(sims)[::-1][:10]
    return [(skill_index[i]["name"], float(sims[i])) for i in idxs if sims[i] > threshold]

with open(TEST_QUERIES, encoding="utf-8") as _f:
    data = json.load(_f)
all_queries = []
for tier in data:
    for q in tier["queries"]:
        all_queries.append(q)

def eval_threshold(threshold):
    tp = fp = fn = 0
    fp_neg = 0
    for q in all_queries:
        matched = tfidf_match(q["query"], threshold)
        names = [m[0] for m in matched]
        expected = q.get("expected_skill")
        if expected is None:
            if names:
                fp_neg += 1
            continue
        exp_set = {expected} if isinstance(expected, str) else set(expected)
        top1 = names[0] if names else None
        if top1 and top1 in exp_set:
            tp += 1
        elif top1 and top1 not in exp_set:
            fp += 1
        if not names:
            fn += 1
    n_exp = sum(1 for q in all_queries if q.get("expected_skill") is not None)
    n_neg = sum(1 for q in all_queries if q.get("expected_skill") is None)
    p = tp/(tp+fp)*100 if (tp+fp) else 0
    r = tp/(tp+fn)*100 if (tp+fn) else 0
    f1 = 2*p*r/(p+r) if (p+r) else 0
    top1_acc = tp/n_exp*100
    fp_rate = fp_neg/n_neg*100
    return top1_acc, f1, fp_rate

print(f"{'阈值':>8} {'Top-1':>7} {'F1':>7} {'误触发':>7} {'判定'}")
print(f"{'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*8}")
best = (0, 0, 0, 0)
for t in [0.03, 0.05, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.15, 0.18, 0.20]:
    top1, f1, fp = eval_threshold(t)
    judge = "✅ 最优" if fp <= 5 and top1 > best[1] else ("⚠️ 误触" if fp > 5 else "")
    print(f"{t:>8.2f} {top1:>6.1f}% {f1:>6.1f}% {fp:>6.1f}% {judge}")
    if fp <= 5 and top1 > best[1]:
        best = (t, top1, f1, fp)

print(f"\n🏆 推荐阈值: {best[0]:.2f} (Top-1={best[1]:.1f}%, F1={best[2]:.1f}%, 误触发={best[3]:.1f}%)")
