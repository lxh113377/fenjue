#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_router.py — 语义层路由的规模与延迟基准（可复算，不写"很快"）。

补这个文件的原因（对标轮 2026-09-29）：同类仓里 basic-memory 有独立 `benchmarks/`
子项目并配 nightly + smoke 两条 workflow，khoj 有 `run_evals.yml`；本仓此前对外只给
一个数字——12 个合成技能上跑 14 条查询的命中率。那既不是性能读数，也回答不了
「技能库长到 1000 个还跑得动吗」，而技能库规模恰恰是本系统的卖点与风险源。

方法（口径全部写死在输出里，换机器也能对账）:
  1. 合成技能档案（名称 + 描述 + 触发词三段拼接，与 hitrate_cli 的 profile 同构），
     词表按序号轮换生成，保证档案之间互不相同且都有实际内容——不用空壳技能凑规模。
  2. 每个规模跑两件事并分开计时：
        建索引 = TfidfVectorizer.fit_transform(技能档案 + 查询)
        查询   = 对固定 20 条查询逐条取 top-k（与生产同一套 cosine_similarity）
  3. 延迟按**单查询**统计（中位/p95），单位毫秒；峰值内存用 tracemalloc（跨平台，
     不依赖 /proc 与 psutil）。
  4. 正确性抽查：每个规模都断言「Top-1 的词对 == 查询词对」——规模涨了但
     检索无效的基准没有意义。判词对而非判技能编号，是因为词对表每 10 个技能
     循环一次，同词对技能本就是合法并列候选。

退出码: 0=全部规模跑通且抽查命中 / 1=抽查失败 / 2=输入面不可判（规模列表为空等）
用法:
  python eval/bench_router.py                    # 默认规模 12,100,500
  python eval/bench_router.py --sizes 12,1000 --json
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # 装成包时用相对导入，避免同一模块出现两个实例
    from .hitrate_cli import score_matrix
except ImportError:  # 直接跑脚本时（__package__ 为空）退回绝对导入
    from hitrate_cli import score_matrix  # noqa: E402

VOCAB = ["评审", "图表", "日志", "索引", "翻译", "部署", "测试", "文档", "性能", "安全"]
VERBS = ["帮我", "请问", "需要", "想要", "麻烦"]


def _tokens(i: int) -> tuple[str, str]:
    """技能 i 的词对。生成器与查询构造**共用这一个函数**——否则查询里的词与
    目标技能档案里的词不同源，抽查就变成碰运气。

    词对每 10 个技能循环一次 ⇒ 同词对技能是一组**合法并列候选**。因此抽查判的是
    「Top-1 的词对等于查询词对」，不判具体编号；判编号的写法在 100/500 规模上会
    因为合法并列而把基准误判成失败。"""
    return VOCAB[i % len(VOCAB)], VOCAB[(i * 7 + 3) % len(VOCAB)]


def synthetic_skills(n: int) -> list[dict]:
    """生成 n 个技能档案（名称 + 描述 + 触发词，与仓内示例同构）。"""
    out = []
    for i in range(n):
        a, b = _tokens(i)
        out.append({
            "name": f"bench-skill-{i:04d}",
            "profile": f"bench-skill-{i:04d} 处理{a}相关的{b}任务 触发词 {a} {b} 第{i}号场景",
            "tokens": (a, b),
        })
    return out


def synthetic_queries(n_query: int, anchor: int) -> tuple[list[str], list[tuple[str, str]]]:
    """返回 (查询文本, 期望词对)；第 0 条固定落在 anchor 的词对上。"""
    queries, expects = [], []
    for j in range(n_query):
        idx = anchor if j == 0 else (j * 13) % 60
        a, b = _tokens(idx)
        queries.append(f"{VERBS[j % len(VERBS)]}把{a}的{b}结果整理一下")
        expects.append((a, b))
    return queries, expects


def _warmup() -> None:
    """先跑一次极小打分，把 sklearn/scipy 的惰性导入与首编译从计时里剥出去。

    不做这件事的实测后果（2026-09-29 本机）：同一进程内按 12,100,500 顺序跑，
    第一行建索引 6.23s、其后 0.10s/0.38s；把顺序换成 100,12,1000，第一行变成
    6.16s——冷的不是规模而是**进程首趟**。把这 6 秒记进 12 规模的账，
    等于对外公布一个由取数顺序决定的数字。
    """
    tiny = [{"name": "w0", "profile": "warmup 评审"}, {"name": "w1", "profile": "warmup 图表"}]
    score_matrix(tiny, ["warmup 评审"])


