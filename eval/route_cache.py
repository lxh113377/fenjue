#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""route_cache.py — 路由结果跨进程缓存（对标轮四 7-A，治 D-19）。

实测背景：各在役端每轮都新起进程，落 BGE 语义召回的查询稳定 ~1.53 s（其中约 95% 是
onnx 模型重复加载，稳态判定本身 p50 约 4 ms）。直连/Tag 命中仅 ~85 ms。

失效是本模块的第一约束：缓存键绑定「索引指纹」（各索引产物的 size+mtime 摘要），
索引重建/技能退役后指纹变 ⇒ 旧条目整体不可见。绝不允许缓存把已退役技能供出来。

文件形态：追加式 JSONL（多 agent 进程可能同时写），读侧逐行容错坏行/BOM，
写侧任何 IO 异常一律降级为「未命中」而不是让路由失败。
用法：`python eval/route_cache.py --stats`；关闭用 FENJUE_ROUTE_CACHE=0。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVAL_DIR)

SCHEMA = "fenjue-route-cache-v1"
TTL_SECONDS = 7 * 24 * 3600
MAX_ENTRIES = 512
COMPACT_BYTES = 128 * 1024

# 影响路由结果的索引产物：任一变化即整体失效（宁 miss 不误供）
INDEX_SOURCES = (
    "direct_map.json", "skill_tags.json", "tfidf_matrix.npz", "tfidf_vectorizer.pkl",
    "tfidf_skill_ids.json", "bge_fullbody_embeddings.npy", "bge_fullbody_meta.json",
    "bge_fullbody_skills.json", "../skill/registry/unified-skills-index.json",
)

_WS_RE = re.compile(r"\s+")
_DISABLED = ("0", "false", "no", "off")


def cache_path() -> str:
    override = os.environ.get("FENJUE_ROUTE_CACHE_FILE")
    if override:
        return override
    return os.path.join(EVAL_DIR, "_cache", "route_cache.jsonl")


CACHE_PATH = cache_path()


def enabled() -> bool:
    return os.environ.get("FENJUE_ROUTE_CACHE", "").strip().lower() not in _DISABLED


def fingerprint() -> str:
    h = hashlib.sha1(SCHEMA.encode("utf-8"))
    for name in INDEX_SOURCES:
        p = os.path.normpath(os.path.join(EVAL_DIR, name))
        try:
            st = os.stat(p)
            h.update(("%s|%d|%d;" % (name, st.st_size, int(st.st_mtime))).encode("utf-8"))
        except OSError:
            h.update(("%s|missing;" % name).encode("utf-8"))
    return h.hexdigest()[:16]


def normalize_query(query: str) -> str:
    return _WS_RE.sub(" ", (query or "").strip()).casefold()


def make_key(query: str, flags: dict | None = None) -> str:
    payload = json.dumps({"q": normalize_query(query), "f": flags or {}},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _read_records(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.readlines()
    except OSError:
        return []
    out = []
    for line in raw:
        line = line.strip().lstrip("\ufeff")
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and "key" in rec and "payload" in rec:
            out.append(rec)
    return out


def lookup(key: str):
    if not enabled():
        return None
    fp = fingerprint()
    now = time.time()
    try:
        path = CACHE_PATH
    except Exception:
        return None
    hit = None
    for rec in _read_records(path):
        if rec.get("fp") != fp or rec.get("key") != key:
            continue
        if now - float(rec.get("ts", 0)) > TTL_SECONDS:
            continue
        hit = rec.get("payload")
    if isinstance(hit, dict):
        hit = dict(hit)
        hit["cached"] = True
        hit["cache_fp"] = fp
    return hit


def store(key: str, payload: dict) -> None:
    if not enabled() or not isinstance(payload, dict):
        return
    rec = {"fp": fingerprint(), "key": key, "ts": time.time(), "payload": payload}
    try:
        path = CACHE_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        # 滞后带（2×MAX）触发重写：每条都压缩会把成本摊到每次调用上，按带摊销为 O(1)
        with open(path, "rb") as f:
            lines = sum(1 for _ in f)
        if lines > MAX_ENTRIES * 2 or os.path.getsize(path) > COMPACT_BYTES:
            _compact(path)
    except OSError:
        return


def _compact(path: str) -> None:
    """按 key 去重后只保留最新 MAX_ENTRIES 条（防缓存无界增长）。"""
    fp = fingerprint()
    now = time.time()
    kept = {}
    for rec in _read_records(path):
        if rec.get("fp") != fp or now - float(rec.get("ts", 0)) > TTL_SECONDS:
            continue
        kept[rec["key"]] = rec
    newest = sorted(kept.values(), key=lambda r: r.get("ts", 0))[-MAX_ENTRIES:]
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for rec in newest:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except OSError:
        return


def stats() -> dict:
    fp = fingerprint()
    now = time.time()
    recs = _read_records(CACHE_PATH)
    live = [r for r in recs if r.get("fp") == fp and now - float(r.get("ts", 0)) <= TTL_SECONDS]
    return {"path": CACHE_PATH, "fingerprint": fp, "records": len(recs),
            "live": len(live), "bytes": os.path.getsize(CACHE_PATH) if os.path.exists(CACHE_PATH) else 0,
            "enabled": enabled()}


def main(argv=None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--stats" in argv:
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
        return 0
    print("用法: python eval/route_cache.py --stats")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
