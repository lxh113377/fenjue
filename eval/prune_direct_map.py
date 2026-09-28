# -*- coding: utf-8 -*-
"""prune_direct_map.py — DIRECT_MAP 冗余规则剪枝实验（R170 去熵）

方法: 对语料(分层盲测284 + 回归 + 生产唯一查询 + 探针)逐条实跑：
  - 全量路由得 top1_0；
  - 对每条命中该查询的直连规则，模拟移除后重跑得 top1_1；
  - top1 不变 → 该规则对该查询冗余；全部命中查询均冗余 → 可剪枝。
安全: 先 --dry-run 分析（分批/断点续跑），--report 汇总，--verify 全语料
复跑确认无回归，--apply 才写入（direct_layer.py fallback + save_direct_map 同步）。

用法:
  python eval/prune_direct_map.py --dry-run [--offset N --limit M]
  python eval/prune_direct_map.py --report
  python eval/prune_direct_map.py --verify
  python eval/prune_direct_map.py --apply

I/O 形态（2026-09-24 P0-11）: 全文件统一 pathlib 接收者式读写，
行为等价（json.dump(x, f) → write_text(json.dumps(x))，均无尾换行）。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

EVAL = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(EVAL)
sys.path.insert(0, EVAL)

import direct_layer  # noqa: E402
import unified_router  # noqa: E402

TMP = os.path.join(PROJ, "Temp")
RESULT_PATH = os.path.join(TMP, "prune_results.json")
PROGRESS_PATH = os.path.join(TMP, "prune_progress.json")


def load_corpus():
    qs = []
    # 分层盲测 284
    lp = os.path.join(EVAL, "layered_testset.json")
    with Path(lp).open(encoding="utf-8") as _f:
        _tiers = json.load(_f)
    for tier in _tiers:
        qs += [e["query"] for e in tier.get("queries", [])]
    # 回归集
    tp = os.path.join(EVAL, "test_queries.json")
    with Path(tp).open(encoding="utf-8") as _f:
        _tiers = json.load(_f)
    for tier in _tiers:
        if isinstance(tier, dict):
            qs += [e["query"] for e in tier.get("queries", []) if isinstance(e, dict) and e.get("query")]
    # 生产唯一查询
    pp = os.path.join(TMP, "corpus_prod_queries.json")
    if os.path.exists(pp):
        with Path(pp).open(encoding="utf-8") as _f:
            qs += json.load(_f)
    # 直连层不变式用例（回归 T2 30 条 + test_queries 全量，防剪枝破坏 direct_route 覆盖）
    invp = os.path.join(TMP, "corpus_direct_invariant.json")
    if os.path.exists(invp):
        with Path(invp).open(encoding="utf-8") as _f:
            qs += json.load(_f)
    # R170 探针
    qs += [
        "写个脚本定期备份数据库", "开始写第一章小说",
        "这是我的记忆系统项目文件夹，为codex配置我的记忆系统memory tree和skill tree",
        "1.番茄免费小说作品标签 2.简介 3.为这本书创作一个封面", "生成一张海报",
        "帮我看看路由有没有问题", "我想让别人也可以打开我的网站",
        "继续执行未完成的任务", "下载 Hermes 桌面版",
    ]
    seen, out = set(), []
    for q in qs:
        q = (q or "").strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def full_route(q):
    try:
        return unified_router.route(q, top_k=5, enable_memory=True, enable_llm=False, enable_tags=True)
    except Exception as e:
        return {"top1": f"ERROR:{e}"}


def candidates_of(q):
    out = []
    for i, (pat, _tgt) in enumerate(direct_layer.DIRECT_MAP):
        try:
            if re.search(pat, q, re.IGNORECASE):
                out.append(i)
        except re.error:
            continue
    return out


def run_dry(offset, limit):
    os.makedirs(TMP, exist_ok=True)
    corpus = load_corpus()
    unified_router.TRACE_ENABLED = False
    done = {}
    if os.path.exists(PROGRESS_PATH):
        with Path(PROGRESS_PATH).open(encoding="utf-8") as _f:
            done = json.load(_f)
    if done.get("map_count") != len(direct_layer.DIRECT_MAP):
        done = {}  # 映射已变化，旧结果作废
    results = done.get("results", [])
    done_queries = {r["q"] for r in results}
    total = min(len(corpus), offset + limit) if limit else len(corpus)
    for qi in range(offset, total):
        q = corpus[qi]
        if q in done_queries:
            continue
        base = full_route(q)
        top0 = base.get("top1")
        changes = []
        for idx in candidates_of(q):
            filtered = [e for i, e in enumerate(direct_layer.DIRECT_MAP) if i != idx]
            direct_layer.DIRECT_MAP = filtered
            top1 = full_route(q).get("top1")
            direct_layer.DIRECT_MAP = _restore_map()
            if top1 != top0:
                changes.append({"rule": idx, "to": top1})
        results.append({"q": q, "top1": top0, "matched": candidates_of(q), "changes": changes})
        if qi % 50 == 0:
            Path(PROGRESS_PATH).write_text(
                json.dumps({"map_count": len(direct_layer.DIRECT_MAP), "results": results}, ensure_ascii=False),
                encoding="utf-8")
    Path(PROGRESS_PATH).write_text(
        json.dumps({"map_count": len(direct_layer.DIRECT_MAP), "results": results}, ensure_ascii=False),
        encoding="utf-8")
    Path(RESULT_PATH).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"dry-run: {len(results)}/{len(corpus)} 完成")


def _restore_map():
    # 从 direct_map.json 恢复权威映射（防实验中途污染）
    return direct_layer._load_direct_map()


def report():
    results = json.loads(Path(RESULT_PATH).read_text(encoding="utf-8"))
    dm = direct_layer._load_direct_map()
    matched = {}
    changed = {}
    for r in results:
        for idx in r["matched"]:
            matched[idx] = matched.get(idx, 0) + 1
            if any(c["rule"] == idx for c in r["changes"]):
                changed[idx] = changed.get(idx, 0) + 1
    prunable = [i for i in range(len(dm)) if i in matched and i not in changed]
    zero_match = [i for i in range(len(dm)) if i not in matched]
    none_rules = [i for i in range(len(dm)) if dm[i][1] == "NONE"]
    safe_zero = [i for i in zero_match if i not in none_rules]
    print(f"总规则: {len(dm)} | 命中≥1: {len(matched)} | 可剪(全冗余): {len(prunable)} "
          f"| 零命中: {len(zero_match)} (NONE {len(none_rules)}, 非NONE {len(safe_zero)})")
    print(f"保守剪枝候选: {len(prunable)} | 激进候选(含零命中非NONE): {len(prunable) + len(safe_zero)}")
    out = {"total": len(dm), "matched": len(matched), "prunable": prunable,
           "zero_match_non_none": safe_zero, "load_bearing": sorted(changed.keys())}
    Path(os.path.join(TMP, "prune_report.json")).write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def first_matching_remove(q, dm, remove):
    for i, (pat, _t) in enumerate(dm):
        if i not in remove:
            continue
        try:
            if re.search(pat, q, re.IGNORECASE):
                return i
        except re.error:
            continue
    return None


def compute_final_remove():
    """逐个剪枝候选 → 联合剪枝，冲突规则（同查全剪后语义跑偏）贪心回滚。"""
    with Path(os.path.join(TMP, "prune_report.json")).open(encoding="utf-8") as _f:
        rep = json.load(_f)
    dm = direct_layer._load_direct_map()
    remove = {i for i in rep["prunable"] if dm[i][1] != "NONE"}
    corpus = load_corpus()
    with Path(os.path.join(TMP, "corpus_direct_invariant.json")).open(encoding="utf-8") as _f:
        inv = set(json.load(_f))
    unified_router.TRACE_ENABLED = False
    for it in range(20):
        pruned = [e for i, e in enumerate(dm) if i not in remove]
        direct_layer.DIRECT_MAP = dm
        bad = []
        for q in corpus:
            t0 = full_route(q).get("top1")
            d0 = direct_layer.direct_route(q)
            direct_layer.DIRECT_MAP = pruned
            t1 = full_route(q).get("top1")
            d1 = direct_layer.direct_route(q)
            direct_layer.DIRECT_MAP = dm
            if t0 != t1 or (q in inv and d0 != d1):
                bad.append(q)
        if not bad:
            print(f"联合剪枝通过: 迭代 {it + 1} | 移除 {len(remove)} | 最终 {len(pruned)} 条")
            break
        restored = set()
        for q in bad:
            ridx = first_matching_remove(q, dm, remove)
            if ridx is not None:
                restored.add(ridx)
        if not restored:
            raise SystemExit(f"迭代 {it + 1}: 无法定位回滚规则，仍 {len(bad)} 条不一致")
        remove -= restored
        print(f"迭代 {it + 1}: 不一致 {len(bad)} 条 → 回滚 {len(restored)} 条规则，剩余移除 {len(remove)}")
    else:
        raise SystemExit("20 次迭代未收敛")
    rep["remove_final"] = sorted(remove)
    Path(os.path.join(TMP, "prune_report.json")).write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return remove


def verify():
    remove = compute_final_remove()
    dm = direct_layer._load_direct_map()
    pruned = [e for i, e in enumerate(dm) if i not in remove]
    corpus = load_corpus()
    with Path(os.path.join(TMP, "corpus_direct_invariant.json")).open(encoding="utf-8") as _f:
        inv = set(json.load(_f))
    unified_router.TRACE_ENABLED = False
    direct_layer.DIRECT_MAP = dm
    bad = []
    for q in corpus:
        t0 = full_route(q).get("top1")
        d0 = direct_layer.direct_route(q)
        direct_layer.DIRECT_MAP = pruned
        t1 = full_route(q).get("top1")
        d1 = direct_layer.direct_route(q)
        direct_layer.DIRECT_MAP = dm
        if t0 != t1 or (q in inv and d0 != d1):
            bad.append((q, t0, t1))
    print(f"verify: 语料 {len(corpus)} 条 | 剪枝后不一致 {len(bad)} 条 | 剪枝后规则数 {len(pruned)}")
    for b in bad[:10]:
        print("  MISMATCH:", b)
    Path(os.path.join(TMP, "prune_verify.json")).write_text(
        json.dumps({"ok": not bad, "bad": bad[:50], "pruned_count": len(pruned), "removed": len(remove)},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return not bad


def apply_prune():
    dm = direct_layer._load_direct_map()
    remove = set(compute_final_remove())
    pruned = [e for i, e in enumerate(dm) if i not in remove]
    with Path(os.path.join(TMP, "prune_verify.json")).open(encoding="utf-8") as _f:
        vf = json.load(_f)
    if not vf.get("ok"):
        raise SystemExit("verify 未通过，拒绝 apply")
    # 回写 direct_layer.py fallback
    lp = os.path.join(EVAL, "direct_layer.py")
    src = Path(lp).read_text(encoding="utf-8")
    body = ",\n".join(f"    ({json.dumps(p, ensure_ascii=False)}, {json.dumps(t, ensure_ascii=False)})" for p, t in pruned)
    new_block = f"_DIRECT_MAP_FALLBACK = [\n{body},\n]"
    pat = re.compile(r"_DIRECT_MAP_FALLBACK = \[.*?\n\]", re.DOTALL)
    src2, n = pat.subn(new_block, src, count=1)
    if n != 1:
        raise SystemExit("fallback 块未找到")
    Path(lp).write_text(src2, encoding="utf-8")
    print(f"fallback 已回写: {len(dm)} -> {len(pruned)} 条")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.dry_run:
        run_dry(a.offset, a.limit)
    elif a.report:
        report()
    elif a.verify:
        verify()
    elif a.apply:
        apply_prune()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
