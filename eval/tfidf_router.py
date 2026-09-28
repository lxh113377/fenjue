#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚠️ LEGACY（R207 P1-5 裁定，2026-09-02）⚠️
  本文件为 R162 分层重构前的历史双路由实现——运行时不被 unified_router 引用
  （L1 召回统一走 bge_layer.tfidf_score / ensemble_rerank；TF-IDF 语料加载见
  bge_layer._load_tfidf）。保留原因: ① publish toolkit 发布清单成员
  （scripts/build_publish.py SOURCES，提供独立 --tfidf/--bge CLI）；② 历史评估
  脚本引用；③ cross_layer_audit/fenjue_measure 已将本文件列入 legacy 豁免名单。
  ⛔ 新代码禁止 import 本模块；召回需求一律使用 bge_layer.tfidf_score。

tfidf_router.py — 语义路由桥接层（TF-IDF + BGE-zh 双引擎）
==========================================================
嵌入到 intent_classifier 降级链中:
  关键词 L0/L1/L2 匹配 → 未命中 → TF-IDF/BGE-zh Top-5 召回 → 返回候选 skill

用法（独立运行）:
  python tfidf_router.py "检查路由有没有毛病"          # 默认 BGE-zh
  python tfidf_router.py --tfidf "检查路由有没有毛病"   # TF-IDF 引擎
  python tfidf_router.py --bge "检查路由有没有毛病"     # BGE-zh 引擎
  → 返回 Top-5 skill 名 + 相似度分数

集成方式:
  在 intent_classifier_canonical.md 降级链 Step 4 后增加:
  "若 L0-L2 关键词均未命中 → 调用 tfidf_router.py <query> → 取 Top-3 注入 L3 LLM 精选"
