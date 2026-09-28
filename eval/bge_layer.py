#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bge_layer.py — L1 召回层（BGE Full-Body + TF-IDF 降级 + ensemble 重排）
====================================================================
R162: 从 unified_router.py 拆出（五层模块化: direct/tag/BGE/memory/LLM）。
对外 API: _load_bge / tfidf_score / ensemble_rerank / bge_recall
"""
from __future__ import annotations  # P0-2: 注解延迟求值，允许 ndarray 仅 TYPE_CHECKING 导入
import os
import json
import sys
import importlib.util
import threading  # P0-6: 计数器锁，多线程路由下防撕裂
from typing import TYPE_CHECKING
# P0-2: numpy/sklearn 顶层导入税（实测冷启动 ~0.9s）下沉到函数内懒导入；
# direct 短路/TF-IDF-only 路径零缴税。用到时分别在 _load_bge_corpus / bge_recall / tfidf_score 内 import。
if TYPE_CHECKING:  # 仅类型标记，运行时零导入
    from numpy import ndarray

from tag_layer import negative_filter_candidates
from index_integrity import restricted_loads, verify_pickle_hash, verify_vectorizer_structure
from config import SKILL_CONTENT  # SKILLS_DIR 无引用（R208 O-8 ruff F401 清理）

# ====== 路径 ======
EVAL_DIR = os.path.dirname(os.path.abspath(__file__))

# ====== BGE 索引（懒加载） ======
_bge_model = None
_bge_emb: ndarray | None = None
_bge_skills: list[dict] | None = None

# R163: 降级行为可观测标志 — degrade_behavior_test.py 置位后断言 TF-IDF 兜底真实生效
FALLBACK_USED = False
# R163: BGE 层调用计数器 — 证明查询真的走到了 BGE 层（防直连短路导致"假验证"）
CALL_COUNT = 0
# P0-6: 计数器锁 —— CALL_COUNT / FALLBACK_USED 写操作必须持锁（多线程路由计数撕裂实证）
_COUNTER_LOCK = threading.Lock()
# R-fix: torch 探测只跑一次 —— 损坏时子进程 import torch 会 segfault，若每次 bge_recall 都重探，
# 分层盲测 300+ 条会触发 300+ 次崩溃子进程（极慢且刷屏）。探测失败后永久跳过，走 TF-IDF 降级。
_BGE_PROBE_DONE = False
# R-fix-2: BGE 实际后端标识 —— 'torch' | 'onnx' | None。onnx 为绕过本机 torch/tokenizers
# 原生崩溃的治本后端（onnxruntime 独立原生库，已验证可加载）。
_bge_backend = None

# ====== R20: TF-IDF 确定性检索层（懒加载） ======
# 视频方法论落地：BM25/TF-IDF 作为 BGE 的 ensemble 投票层
# 当 BGE 置信度在不确定区间(0.40-0.60)时，用 TF-IDF 投票决定最终排序
_tfidf_vectorizer = None
_tfidf_matrix = None
_tfidf_skill_ids = None


def _load_tfidf():
    global _tfidf_vectorizer, _tfidf_matrix, _tfidf_skill_ids
    if _tfidf_vectorizer is not None:
        return
    from scipy import sparse
    skill_content_dir = SKILL_CONTENT
    matrix_path = os.path.join(skill_content_dir, 'tfidf_matrix.npz')
    vec_path = os.path.join(skill_content_dir, 'tfidf_vectorizer.pkl')
    ids_path = os.path.join(skill_content_dir, 'skill_ids.json')
    if not all(os.path.exists(p) for p in [matrix_path, vec_path, ids_path]):
        _tfidf_vectorizer = False  # 标记不可用
        return
    _tfidf_matrix = sparse.load_npz(matrix_path)
    verify_pickle_hash(vec_path, 'tfidf_vectorizer.pkl')
    with open(vec_path, 'rb') as f:
        _tfidf_vectorizer = restricted_loads(f.read())  # R209: 白名单受限反序列化
    verify_vectorizer_structure(_tfidf_vectorizer, _tfidf_matrix.shape[1], 'tfidf_vectorizer.pkl')
    with open(ids_path, 'r', encoding='utf-8') as f:
        _tfidf_skill_ids = json.load(f)

def tfidf_score(query, skill_names=None):
    """TF-IDF 确定性检索：返回 {skill_name: score} 字典"""
    _load_tfidf()
    if not _tfidf_vectorizer or _tfidf_matrix is None:
        return {}
    from sklearn.metrics.pairwise import cosine_similarity as _cos
    q_vec = _tfidf_vectorizer.transform([query])
    sims = _cos(q_vec, _tfidf_matrix)[0]
    if hasattr(sims, 'toarray'):
        sims = sims.toarray().flatten()
    else:
        sims = sims.flatten()
    results = {}
    for i, sid in enumerate(_tfidf_skill_ids):
        # skill_ids 格式: {"name": "xxx", "domain": "yyy"} 或纯字符串
        name = sid['name'] if isinstance(sid, dict) else (sid.split('/')[-1] if '/' in sid else sid)
        if skill_names is None or name in skill_names:
            results[name] = float(sims[i])
    return results

def ensemble_rerank(candidates, query, bge_weight=0.6, tfidf_weight=0.4):
    """BGE + TF-IDF 集成投票重排序（确定性检索层）
    仅在 BGE top1-top2 几乎并列(差<0.03) 且处于不确定区间时启用。
    保守策略：不推翻BGE明确领先的结果。
    """
    if not candidates or len(candidates) < 2:
        return candidates
    top1_score = candidates[0]['score']
    top2_score = candidates[1]['score']
    gap = top1_score - top2_score
    # 仅当几乎并列 + 不确定区间时启用
    if gap >= 0.03 or top1_score > 0.60 or top1_score < 0.35:
        return candidates
    # 获取 TF-IDF 分数
    candidate_names = {c['name'] for c in candidates}
    tfidf_scores = tfidf_score(query, candidate_names)
    if not tfidf_scores:
        return candidates
    # 归一化 TF-IDF 分数到 0-1
    max_tfidf = max(tfidf_scores.values()) if tfidf_scores else 1.0
    # R20: 最小词证阈值 — 绝对 tfidf 太弱(<0.10)说明只是停用词级重叠，
    # 归一化会把 0.067 强行抬成 1.0 制造假信号（盲测负例'起个英文名'教训）→ 不启用 ensemble
    if max_tfidf < 0.10:
        return candidates
    if max_tfidf > 0:
        tfidf_scores = {k: v / max_tfidf for k, v in tfidf_scores.items()}
    # 加权融合
    reranked = []
    for c in candidates:
        tf_score = tfidf_scores.get(c['name'], 0)
        combined = bge_weight * c['score'] + tfidf_weight * tf_score
        reranked.append({**c, 'score': round(combined, 4), 'tfidf': round(tf_score, 4)})
    reranked.sort(key=lambda x: -x['score'])
    return reranked

def _load_bge_corpus():
    """加载 BGE 语料（技能向量 + 元信息），torch/onnx 两类后端共用。"""
    global _bge_emb, _bge_skills
    if _bge_emb is not None:
        return
    # R206-01: mmap_mode='r' —— 语料只读、OS 页缓存跨冷启动复用，省每次全量读入堆内存
    import numpy as np  # P0-2: 懒导入，顶层不再缴 numpy 税
    _bge_emb = np.load(os.path.join(EVAL_DIR, 'bge_fullbody_embeddings.npy'), mmap_mode='r')
    with open(os.path.join(EVAL_DIR, 'bge_fullbody_skills.json'), 'r', encoding='utf-8') as f:
        _bge_skills = json.load(f)


def _try_load_torch_bge():
    """原后端：sentence_transformers/torch。本机 torch 原生崩溃 → 探测失败返回 False。"""
    global _bge_model, _bge_backend
    try:
        # R206-01: find_spec 替代子进程探测——torch 已卸载，原 subprocess `import torch`
        # 探测每次冷启动 fork 一个 Python 解释器（≈50-300ms）且带 10s timeout 挂死隐患；
        # find_spec 只查模块注册不执行模块代码，纳秒级且无原生崩溃面。
        # 注意：若未来重装"存在但损坏"的 torch，find_spec 会放行 → 请同时设
        # FENJUE_BGE_BACKEND=onnx 保险栓（见 _load_bge）。
        if importlib.util.find_spec('torch') is None:
            return False
    except Exception:
        return False
    try:
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        from sentence_transformers import SentenceTransformer
        cache_root = os.path.expanduser(r'~/.cache/huggingface/models--BAAI--bge-small-zh-v1.5/snapshots')
        if not os.path.isdir(cache_root):
            cache_root = os.path.expanduser(r'~/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5/snapshots')
        snap = sorted(os.listdir(cache_root))[-1]
        model_path = os.path.join(cache_root, snap)
        _bge_model = SentenceTransformer(model_path, device='cpu')
        _load_bge_corpus()
        _bge_backend = 'torch'
        return True
    except Exception:
        return False


def _try_load_onnx_bge():
    """R-fix-2 治本后端：onnxruntime 加载 BGE ONNX 权重 + 纯 Python 分词，
    零 torch / 零 tokenizers 依赖，绕过本机 torch 与 Rust tokenizers 的原生崩溃。
    已用 .npy 语料金标准验证（顺序对齐余弦 mean=0.978）：与原 torch 管线数学等价。"""
    global _bge_model, _bge_backend
    try:
        from bge_onnx_engine import BgeOnnxEncoder
        _bge_model = BgeOnnxEncoder()
        _load_bge_corpus()
        _bge_backend = 'onnx'
        print('[bge_layer] BGE 语义层已通过 onnxruntime 后端加载（torch 不可用，已绕过）',
              file=sys.stderr)
        return True
    except Exception as e:
        print(f'[bge_layer] onnx BGE 后端加载失败: {e}', file=sys.stderr)
        return False


def _load_bge():
    global _bge_model, _BGE_PROBE_DONE, _bge_backend
    # R163 测试开关: FENJUE_BGE_DISABLE=1 时跳过 BGE 加载（生产默认不设置, 行为不变）
    if os.environ.get('FENJUE_BGE_DISABLE') == '1':
        return
    if _bge_model is not None:
        return
    # R-fix: torch 探测只跑一次（见 _BGE_PROBE_DONE 说明），避免损坏时反复 fork 崩溃子进程
    if _BGE_PROBE_DONE:
        return
    _BGE_PROBE_DONE = True
    # R206-01: 后端优先级倒转——默认 onnx 治本后端优先；torch 原后端在本机
    # （system Python 3.12 仍装着 torch+transformers）import 链即烧 10-15s 且随后
    # 原生崩溃（cProfile 实测 _jit_internal/_ops/custom_ops 占 __import__ 34s/38s），
    # 降级为「显式 FENJUE_BGE_BACKEND=torch 才走」。onnx 失败且未点名 torch 时
    # 仍保留 torch 兜底（罕见路径：onnxruntime 缺失的机器），保底可路由性不变。
    forced = os.environ.get('FENJUE_BGE_BACKEND', '').strip().lower()
    if forced == 'torch':
        if _try_load_torch_bge():
            return
        print('[bge_layer] FENJUE_BGE_BACKEND=torch 但加载失败，BGE 降级 TF-IDF', file=sys.stderr)
        return
    if _try_load_onnx_bge():
        return
    # torch 兜底仅限「未显式锁定后端」时——forced='onnx' 失败不回落 torch（保险栓），
    # forced='torch' 已在上方提前返回，forced='no_torch' 显式禁用 torch。
    if not forced and _try_load_torch_bge():
        return
    # 3) 两类后端均不可用 → 留 None → bge_recall 走 TF-IDF 降级
    print('[bge_layer] torch 与 onnx 后端均不可用，BGE 降级 TF-IDF', file=sys.stderr)



# R209 P1-性能: 查询向量缓存——run_eval 全管线与 BGE-only 两次 route() 对同一 query
# 重复 encode（生产重复查询同理）。按 norm_query 键控的有界缓存；q_emb 下游仅作
# cosine 只读输入（实测 :263/:292 两处），可安全共享；encode 异常不缓存（降级路径不变）。
_QEMB_CACHE = {}
_QEMB_CACHE_MAX = 512


def _encode_query_cached(norm_query: str):
    """带缓存的查询编码：None 模型守卫与原 bge_recall 内联检查行为一致。"""
    if _bge_model is None:
        raise RuntimeError('bge model not loaded')
    q_emb = _QEMB_CACHE.get(norm_query)
    if q_emb is None:
        q_emb = _bge_model.encode([norm_query])
        if len(_QEMB_CACHE) >= _QEMB_CACHE_MAX:
            _QEMB_CACHE.clear()
        _QEMB_CACHE[norm_query] = q_emb
    return q_emb


def bge_recall(norm_query: str, tag_hits: list | None, domain: str | None, top_k: int = 5, raw_query: str | None = None) -> list:
    """L1: BGE Full-Body 召回（R150: encode 失败 → TF-IDF 确定性降级）。

    内部完成 NOT USE 负标签过滤（L1.4）与域限制兜底（L1.5）。
    返回候选列表。
    """
    # 负标签过滤沿用原始 query（与 R162 前 route() 行为一致，防同义词追加误伤）
    filter_query = raw_query if raw_query is not None else norm_query
    global FALLBACK_USED, CALL_COUNT
    with _COUNTER_LOCK:
        CALL_COUNT += 1
    # R163: 显式禁用 BGE → 直接走 TF-IDF 确定性降级（行为验证入口）
    if os.environ.get('FENJUE_BGE_DISABLE') == '1':
        with _COUNTER_LOCK:
            FALLBACK_USED = True
        return _tfidf_fallback(norm_query, filter_query, top_k)
    try:
        _load_bge()
    except Exception:
        pass  # 加载失败时模块级 _bge_model 保持 None → encode 抛异常 → TF-IDF 降级
    try:
        if _bge_model is None:  # R208 O-7: mypy None 收窄——缺模型即降级（与下方异常同路）
            raise RuntimeError('bge model not loaded')
        q_emb = _encode_query_cached(norm_query)
        bge_ok = True
    except Exception:
        bge_ok = False

    if bge_ok:
        if _bge_skills is None or _bge_emb is None:
            # R208 O-7: mypy Optional 收窄——bge_ok 时数据理应在加载态；
            # 异常态安全降级 TF-IDF（原行为此处 TypeError 崩溃）
            return _tfidf_fallback(norm_query, filter_query, top_k)
        # 决定BGE搜索范围：Tag命中→在tag匹配skill内搜索；否则→domain内搜索
        if tag_hits:
            tag_set = set(tag_hits)
            indices = [i for i, s in enumerate(_bge_skills) if s['name'] in tag_set]
            if not indices:
                # 兜底：tag命中了但skill不在bge索引中
                indices = list(range(len(_bge_skills)))
        elif domain:
            indices = [i for i, s in enumerate(_bge_skills) if s['domain'] == domain]
        else:
            indices = list(range(len(_bge_skills)))

        if not indices:
            indices = list(range(len(_bge_skills)))

        dom_emb = _bge_emb[indices]
        import numpy as np  # P0-2: 懒导入
        from sklearn.metrics.pairwise import cosine_similarity  # P0-2: 懒导入
        sims = cosine_similarity(q_emb, dom_emb)[0]
        top_indices = np.argsort(sims)[::-1][:top_k * 2]

        candidates = []
        seen = set()
        for i in top_indices:
            skill_idx = indices[i]
            name = _bge_skills[skill_idx]['name']
            if name in seen:
                continue
            seen.add(name)
            candidates.append({
                'name': name,
                'score': round(float(sims[i]), 4),
                'domain': _bge_skills[skill_idx].get('domain', 'unknown'),
                'boost': 0.0,
            })
            if len(candidates) >= top_k * 2:  # R20: 扩池，负标签过滤后再截断
                break

        # L1.4: R20 NOT USE 负标签过滤下沉到 BGE 候选层（架构修复）
        candidates = negative_filter_candidates(candidates, filter_query)

        # L1.5: 域限制兜底 — R20 改 union 合并（治"域误分类锁死候选池"）
        if domain and candidates and candidates[0]['score'] < 0.55:
            # W1#7 fix: 当 indices 已覆盖全量时复用 line 171 的 sims，避免重复 cosine 计算
            if len(indices) == len(_bge_skills):
                all_sims = sims
            else:
                all_sims = cosine_similarity(q_emb, _bge_emb)[0]
            all_top = np.argsort(all_sims)[::-1][:top_k * 2]
            existing = {c['name'] for c in candidates}
            extra = []
            for i in all_top:
                name = _bge_skills[i]['name']
                if name in existing:
                    continue
                existing.add(name)
                extra.append({
                    'name': name,
                    'score': round(float(all_sims[i]), 4),
                    'domain': _bge_skills[i].get('domain', 'unknown'),
                    'boost': 0.0,
                })
            extra = negative_filter_candidates(extra, filter_query)
            candidates = sorted(candidates + extra,
                                key=lambda c: (c.get('neg_hit', False), -c['score']))
        return candidates

    # R150/R163: BGE 不可用 → TF-IDF 全量候选降级（防路由崩溃, 保持可路由性）
    with _COUNTER_LOCK:
        FALLBACK_USED = True
    return _tfidf_fallback(norm_query, filter_query, top_k)


def _tfidf_fallback(norm_query, filter_query, top_k):
    """TF-IDF 全量候选降级（R150 原逻辑抽取为独立函数, R163 供显式开关复用）"""
    tfidf_scores = tfidf_score(norm_query)
    candidates = []
    seen = set()
    if tfidf_scores:
        for n, s in sorted(tfidf_scores.items(), key=lambda x: -x[1]):
            if s < 0.08 or n in seen:
                continue
            seen.add(n)
            candidates.append({'name': n, 'score': round(s, 4), 'domain': 'unknown', 'boost': 0.0})
            if len(candidates) >= top_k * 2:
                break
    return negative_filter_candidates(candidates, filter_query)