def _time_once(skills: list[dict], queries: list[str], top: int):
    """一趟：返回 (建索引秒, 每次取 top-k 的毫秒列表, 每条查询的 top-k 下标)。

    top-k 下标顺手返回而不是再跑第四趟打分：抽查要用它，而多跑一趟既慢又让
    「计时的那次」和「被检查的那次」不是同一次，读数的因果就不成立。
    计时期间不开 tracemalloc（见 bench_size 里的单独一趟）。
    """
    latents = []
    t0 = time.perf_counter()
    sim = score_matrix(skills, queries)
    build = time.perf_counter() - t0
    picks = []
    for row in sim:
        t1 = time.perf_counter()
        picks.append([int(i) for i in row.argsort()[::-1][:top]])
        latents.append((time.perf_counter() - t1) * 1000.0)
    return build, latents, picks


def bench_size(n_skills: int, anchor: int = 5, n_query: int = 20, top: int = 3,
               repeats: int = 3) -> dict:
    skills = synthetic_skills(n_skills)
    queries, expects = synthetic_queries(n_query, anchor)

    builds, all_latents, last_picks = [], [], []
    for _ in range(repeats):
        build, lat, picks = _time_once(skills, queries, top)
        builds.append(build)
        all_latents.extend(lat)
        last_picks = picks

    # 内存单独一趟：tracemalloc 会给每次分配加钩子，混在计时里两头都不准。
    tracemalloc.start()
    _time_once(skills, queries, top)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tokens = [s["tokens"] for s in skills]
    correct = sum(int(bool(last_picks) and tokens[last_picks[j][0]] == expects[j])
                  for j in range(len(expects)))

    lat_sorted = sorted(all_latents)
    return {
        "skills": n_skills,
        "queries": n_query,
        "repeats": repeats,
        "index_seconds": round(statistics.median(builds), 4),
        "per_query_ms_median": round(statistics.median(all_latents), 4),
        "per_query_ms_p95": round(lat_sorted[max(0, int(len(lat_sorted) * 0.95) - 1)], 4),
        "peak_alloc_mb": round(peak / 1024 / 1024, 3),
        "expected_top1_hits": correct,
        "n_expected": n_query,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="12,100,500",
                    help="逗号分隔的技能规模列表；12 = 仓内示例的真实规模")
    ap.add_argument("--queries", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    except ValueError:
        print("[FATAL] --sizes 必须是逗号分隔的整数", file=sys.stderr)
        return 2
    if not sizes:
        print("[FATAL] 零规模不得记 PASS：--sizes 解析为空", file=sys.stderr)
        return 2

    _warmup()
    rows = [bench_size(n, n_query=args.queries) for n in sizes]

    rc = 0
    for r in rows:
        if r["expected_top1_hits"] < r["n_expected"]:
            r["check"] = f"FAIL {r['expected_top1_hits']}/{r['n_expected']}"
            rc = 1
        else:
            r["check"] = "ok"

    if args.json:
        print(json.dumps({
            "python": sys.version.split()[0],
            "platform": f"{platform.system()}/{platform.machine()}",
            "method": "TF-IDF char_wb(2,4) + cosine；建索引计时含 fit_transform",
            "rows": rows,
        }, ensure_ascii=False, indent=2))
        return rc

    print("python %s  %s" % (sys.version.split()[0], f"{platform.system()}/{platform.machine()}"))
    print("%-8s%-9s%-14s%-19s%-16s%-14s%s"
          % ("技能数", "查询数", "建索引(s)", "单查询中位(ms)", "单查询p95(ms)", "峰值内存(MB)", "抽查"))
    for r in rows:
        print("%-8d%-9d%-14s%-19s%-16s%-14s%s"
              % (r["skills"], r["queries"], r["index_seconds"], r["per_query_ms_median"],
                 r["per_query_ms_p95"], r["peak_alloc_mb"], r["check"]))
    if rc:
        print("[FATAL] 抽查未全中：基准结果不可信，见上表 check 列", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