"""
import json
import os
import sys
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from scipy import sparse
from index_integrity import restricted_loads, verify_pickle_hash, verify_vectorizer_structure
from config import SKILL_CONTENT


# 单例缓存
_vec = None
_mat = None
_idx = None

def _ensure_loaded():
    global _vec, _mat, _idx
    if _vec is None:
        mpath = os.path.join(SKILL_CONTENT, "tfidf_matrix.npz")
        vpath = os.path.join(SKILL_CONTENT, "tfidf_vectorizer.pkl")
        ipath = os.path.join(SKILL_CONTENT, "skill_ids.json")
        if not all(os.path.exists(p) for p in [mpath, vpath, ipath]):
            raise FileNotFoundError("TF-IDF 索引未构建! 先运行: python eval/build_indexes.py --apply")
        _mat = sparse.load_npz(mpath)
        verify_pickle_hash(vpath, "tfidf_vectorizer.pkl")
        with open(vpath, "rb") as f:
            _vec = restricted_loads(f.read())  # R209: 白名单受限反序列化
        verify_vectorizer_structure(_vec, _mat.shape[1], "tfidf_vectorizer.pkl")
        with open(ipath, encoding="utf-8") as _f:
            _idx = json.load(_f)

def route(query, top_k=5, threshold=0.08):
    """
    TF-IDF 语义路由入口
    
    参数:
      query: 用户输入文本
      top_k: 返回前 K 个候选
      threshold: 最低相似度阈值（0.08≈宽松, 0.15≈保守）
    
    返回:
      [{"name": "skill-name", "score": 0.xx, "domain": "xxx"}, ...]
    """
    _ensure_loaded()
    q_vec = _vec.transform([query])
    sims = cosine_similarity(q_vec, _mat)[0]
    top = np.argsort(sims)[::-1][:top_k * 2]  # 多取些用于去重
    
    results = []
    seen = set()
    for i in top:
        if sims[i] < threshold:
            continue
        name = _idx[i]["name"]
        if name in seen:
            continue
        seen.add(name)
        results.append({
            "name": name,
            "score": round(float(sims[i]), 4),
            "domain": _idx[i]["domain"]
        })
        if len(results) >= top_k:
            break
    return results

def hybrid_route(query, keyword_matches=None, top_k=5):
    """
    混合路由: 关键词优先 + TF-IDF 补充
    
    参数:
      query: 用户输入
      keyword_matches: 关键词匹配结果 [skill_name, ...]（可选）
      top_k: 最多返回 K 个
    
    返回:
      合并去重后的候选列表
    """
    tfidf = route(query, top_k=top_k)
    kw = keyword_matches or []
    
    result = []
    seen = set()
    
    # 关键词结果优先
    for name in kw:
        if name not in seen:
            result.append({"name": name, "score": 1.0, "source": "keyword"})
            seen.add(name)
    
    # TF-IDF 补充（去重，降权为 0.5 标记来源）
    for r in tfidf:
        if r["name"] not in seen:
            r["source"] = "tfidf"
            r["score"] = r["score"] * 0.5  # 标记为非精确匹配
            result.append(r)
            seen.add(r["name"])
    
    return result[:top_k]

# ====== BGE-zh Full-Body Router ======
_bge_emb = None
_bge_skills = None
_bge_model = None

def _ensure_bge_loaded():
    """加载 Full-Body BGE-zh 索引（懒加载，首次调用时初始化）"""
    global _bge_emb, _bge_skills, _bge_model
    if _bge_emb is None:
        eval_dir = os.path.dirname(os.path.abspath(__file__))
        emb_path = os.path.join(eval_dir, 'bge_fullbody_embeddings.npy')
        skills_path = os.path.join(eval_dir, 'bge_fullbody_skills.json')
        
        if not os.path.exists(emb_path):
            raise FileNotFoundError(
                f"BGE full-body index not found: {emb_path}\n"
                "Run: python eval/build_indexes.py --apply first"
            )
        
        import os as _os
        _os.environ['HF_HUB_OFFLINE'] = '1'
        _os.environ['TRANSFORMERS_OFFLINE'] = '1'
        
        from sentence_transformers import SentenceTransformer
        cache_dir = _os.path.expanduser(r'~/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5')
        snap = sorted(_os.listdir(_os.path.join(cache_dir, 'snapshots')))[-1]
        model_path = _os.path.join(cache_dir, 'snapshots', snap)
        
        _bge_model = SentenceTransformer(model_path, device='cpu')
        _bge_emb = np.load(emb_path)
        with open(skills_path, 'r', encoding='utf-8') as f:
            _bge_skills = json.load(f)

def bge_route(query, top_k=5, domain=None):
    """
    BGE-zh Full-Body 语义路由 (推荐)
    
    参数:
      query: 用户输入
      top_k: 返回前K个
      domain: 限定领域（None=全局搜索）
    
    返回: [{"name","score","domain"},...]
    """
    _ensure_bge_loaded()
    
    q_emb = _bge_model.encode([query])
    sims = cosine_similarity(q_emb, _bge_emb)[0]
    
    # Filter by domain if specified
    if domain:
        candidates = [(i, sims[i]) for i, s in enumerate(_bge_skills) if s['domain'] == domain]
    else:
        candidates = [(i, sims[i]) for i in range(len(sims))]
    
    candidates.sort(key=lambda x: -x[1])
    
    results = []
    seen = set()
    for i, score in candidates[:top_k * 2]:
        name = _bge_skills[i]['name']
        if name in seen:
            continue
        seen.add(name)
        results.append({
            'name': name,
            'score': round(float(score), 4),
            'domain': _bge_skills[i]['domain'],
            'source': 'bge-fullbody'
        })
        if len(results) >= top_k:
            break
    
    return results

def smart_route(query, top_k=5):
    """
    智能路由: BGE-zh (优先) + TF-IDF 回退
    """
    try:
        return bge_route(query, top_k=top_k)
    except (FileNotFoundError, ImportError):
        return route(query, top_k=top_k)


# ====== 三级路由管道 (Three-Stage Pipeline) ======
# Bilibili方法论: L0规则→L1语义→L2 LLM决策
# Stage 1: 域分类 (classify_domain)
# Stage 2: BGE-zh 语义召回 (bge_route)
# Stage 3: LLM 精选 (build_llm_prompt → external LLM)

def build_skill_profile(name, max_desc=300):
    """
    为 LLM 决策构建 skill 结构化描述
    返回: {name, domain, desc, triggers, not_for, url}
    """
    import os as _os
    skills_dir = r'<SKILLS_ROOT>'
    sc = r'<MEMORY_ROOT>\skill_content'
    
    profile = {
        'name': name,
        'domain': 'unknown',
        'desc': '',
        'triggers': [],
        'not_for': [],
    }
    
    # 从 skill_content JSON 取元数据
    for df in _os.listdir(sc):
        if not df.endswith('.json') or df == 'skill_ids.json':
            continue
        with open(_os.path.join(sc, df), 'r', encoding='utf-8') as f:
            data = json.load(f)
            for s in data.get('skills', []):
                if s.get('name') == name:
                    profile['domain'] = df.replace('.json', '')
                    profile['triggers'] = s.get('triggers', [])
                    break
        if profile['domain'] != 'unknown':
            break
    
    # 从 SKILL.md 取描述
    md_path = _os.path.join(skills_dir, name, 'SKILL.md')
    if _os.path.exists(md_path):
        with open(md_path, 'r', encoding='utf-8') as f:
            body = f.read()
        
        # 跳过 YAML frontmatter
        if body.startswith('---'):
            end = body.find('---', 3)
            if end > 0:
                body = body[end + 3:].strip()
        
        # 提取描述（跳过标题行）
        lines = body.split('\n')
        desc_parts = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            desc_parts.append(stripped)
            if len(' '.join(desc_parts)) > max_desc:
                break
        profile['desc'] = ' '.join(desc_parts)
        
        # 提取别用我
        for line in body.split('\n'):
            if '【别用我】' in line:
                profile['not_for'].append(line.strip())
    
    return profile


def three_stage_route(query, top_k=5, domain=None):
    """
    三级路由管道（完整版）
    
    Stage 1: L0 域分类 (classify_domain)
    Stage 2: BGE-zh 语义召回 Top-K
    Stage 3: 构建 LLM 决策提示词
    
    返回: {
        'stage1_domain': str,
        'stage2_candidates': [...],
        'stage3_llm_prompt': str,  # 可直接喂给LLM的决策提示词
        'selected': str,           # BGE Top-1（LLM未介入时的默认选择）
    }
    """
    # Import domain classifier (avoid circular)
    try:
        from domain_classifier import classify_domain
    except ImportError:
        def classify_domain(q):
            return None
    
    # Stage 1: 域分类
    detected_domain = domain or classify_domain(query)
    
    # Stage 2: BGE-zh 语义召回
    candidates = bge_route(query, top_k=top_k, domain=detected_domain)
    if not candidates:
        candidates = bge_route(query, top_k=top_k)  # fallback: no domain filter
    
    # Stage 3: 构建 LLM 提示词
    profiles = []
    for c in candidates[:top_k]:
        p = build_skill_profile(c['name'])
        profiles.append((c, p))
    
    # 构建 LLM 决策提示词
    candidate_lines = []
    for i, (c, p) in enumerate(profiles, 1):
        triggers_str = ', '.join(p['triggers'][:5]) if p['triggers'] else '(无)'
        not_for_str = '; '.join(p['not_for'][:2]) if p['not_for'] else '(无)'
        desc_str = p['desc'][:200] if p['desc'] else '(无描述)'
        
        candidate_lines.append(
            f"{i}. **{p['name']}** (领域:{p['domain']}, 相似度:{c['score']:.3f})\n"
            f"   描述: {desc_str}\n"
            f"   触发词: {triggers_str}\n"
            f"   不适用: {not_for_str}"
        )
    
    system_prompt = """你是 Skill 路由决策器。根据用户查询，从候选 Skill 中选择最匹配的一个。

