#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_recall_eval.py — 记忆召回评测集跑分器（P1E-1，2026-09-24）

对标：mem0 memory-benchmarks / letta Leaderboard —— 记忆系统首个可复现数字。
召回契约与 A-memory-start Step 0.55 同构：关键词提取归 AI（评测条目自带人工策展
keywords），检索质量归记忆系统（本脚本引擎）——两个环节分离，数字才有诊断价值。

指标（双）：
  Hit@5 —— 期望条目进入 top-5 的用例占比
  MRR   —— 期望条目首次排名倒数的均值

语料：GLOBAL_MEMORY 根下 {lessons,core,meta,system}/*.md（config 单源），排除口径与 Step 0.55
一致（lessons.md / lessons_index* / lessons-archive* / lessons-p0.md / lessons.part1.md）。
条目粒度：##~#### 标题切分。

用法:
  python memory_recall_eval.py                  # 人读报告
  python memory_recall_eval.py --json           # 机器读（aggregate_status 消费）
  python memory_recall_eval.py --check-testset  # 只验评测集结构 + 期望目标死链
  python memory_recall_eval.py --selftest       # 判据隔离桩（合成语料，不碰真实记忆盘）

退出码: 0 正常 / 1 评测集或语料异常 / 2 用法错误
"""
from __future__ import annotations

import json
import os
import re
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EVAL_DIR)
from config import GLOBAL_MEMORY  # noqa: E402  单源引用（env 可覆盖）

TESTSET_PATH = os.path.join(EVAL_DIR, "memory_recall_testset.json")

HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$", re.M)


# ============ 语料构建 ============
def split_entries(text):
    """按 ##~#### 标题切条目。返回 [(heading, body)]；首个标题前的内容不建条目。"""
    marks = [(m.start(), m.group(2).strip()) for m in HEADING_RE.finditer(text)]
    entries = []
    for i, (pos, heading) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos:end]
        entries.append((heading, body))
    return entries


def default_excludes():
    return {"lessons.md", "lessons-p0.md", "lessons.part1.md"}


def is_excluded(fname, exclude_names, exclude_prefixes):
    if fname in exclude_names:
        return True
    if fname.startswith("lessons_index") or fname.startswith("lessons-archive"):
        return True
    for p in exclude_prefixes:
        if fname.startswith(p):
            return True
    return False


def build_corpus(root, corpus_roots, exclude_prefixes=()):
    """遍历记忆根构建条目集合。返回 [{file, heading, text}]，file 为相对 root 的正斜杠路径。"""
    excl_names = default_excludes()
    corpus = []
    for d in corpus_roots:
        dirpath = os.path.join(root, d.replace("/", os.sep))
        if not os.path.isdir(dirpath):
            continue
        for fname in sorted(os.listdir(dirpath)):
            if not fname.endswith(".md"):
                continue
            if is_excluded(fname, excl_names, exclude_prefixes):
                continue
            fp = os.path.join(dirpath, fname)
            try:
                text = open(fp, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            rel = (d + "/" + fname) if d else fname
            for heading, body in split_entries(text):
                corpus.append({"file": rel, "heading": heading, "text": body})
    return corpus


def corpus_from_testset(testset, root=None):
    ts_root = testset.get("corpus_roots", ["lessons", "core", "meta", "system"])
    return build_corpus(root or GLOBAL_MEMORY, ts_root,
                        tuple(testset.get("exclude_prefixes", [])))


# ============ 召回引擎（确定性关键词评分）============
def score_entry(entry, keywords):
    s = 0
    for kw in keywords:
        if kw in entry["heading"]:
            s += 3
        elif kw in entry["text"]:
            s += 1
    return s


def recall(corpus, keywords, top_k):
    ranked = [(score_entry(e, keywords), e["file"], e["heading"], i)
              for i, e in enumerate(corpus)]
    hits = [t for t in ranked if t[0] > 0]
    hits.sort(key=lambda t: (-t[0], t[1], t[2]))
    return hits[:top_k]


def first_expected_rank(ranked, expected):
    """期望条目（file+heading 精确匹配）在 top-k 列表中的 0-based 名次；未命中返回 None。"""
    exp = {(e["file"], e["heading"]) for e in expected}
    for i, (_score, f, h, _idx) in enumerate(ranked):
        if (f, h) in exp:
            return i
    return None


def evaluate(testset, corpus):
    params = testset.get("params", {})
    top_k = int(params.get("top_k", 10))
    hit_at = int(params.get("hit_at", 5))
    details, misses = [], []
    rr_sum = 0.0
    for item in testset.get("items", []):
        ranked = recall(corpus, item.get("keywords", []), top_k)
        rank = first_expected_rank(ranked, item.get("expected", []))
        hit = rank is not None and rank < hit_at
        rr = (1.0 / (rank + 1)) if rank is not None else 0.0
        rr_sum += rr
        rec = {"id": item.get("id"), "query": item.get("query", ""),
               "rank": rank, "hit": hit, "rr": round(rr, 4)}
        details.append(rec)
        if not hit:
            misses.append({**rec,
                           "expected": [f"{e['file']}#{e['heading']}"
                                        for e in item.get("expected", [])],
                           "top": [f"{f}#{h}" for _s, f, h, _i in ranked[:hit_at]]})
    n = len(details)
    hits_n = sum(1 for d in details if d["hit"])
    return {
        "schema": "fenjue-memory-recall-v1",
        "items": n,
        "top_k": top_k,
        "hit_at": hit_at,
        "corpus_entries": len(corpus),
        "hits": hits_n,
        "hit_at_5_rate": round(hits_n / n, 4) if n else 0.0,
        "mrr": round(rr_sum / n, 4) if n else 0.0,
        "baseline": testset.get("baseline", {}),
        "misses": misses,
        "details": details,
    }


# ============ 评测集结构与死链校验（C26 复用同一实现）============
def validate_testset(testset, root, min_items=30, max_items=60):
    """返回 (errors, stats)。errors 空 = 合规。R247：零检索面不得静默 PASS。"""
    errors = []
    items = testset.get("items") or []
    if not items:
        return (["W1 items 为空（评测集判据面失效）"], {"items": 0})
    if not (min_items <= len(items) <= max_items):
        errors.append(f"W2 条目数 {len(items)} 越界（要求 {min_items}~{max_items}）")
    seen_ids = set()
    for it in items:
        iid = it.get("id", "?")
        if iid in seen_ids:
            errors.append(f"W2 id 重复: {iid}")
        seen_ids.add(iid)
        if not (it.get("keywords") or []):
            errors.append(f"W3 {iid}: keywords 为空")
        if not (it.get("expected") or []):
            errors.append(f"W3 {iid}: expected 为空")
    # W4 死链核验：expected 的 (file, heading) 必须在磁盘语料真实出现
    corpus = corpus_from_testset(testset, root=root)
    indexed = {(e["file"], e["heading"]) for e in corpus}
    dead = []
    for it in items:
        for e in it.get("expected", []):
            if (e.get("file", ""), e.get("heading", "")) not in indexed:
                dead.append(f"{it.get('id')}: {e.get('file')}#{e.get('heading')}")
    if dead:
        errors.append("W4 期望目标死链 %d 条（R240 文档写了≠磁盘有）: %s"
                      % (len(dead), "; ".join(dead[:5])))
    # W5 基线段
    base = testset.get("baseline") or {}
    for key in ("hit_at_5", "mrr"):
        v = base.get(key)
        if not isinstance(v, (int, float)) or not (0.0 <= v <= 1.0):
            errors.append(f"W5 baseline.{key} 缺失或越界: {v!r}")
    if not base.get("measured"):
        errors.append("W5 baseline.measured 缺日期")
    return (errors, {"items": len(items), "corpus_entries": len(corpus)})


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ============ 隔离桩（合成语料小世界，不碰真实记忆盘）============
def _selftest():
    import tempfile
    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "lessons"))
        os.makedirs(os.path.join(td, "core"))
        open(os.path.join(td, "lessons", "lessons-a.md"), "w",
             encoding="utf-8").write(
                 "# 壳\n## 目标经验\n正文提到 junction 与 robocopy。\n"
                 "## 干扰条目\n也提到 junction 一次。\n")
        open(os.path.join(td, "lessons", "lessons-p0.md"), "w",
             encoding="utf-8").write("## 必须排除我\njunction junction junction junction\n")
        open(os.path.join(td, "core", "rules.md"), "w",
             encoding="utf-8").write("## 目标铁律\njunction 三要则全文出现 junction junction\n")
        corpus = build_corpus(td, ["lessons", "core"])
        files = {e["file"] for e in corpus}
        check("T1 正例:语料含目标文件", "lessons/lessons-a.md" in files and "core/rules.md" in files)
        check("T1 边界:排除口径 lessons-p0 不入面", not any("p0" in f for f in files))
        ts = {"corpus_roots": ["lessons", "core"],
              "params": {"top_k": 3, "hit_at": 2},
              "baseline": {"hit_at_5": 0.5, "mrr": 0.5, "measured": "2026-09-24"},
              "items": [
                  {"id": "S1", "query": "junction 经验在哪",
                   "keywords": ["junction", "目标"],
                   "expected": [{"file": "core/rules.md", "heading": "目标铁律"},
                                {"file": "lessons/lessons-a.md", "heading": "目标经验"}]},
                  {"id": "S2", "query": "不存在的东西",
                   "keywords": ["量子退相干"],
                   "expected": [{"file": "core/rules.md", "heading": "目标铁律"}]},
              ]}
        res = evaluate(ts, corpus)
        check("T2 正例:S1 命中且名次最优", res["details"][0]["hit"]
              and res["details"][0]["rank"] == 0)
        check("T2 违规:S2 零命中不静默", not res["details"][1]["hit"]
              and res["details"][1]["rr"] == 0.0)
        check("T2 指标:hit_rate=0.5 且 MRR=0.5",
              abs(res["hit_at_5_rate"] - 0.5) < 1e-9 and abs(res["mrr"] - 0.5) < 1e-9)
        errs, _ = validate_testset(ts, root=td, min_items=2)  # 合成小世界仅 2 条，边界参数随夹具注入
        check("T3 正例:合规评测集零错误", errs == [])
        ts_dead = json.loads(json.dumps(ts))
        ts_dead["items"][0]["expected"].append(
            {"file": "core/rules.md", "heading": "被删掉的标题"})
        errs2, _ = validate_testset(ts_dead, root=td, min_items=2)
        check("T3 违规:期望死链必拦", any("W4" in e for e in errs2))
        ts_empty = {"corpus_roots": ["lessons"], "items": []}
        errs3, _ = validate_testset(ts_empty, root=td)
        check("T3 边界:空集不得静默过", any("W1" in e for e in errs3))
        ts_small = json.loads(json.dumps(ts))
        ts_small["items"] = ts_small["items"] * 10  # 20 条 < min
        errs4, _ = validate_testset(ts_small, root=td, min_items=30)
        check("T3 边界:条目数越界必拦", any("W2 条目数" in e for e in errs4))
        ts_base = json.loads(json.dumps(ts))
        ts_base["baseline"] = {"hit_at_5": 1.5}
        errs5, _ = validate_testset(ts_base, root=td, min_items=2)
        check("T3 违规:基线越界必拦", any("W5" in e for e in errs5))

    n = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("  [%s] %s" % ("OK  " if ok else "FAIL", label))
    print(f"memory_recall_eval selftest: {n}/{len(cases)}")
    return 0 if n == len(cases) else 1


# ============ main ============
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return _selftest()
    as_json = "--json" in argv
    check_only = "--check-testset" in argv
    ts_path = TESTSET_PATH
    if "--testset" in argv:
        i = argv.index("--testset")
        if i + 1 >= len(argv):
            print("用法错误: --testset 需要路径", file=sys.stderr)
            return 2
        ts_path = argv[i + 1]
    try:
        testset = load_json(ts_path)
    except Exception as e:
        print(f"评测集读取失败: {e}", file=sys.stderr)
        return 1
    if testset.get("schema") != "fenjue-memory-recall-testset-v1":
        print("评测集 schema 不识别: %r" % testset.get("schema"), file=sys.stderr)
        return 1
    errors, stats = validate_testset(testset, GLOBAL_MEMORY)
    if check_only:
        if errors:
            print("评测集校验失败:\n" + "\n".join("  - " + e for e in errors),
                  file=sys.stderr)
            return 1
        print("评测集校验 PASS: items=%d corpus_entries=%d"
              % (stats["items"], stats["corpus_entries"]))
        return 0
    if errors:
        print("评测集不合规，先修复再跑分:\n" + "\n".join("  - " + e for e in errors),
              file=sys.stderr)
        return 1
    corpus = corpus_from_testset(testset)
    res = evaluate(testset, corpus)
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    print("=" * 64)
    print("记忆召回评测（P1E-1）— 语料条目 %d / 用例 %d"
          % (res["corpus_entries"], res["items"]))
    print("=" * 64)
    print("Hit@%d = %.1f%% (%d/%d)   MRR = %.4f"
          % (res["hit_at"], res["hit_at_5_rate"] * 100, res["hits"], res["items"], res["mrr"]))
    base = res.get("baseline") or {}
    if base:
        print("基线登记: hit@%s, mrr=%s (measured=%s)" % (
            base.get("hit_at_5"), base.get("mrr"), base.get("measured")))
    if res["misses"]:
        print("-" * 64)
        print("未命中 %d 条（Top-%d 内无期望条目）:" % (len(res["misses"]), res["hit_at"]))
        for m in res["misses"]:
            print("  [%s] %s" % (m["id"], m["query"]))
            print("      期望: %s" % "; ".join(m["expected"]))
            print("      实际top: %s" % "; ".join(m["top"][:3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
