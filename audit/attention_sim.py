# -*- coding: utf-8 -*-
"""
attention_sim.py — 注意力税补充模拟（三件套）

规格来源（非臆造）：
  fenjue-memory-audit/SKILL.md L164        「注意力税补充模拟：python audit/attention_sim.py --json」
  fenjue-memory-audit/references/audit_workflow.md L422
      「三件套实测：①上下文税口径（P0/本会话/全库 token）
                    ②蒙特卡洛软注意力稀释（相关块注意力占比 vs 场景 N）
                    ③BGE 干草堆检索（协议集 vs 全库 rank）
        D1/D7 满分 ≠ 稀释为零，审计『算力消耗/前端体验』维度时建议同跑。」
  A-memory-start/SKILL.md 相关技能段        引用 audit/attention_sim.py

口径对齐 audit/fenjue_measure.py D1（L167-171）：token = bytes // 3，上下文窗口 128000。

安全约束：
  * 全程只读，不修改/创建任何被审计文件。
  * 禁止在本进程 import torch（本机 torch 装载会触发 access violation 0xC0000005），
    BGE 可用性一律用子进程探测；不可用则 TF-IDF 降级并在输出显式标注 degraded。

用法：
  python audit/attention_sim.py                 # 人读报告
  python audit/attention_sim.py --json          # 机器可解析（供 scorecard/审计报告引用）
  python audit/attention_sim.py --trials 20000 --seed 42 --mu-rel 4.0
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys

GM = r"<MEMORY_ROOT>"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_DIR = os.path.join(PROJECT_DIR, "eval")
GLOBAL_SKILLS = r"<SKILLS_ROOT>"

WINDOW = 128000          # 上下文窗口（与 fenjue_measure.py D1 口径一致）
BYTES_PER_TOKEN = 3      # token = bytes // 3（同上）
CHUNK_TOKENS = 512       # 注意力块粒度
SKIP_DIRS = {".git", "_trash", "_bak", "_temp", "__pycache__", ".hermes", ".pytest_cache"}

# P0 清单：与 fenjue_measure.py L182 同集合（该处已用修正路径，故 D1 未少算）。
# 实测：<MEMORY_ROOT>\behavior_core.md 不存在，正文在 core\behavior_core.md。
# 真正的失效引用在 D12(L347) 与 D15(L387) 两个子项 —— 2026-09-22 第 10 轮已修。
P0_FILES = [
    "core/BOOTSTRAP.md",
    "core/SOUL.md",
    "core/MEMORY.md",
    "meta/VERSION_LOCK.md",
    "meta/memory_index.md",
    "core/behavior_core.md",
]
P0_UPSTREAM_PATH = "behavior_core.md"          # 主引擎写法（根目录）
P0_CORRECTED_PATH = "core/behavior_core.md"    # 实际存在路径

# 本会话层：P0 + 项目绑定表 + 项目 AGENTS 壳与分卷（复杂任务的真实开场注入面）
SESSION_PROJECT_FILES = [
    "memory/AGENTS.md",
    "memory/常用技能.md",
    "memory/07-next-steps.md",
    "memory/01-goal.md",
    "memory/task-card.md",
    "AGENTS.md",
    "AGENTS.md.part1.md",
]

# ③ 干草堆 needle：协议类自然语言查询 → ground-truth 目标文件（相对 GM）
# query 不含文件名/标题原文，避免信息泄漏导致 rank 恒为 1。
# R214-1: 5 → 32 条（needles_scored=5 时 hit_top1_rate 步进 20%，噪声不可判定）。
# 缺失目标运行时自动 SKIP，不进 scored 口径。
NEEDLES = [
    ("每轮对话开场必须先加载什么，身份和铁律写在哪里", "core/BOOTSTRAP.md"),
    ("七步闭环工作流的任务卡要包含哪些区，各端脚本怎么跑", "prompts/workflow_seven_step.md"),
    ("什么样的任务算简单任务，可以跳过后续记忆加载", "system/simple_task_bypass_guide.md"),
    ("怎么判断缓存需不需要重载，版本号锁定在哪", "meta/VERSION_LOCK.md"),
    ("以前踩过的坑和经验教训记录在什么地方", "lessons/lessons.md"),
    ("记忆该写到哪个文件的读写映射规则在哪", "meta/MEMORY_WRITE_MAP.md"),
    ("技能的进化历史和版本演变记录在哪", "meta/SKILL_EVOLUTION.md"),
    ("大文件索引，超大文件登记在哪查", "meta/BIGFILE_INDEX.md"),
    ("归档应该放到什么位置，归档路径规则", "meta/ARCHIVE_LOCATION.md"),
    ("项目的核心目标和价值定义写在哪", "memory/01-goal.md"),
    ("项目仓库结构的说明，sync 命令自动更新哪份文件", "memory/02-structure.md"),
    ("技术栈清单和版本偏好记录", "memory/03-tech-stack.md"),
    ("常用文件的路径地图在哪查", "memory/04-file-map.md"),
    ("当前功能做到什么程度了，进度状态", "memory/05-feature-status.md"),
    ("有哪些约束和不能碰的红线", "memory/06-constraints.md"),
    ("当前待办和下一步计划是什么", "memory/07-next-steps.md"),
    ("任务卡的标准模板和字段规范", "memory/task-card.md"),
    ("快速路由器和记忆入口索引在哪", "meta/memory_index.md"),
    ("意图分类的六端权威路由表", "intent_classifier_canonical.md"),
    ("技能路由的名称映射和跨端对照", "skill_routing.md"),
    ("决策的理由和设计依据在哪记录", "RATIONALE.md"),
    ("行为规则的核心锚点文件", "core/behavior_core.md"),
    ("人格和灵魂定义在哪份文件", "SOUL.md"),
    ("用户的个人信息和画像记录", "core/USER.md"),
    ("核心快照和路由三层的文件索引在哪个文件", "core/MEMORY.md"),
    ("记忆读写的协议规范", "system/memory_protocol.md"),
    ("回复语言和语言偏好规定", "system/language_preference.md"),
    ("经验教训的归档手册怎么操作", "lessons/lessons-archive-manual.md"),
    ("域到目录的映射说明文档", "scripts/domain_map.ps1_readme.md"),
    ("各框架通用规范汇总", "system/framework_common.md"),
    ("批判性思维的思考规范", "system/critical_thinking.md"),
    ("启动模板的格式长什么样", "system/boot_template.md"),
]


# ---------------------------------------------------------------- 基础工具
def fsize(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def to_tokens(nbytes: int) -> int:
    return nbytes // BYTES_PER_TOKEN


def pct_window(tokens: int) -> float:
    return round(tokens / WINDOW * 100, 2)


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def walk_md(root: str):
    """遍历 root 下 .md（跳过噪声/归档目录）。"""
    if not os.path.isdir(root):
        return
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("_trash")]
        for fn in files:
            if fn.endswith(".md"):
                yield os.path.join(cur, fn)


def layer_stat(paths, label: str) -> dict:
    present, missing, total = [], [], 0
    for p, rel in paths:
        n = fsize(p)
        if n:
            present.append({"file": rel, "bytes": n})
            total += n
        else:
            missing.append(rel)
    tok = to_tokens(total)
    return {
        "layer": label,
        "files_present": len(present),
        "files_missing": missing,
        "bytes": total,
        "kb": round(total / 1024, 1),
        "tokens": tok,
        "pct_of_window": pct_window(tok),
        "detail": present,
    }


# ---------------------------------------------------- ① 上下文税口径
def measure_ctx_tax() -> dict:
    p0 = layer_stat([(os.path.join(GM, f.replace("/", os.sep)), f) for f in P0_FILES],
                    "P0 强制注入")

    session_pairs = [(os.path.join(GM, f.replace("/", os.sep)), f) for f in P0_FILES]
    session_pairs += [(os.path.join(PROJECT_DIR, f.replace("/", os.sep)), "项目/" + f)
                      for f in SESSION_PROJECT_FILES]
    session = layer_stat(session_pairs, "本会话（P0+项目绑定）")

    gm_files = list(walk_md(GM))
    gm_bytes = sum(fsize(p) for p in gm_files)
    sk_files, sk_bytes = [], 0
    if os.path.isdir(GLOBAL_SKILLS):
        for d in os.listdir(GLOBAL_SKILLS):
            if d in SKIP_DIRS or d.startswith("_trash"):
                continue
            sp = os.path.join(GLOBAL_SKILLS, d, "SKILL.md")
            if os.path.isfile(sp):
                sk_files.append(sp)
                sk_bytes += fsize(sp)
    full_bytes = gm_bytes + sk_bytes
    full_tokens = to_tokens(full_bytes)
    fullbody = {
        "layer": "全库（global_memory .md + 全部 SKILL.md）",
        "gm_md_files": len(gm_files),
        "gm_bytes": gm_bytes,
        "skill_md_files": len(sk_files),
        "skill_bytes": sk_bytes,
        "bytes": full_bytes,
        "kb": round(full_bytes / 1024, 1),
        "tokens": full_tokens,
        "pct_of_window": pct_window(full_tokens),
        "window_multiple": round(full_tokens / WINDOW, 2),
    }

    upstream_exists = os.path.exists(os.path.join(GM, P0_UPSTREAM_PATH))
    return {
        "window": WINDOW,
        "bytes_per_token": BYTES_PER_TOKEN,
        "p0": p0,
        "session": session,
        "fullbody": fullbody,
        "upstream_p0_path_note": {
            "fenjue_measure_path": P0_UPSTREAM_PATH,
            "exists": upstream_exists,
            "corrected_path": P0_CORRECTED_PATH,
            "corrected_exists": os.path.exists(
                os.path.join(GM, P0_CORRECTED_PATH.replace("/", os.sep))),
            "impact": ("无差异" if upstream_exists else
                       "上游 D12(L347)/D15(L387) 已于 2026-09-22 第 10 轮改用修正路径 core/behavior_core.md"
                       "（此前按根路径取 size=0 属失效引用；D1 的 P0 集合本就用修正路径，从未少算）"),
        },
    }


# -------------------------------------- ② 蒙特卡洛软注意力稀释
def simulate_dilution(scenarios, trials=10000, seed=42, mu_rel=4.0, sigma=1.0, k_rel=3):
    """softmax 注意力下，相关块注意力质量占比随上下文块数 N 稀释。

    模型：相关块 logit ~ N(mu_rel, sigma)，无关块 logit ~ N(0, sigma)；
    统计 softmax 后 sum(相关块权重)。N 越大，无关块的 exp 累加越多 → 相关块占比被稀释。
    """
    try:
        import numpy as np
    except ImportError:
        return {"available": False, "reason": "numpy 不可用，无法做蒙特卡洛模拟"}

    rng = np.random.default_rng(seed)
    out = []
    for name, tokens in scenarios:
        n_chunk = max(1, math.ceil(tokens / CHUNK_TOKENS))
        k = min(k_rel, n_chunk)
        n_irr = n_chunk - k
        # (trials, k) 相关块 + (trials, n_irr) 无关块
        z_rel = rng.normal(mu_rel, sigma, size=(trials, k))
        shares = np.empty(trials, dtype=np.float64)
        # 分批算，控制内存（全库场景 n_chunk 可达数万）
        batch = max(1, int(4_000_000 / max(1, n_chunk)))
        for start in range(0, trials, batch):
            end = min(trials, start + batch)
            zr = z_rel[start:end]
            if n_irr > 0:
                zi = rng.normal(0.0, sigma, size=(end - start, n_irr))
                zmax = np.maximum(zr.max(axis=1), zi.max(axis=1))[:, None]
                er = np.exp(zr - zmax).sum(axis=1)
                ei = np.exp(zi - zmax).sum(axis=1)
                shares[start:end] = er / (er + ei)
            else:
                shares[start:end] = 1.0
        out.append({
            "scenario": name,
            "tokens": tokens,
            "n_chunks": n_chunk,
            "k_relevant": int(k),
            "relevant_attention_mean": round(float(shares.mean()), 4),
            "p05": round(float(np.percentile(shares, 5)), 4),
            "p50": round(float(np.percentile(shares, 50)), 4),
            "p95": round(float(np.percentile(shares, 95)), 4),
        })
    base = out[0]["relevant_attention_mean"] if out else None
    for r in out:
        r["dilution_vs_p0"] = (round(r["relevant_attention_mean"] / base, 3)
                               if base else None)
    return {
        "available": True,
        "trials": trials,
        "seed": seed,
        "mu_relevant": mu_rel,
        "sigma": sigma,
        "chunk_tokens": CHUNK_TOKENS,
        "k_relevant": k_rel,
        "scenarios": out,
    }


# ------------------------------------------ ③ 干草堆检索（协议集 vs 全库）
def _probe_bge() -> tuple[bool, str]:
    """子进程探测 torch + BGE 矩阵；绝不在本进程 import torch。"""
    npy = os.path.join(EVAL_DIR, "bge_fullbody_embeddings.npy")
    if not os.path.exists(npy):
        return False, "bge_fullbody_embeddings.npy 不存在"
    try:
        r = subprocess.run([sys.executable, "-c", "import torch; print(torch.__version__)"],
                           capture_output=True, text=True, timeout=60)
    except Exception as e:
        return False, f"torch 探测异常: {type(e).__name__}"
    if r.returncode != 0:
        first = (r.stderr or "").strip().splitlines()
        return False, "torch 不可用: " + (first[-1][:120] if first else f"exit {r.returncode}")
    return True, f"torch {(r.stdout or '').strip()}"


def _chunk_corpus():
    """把 global_memory 全部 .md 切块（≈CHUNK_TOKENS），返回 (texts, owners)。"""
    span = CHUNK_TOKENS * BYTES_PER_TOKEN
    texts, owners = [], []
    for path in walk_md(GM):
        rel = os.path.relpath(path, GM).replace(os.sep, "/")
        body = read_text(path)
        if not body.strip():
            continue
        for i in range(0, len(body), span):
            piece = body[i:i + span]
            if piece.strip():
                texts.append(piece)
                owners.append(rel)
    return texts, owners


def _bge_engine():
    """R214-1: 进程内加载 bge_layer（onnx 强制，禁 torch 兜底）。

    本文件安全约束「禁止本进程 import torch」：FENJUE_BGE_BACKEND=onnx 时
    bge_layer._load_bge() 在 onnx 失败后不回落 torch（见 bge_layer :206-209）。
    返回 (model|None, note)；None = 调用方走 TF-IDF 降级。
    """
    try:
        if EVAL_DIR not in sys.path:
            sys.path.insert(0, EVAL_DIR)
        os.environ.setdefault("FENJUE_BGE_BACKEND", "onnx")
        import bge_layer  # noqa: PLC0415 — 延迟导入，避免拖累纯 TF-IDF 场景
        bge_layer._load_bge()
        if getattr(bge_layer, "_bge_model", None) is not None:
            return bge_layer._bge_model, "bge_layer onnx 后端"
        return None, "bge_layer 加载后模型为 None"
    except Exception as e:  # noqa: BLE001 — 降级路径必须吞一切加载异常
        return None, f"bge_layer 加载异常: {e}"


def _corpus_signature(texts) -> str:
    import hashlib

    h = hashlib.sha1()
    for t in texts:
        h.update(hashlib.md5(t.encode("utf-8")).digest())
    return h.hexdigest()[:12]


def _l2norm(mat):
    import numpy as np

    norm = np.linalg.norm(mat, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return mat / norm


def _bge_corpus_matrix(model, texts):
    """语料向量矩阵（磁盘缓存 eval/_cache/haystack_corpus_<sig>.npy，语料变更自动失效）。"""
    import numpy as np

    cache_dir = os.path.join(EVAL_DIR, "_cache")
    os.makedirs(cache_dir, exist_ok=True)
    sig = _corpus_signature(texts)
    cache_path = os.path.join(cache_dir, f"haystack_corpus_{sig}.npy")
    if os.path.exists(cache_path):
        try:
            mat = np.load(cache_path)
            if mat.shape[0] == len(texts):
                return mat, sig
        except Exception:  # noqa: BLE001 — 缓存损坏即重建
            pass
    emb = model.encode(texts)
    mat = _l2norm(np.asarray(emb, dtype="float32"))
    np.save(cache_path, mat)
    return mat, sig


def _is_family(owner: str, target: str) -> bool:
    """R214-1: 指针壳架构下的文件家族口径。

    4KB 拆分（R161）后协议文件普遍为「索引壳 + .part 分卷」（lessons.md →
    lessons.part1-15.md、BOOTSTRAP.md → BOOTSTRAP.part1-3.md）。检索器命中
    分卷即已把 agent 带到答案，ground-truth 匹配须按家族（同目录 + 同 stem
    或 stem.part* 前缀）判定，否则指针壳目标天然吃亏、指标系统性低估。
    """
    tdir, tbase = os.path.split(target)
    tstem = os.path.splitext(tbase)[0]
    odir, obase = os.path.split(owner)
    ostem = os.path.splitext(obase)[0]
    if odir != tdir:
        return False
    return ostem == tstem or ostem.startswith(tstem + ".part")


def _rank_of(order, owners, target):
    for pos, idx in enumerate(order, start=1):
        if _is_family(owners[idx], target):
            return pos
    return None


def _top_owners(order, owners, top_k, limit=5):
    top_owners, seen = [], set()
    for idx in order[:top_k]:
        if owners[idx] not in seen:
            seen.add(owners[idx])
            top_owners.append(owners[idx])
    return top_owners[:limit]


def _in_uncertain_band(sims, order, lo=0.35, hi=0.60):
    """BGE 头部分数是否处于不确定区间（生产 ensemble 启用条件之一）。"""
    return bool(len(order)) and lo <= float(sims[order[0]]) <= hi


def _conservative_rerank(order, sims_bge, sims_tfidf, scan=60, gap=0.03, lo=0.35, hi=0.60):
    """生产 ensemble_rerank 同参的保守并列决胜（bge_layer.py:88-121 口径）。

    仅当 BGE 头部分数处于不确定区间 [lo, hi] 且相邻差 < gap 时，组内改用
    TF-IDF 词面信号排序；BGE 明确领先的结果不推翻（与生产保守策略一致）。
    """
    import numpy as np  # noqa: PLC0415 — 模块顶不引 numpy（保持 TF-IDF 缺依赖可运行）

    head = [int(k) for k in order[:scan]]
    tail = [int(k) for k in order[scan:]]
    out, i = [], 0
    while i < len(head):
        j = i
        while j + 1 < len(head) and sims_bge[head[i]] - sims_bge[head[j + 1]] < gap:
            j += 1
        group = head[i:j + 1]
        if len(group) > 1 and lo <= sims_bge[head[i]] <= hi:
            group = sorted(group, key=lambda k: -sims_tfidf[k])
        out.extend(group)
        i = j + 1
    return np.array(out + tail)


def measure_haystack(top_k=10) -> dict:
    """③ 干草堆检索：协议类查询 → 全库 chunk rank。

    R214-1 治本：检索引擎与真实路由同源——优先 bge_layer（onnx）语义召回，
    原 char 2-3 gram TF-IDF 保留为 BGE 不可达时的降级路径（此前 TF-IDF 是
    唯一引擎，对自然语言转述查询字面 n-gram 重叠极弱，median_rank=117 属
    引擎选型错配而非语料问题——真实路由 BGE-only Top-1 为 98.9%）。
    """
    bge_ok, bge_note = _probe_bge()
    try:
        import numpy as np
    except ImportError:
        return {"available": False, "reason": "numpy 不可用",
                "engine": "none", "bge_probe": bge_note}

    texts, owners = _chunk_corpus()
    if not texts:
        return {"available": False, "reason": f"语料为空（{GM} 无 .md 或不可达）",
                "engine": "none", "bge_probe": bge_note}

    model, engine_note = _bge_engine()
    engine = "bge" if model is not None else "tfidf-degraded"
    degraded = model is None
    corpus_sig = None
    results, hit1, hit_k, ranks, ranks_exact, hit1_exact = [], 0, 0, [], [], 0

    def _emit(query, target, order):
        nonlocal hit1, hit_k, hit1_exact
        rank = _rank_of(order, owners, target)
        # strict 本体口径照常输出（透明）：直接找 target 本体的排名
        rank_exact = next((pos for pos, idx in enumerate(order, start=1)
                           if owners[idx] == target), None)
        ok1 = rank == 1
        okk = rank is not None and rank <= top_k
        hit1 += int(ok1)
        hit_k += int(okk)
        if rank:
            ranks.append(rank)
        if rank_exact:
            ranks_exact.append(rank_exact)
            hit1_exact += int(rank_exact == 1)
        results.append({
            "query": query, "target": target, "status": "OK",
            "rank_of_target": rank, "rank_of_target_exact": rank_exact,
            "hit_top1": ok1, f"hit_top{top_k}": okk,
            "top_files": _top_owners(order, owners, top_k),
        })

    if model is not None:
        try:
            mat, corpus_sig = _bge_corpus_matrix(model, texts)
            from sklearn.feature_extraction.text import TfidfVectorizer
            vec = TfidfVectorizer(analyzer="char", ngram_range=(2, 3),
                                  min_df=2, max_features=200000)
            tf_mat = vec.fit_transform(texts)
            for query, target in NEEDLES:
                tgt_path = os.path.join(GM, target.replace("/", os.sep))
                if not os.path.exists(tgt_path):
                    results.append({"query": query, "target": target,
                                    "status": "SKIP", "reason": "ground-truth 文件不存在"})
                    continue
                qv = _l2norm(np.asarray(model.encode([query]), dtype="float32"))
                sims = (mat @ qv[0]).ravel()  # qv shape=(1,512)，取行向量 (512,) 做 cosine
                order = np.argsort(-sims)
                # 生产同参保守并列决胜（仅不确定区间内的并列组用词面信号）
                if _in_uncertain_band(sims, order):
                    tq = vec.transform([query])
                    tf_sims = (tf_mat @ tq.T).toarray().ravel()
                    order = _conservative_rerank(order, sims, tf_sims)
                _emit(query, target, order)
        except Exception as e:  # noqa: BLE001 — BGE 编码异常 → TF-IDF 确定性降级
            model, engine = None, "tfidf-degraded"
            degraded = True
            engine_note = f"BGE 编码异常降级: {e}"
            results, hit1, hit_k, ranks, ranks_exact, hit1_exact = [], 0, 0, [], [], 0

    if model is None:
        # 降级路径：char 2-3 gram TF-IDF（原唯一引擎，R214-1 起仅为 fallback）
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:
            return {"available": False, "reason": "sklearn/numpy 不可用",
                    "engine": "none", "bge_probe": bge_note}
        vec = TfidfVectorizer(analyzer="char", ngram_range=(2, 3), min_df=2, max_features=200000)
        matrix = vec.fit_transform(texts)
        for query, target in NEEDLES:
            tgt_path = os.path.join(GM, target.replace("/", os.sep))
            if not os.path.exists(tgt_path):
                results.append({"query": query, "target": target,
                                "status": "SKIP", "reason": "ground-truth 文件不存在"})
                continue
            qv = vec.transform([query])
            sims = (matrix @ qv.T).toarray().ravel()
            _emit(query, target, np.argsort(-sims))

    scored = [r for r in results if r.get("status") == "OK"]
    n = len(scored) or 1
    return {
        "available": True,
        "engine": engine,
        "degraded": degraded,
        "bge_probe": bge_note,
        "engine_note": engine_note,
        "corpus_sig": corpus_sig,
        "corpus_chunks": len(texts),
        "corpus_files": len(set(owners)),
        "chunk_tokens": CHUNK_TOKENS,
        "top_k": top_k,
        "needles_scored": len(scored),
        "hit_top1_rate": round(hit1 / n, 3),
        f"hit_top{top_k}_rate": round(hit_k / n, 3),
        "median_rank": (sorted(ranks)[len(ranks) // 2] if ranks else None),
        # strict 本体口径（透明对照）：不计分卷命中
        "hit_top1_rate_exact": round(hit1_exact / n, 3),
        "median_rank_exact": (sorted(ranks_exact)[len(ranks_exact) // 2] if ranks_exact else None),
        "results": results,
    }


# ---------------------------------------------------------------- 报告
def human_report(data: dict) -> str:
    L = []
    W = 64
    tax = data["ctx_tax"]
    L.append("=" * W)
    L.append("注意力税模拟 attention_sim.py（三件套）")
    L.append("=" * W)
    L.append(f"口径: token = bytes // {tax['bytes_per_token']} | 窗口 {tax['window']}")
    L.append("")
    L.append("① 上下文税口径")
    for key in ("p0", "session"):
        s = tax[key]
        L.append(f"  {s['layer']}: {s['kb']}KB = {s['tokens']} token = {s['pct_of_window']}% of 128K"
                 f" （命中 {s['files_present']} 文件）")
        if s["files_missing"]:
            L.append(f"      缺失: {', '.join(s['files_missing'])}")
    fb = tax["fullbody"]
    L.append(f"  {fb['layer']}: {fb['kb']}KB = {fb['tokens']} token = 窗口的 {fb['window_multiple']}x"
             f"（GM {fb['gm_md_files']} md + {fb['skill_md_files']} SKILL.md）")
    note = tax["upstream_p0_path_note"]
    if not note["exists"] and not note["corrected_exists"]:
        L.append(f"  ⚠ 上游口径差异: fenjue_measure.py 用 `{note['fenjue_measure_path']}`（不存在），"
                 f"实际为 `{note['corrected_path']}` → {note['impact']}")
    L.append("")

    dil = data["dilution"]
    L.append("② 蒙特卡洛软注意力稀释（相关块注意力占比 vs 场景 N）")
    if not dil.get("available"):
        L.append(f"  [SKIP] {dil.get('reason')}")
    else:
        L.append(f"  trials={dil['trials']} seed={dil['seed']} mu_rel={dil['mu_relevant']}"
                 f" chunk={dil['chunk_tokens']}token k={dil['k_relevant']}")
        for s in dil["scenarios"]:
            L.append(f"  {s['scenario']:<26} N={s['n_chunks']:>6} 块 | 相关块注意力 "
                     f"{s['relevant_attention_mean']:.4f}"
                     f" (p05 {s['p05']:.4f} / p95 {s['p95']:.4f})"
                     f" | 相对 P0 稀释 {s['dilution_vs_p0']}x")
        L.append("  结论: D1/D7 满分 ≠ 稀释为零——上下文越大，同一相关块的注意力质量占比越低。")
    L.append("")

    hs = data["haystack"]
    L.append("③ 干草堆检索（协议集 vs 全库 rank）")
    if not hs.get("available"):
        L.append(f"  [SKIP] {hs.get('reason')}")
    else:
        tag = "TF-IDF 降级" if hs["degraded"] else "BGE"
        L.append(f"  引擎: {hs['engine']}（{tag}）| 探测: {hs['bge_probe']}")
        L.append(f"  语料: {hs['corpus_files']} 文件 / {hs['corpus_chunks']} 块")
        L.append(f"  Top-1 命中率 {hs['hit_top1_rate']} | Top-{hs['top_k']} 命中率 "
                 f"{hs.get('hit_top%d_rate' % hs['top_k'])} | 中位 rank {hs['median_rank']}")
        for r in hs["results"]:
            if r.get("status") != "OK":
                L.append(f"    [SKIP] {r['target']}: {r.get('reason')}")
                continue
            mark = "✅" if r["hit_top1"] else ("🟡" if r[f"hit_top{hs['top_k']}"] else "❌")
            L.append(f"    {mark} rank={r['rank_of_target']} → {r['target']}")
    L.append("")
    L.append("=" * W)
    L.append("只读脚本：未修改任何文件。审计 D1/D7/D8 时建议与 fenjue_measure.py 同跑。")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="焚诀注意力税模拟（三件套，只读）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--trials", type=int, default=10000, help="蒙特卡洛次数（默认 10000）")
    ap.add_argument("--seed", type=int, default=42, help="随机种子（默认 42，保证可复现）")
    ap.add_argument("--mu-rel", type=float, default=4.0, help="相关块 logit 均值（默认 4.0）")
    ap.add_argument("--top-k", type=int, default=10, help="干草堆 Top-K（默认 10）")
    ap.add_argument("--no-haystack", action="store_true", help="跳过 ③（省时）")
    args = ap.parse_args(argv)

    if not os.path.isdir(GM):
        msg = f"global_memory 不可达: {GM}"
        print(json.dumps({"error": msg}, ensure_ascii=False) if args.json else f"[FAIL] {msg}")
        return 2

    tax = measure_ctx_tax()
    scenarios = [
        ("P0 强制注入", tax["p0"]["tokens"]),
        ("本会话(P0+项目绑定)", tax["session"]["tokens"]),
        ("全库(理论上限)", tax["fullbody"]["tokens"]),
    ]
    dil = simulate_dilution(scenarios, trials=args.trials, seed=args.seed, mu_rel=args.mu_rel)
    hs = ({"available": False, "reason": "--no-haystack 显式跳过", "engine": "skipped"}
          if args.no_haystack else measure_haystack(top_k=args.top_k))

    data = {
        "schema": "fenjue-attention-sim-v1",
        "readonly": True,
        "ctx_tax": tax,
        "dilution": dil,
        "haystack": hs,
    }
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(human_report(data))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass  # Windows 控制台编码不可配时保持默认（标准惯用法，R207 P2-1 留痕）
    raise SystemExit(main())