决策规则（按优先级）:
1. 触发词优先 — 查询中包含某skill的触发词，权重最高
2. 意图理解 — "报错怎么修"→debugging, "项目交接"→handoff, "咋装"→install
3. 注意不适用场景 — 候选标注了"NOT USE WHEN X"且查询匹配X → 排除
4. 口语化理解 — "拆小"=拆分, "上线"=部署, "画个图"=图表
5. 输出格式: **只输出 skill 名称，不要解释。**"""

    user_prompt = f"""用户查询: "{query}"

候选 Skill (按语义相似度排序):
{chr(10).join(candidate_lines)}

请选择最匹配用户意图的 Skill。只输出名称。"""

    return {
        'stage1_domain': detected_domain,
        'stage2_candidates': candidates,
        'stage3_llm_prompt': f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}",
        'selected': candidates[0]['name'] if candidates else None,
    }


# ---- CLI ----
if __name__ == "__main__":
    engine = 'bge'
    three_stage = False
    args = sys.argv[1:]
    
    if '--tfidf' in args:
        engine = 'tfidf'
        args.remove('--tfidf')
    elif '--bge' in args:
        engine = 'bge'
        args.remove('--bge')
    elif '--three-stage' in args or '--llm' in args:
        three_stage = True
        if '--three-stage' in args:
            args.remove('--three-stage')
        if '--llm' in args:
            args.remove('--llm')
    
    if len(args) < 1:
        print("用法: python tfidf_router.py [--tfidf|--bge|--three-stage] <查询文本>")
        print("  --tfidf       TF-IDF 引擎 (Top-1=28.9%)")
        print("  --bge         BGE-zh Full-Body (推荐, Top-1=75.6%)")
        print("  --three-stage 三级路由: 域分类+BGE召回+LLM决策提示词")
        print("示例: python tfidf_router.py \"检查路由有没有毛病\"")
        sys.exit(1)
    
    query = ' '.join(args)
    
    if three_stage:
        result = three_stage_route(query)
        print(f"查询: {query}")
        print(f"Stage 1 — 域分类: {result['stage1_domain']}")
        print("Stage 2 — BGE 召回 (Top-5):")
        for i, c in enumerate(result['stage2_candidates'], 1):
            print(f"  {i}. {c['name']:<40} {c['score']:.4f}  ({c['domain']})")
        print(f"Stage 2 — 默认选择: {result['selected']}")
        print(f"\n{'='*70}")
        print("Stage 3 — LLM 决策提示词 (复制以下内容发给 LLM):")
        print(f"{'='*70}")
        print(result['stage3_llm_prompt'])
    elif engine == 'bge':
        try:
            results = bge_route(query)
        except Exception as e:
            print(f"BGE Error: {e}")
            print("Falling back to TF-IDF...")
            results = route(query)
        print(f"查询: {query}  (引擎: {engine})")
        print(f"{'排名':<6} {'Skill':<40} {'相似度':>6} {'领域':<15}")
        print("-" * 72)
        for i, r in enumerate(results, 1):
            print(f"{i:<6} {r['name']:<40} {r['score']:>6.4f} {r['domain']:<15}")
        if not results:
            print("  (无匹配)")
    else:
        results = route(query)
        print(f"查询: {query}  (引擎: {engine})")
        print(f"{'排名':<6} {'Skill':<40} {'相似度':>6} {'领域':<15}")
        print("-" * 72)
        for i, r in enumerate(results, 1):
            print(f"{i:<6} {r['name']:<40} {r['score']:>6.4f} {r['domain']:<15}")
        if not results:
            print("  (无匹配)")
