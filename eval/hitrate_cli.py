#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hitrate_cli.py — 技能路由命中率评估器（可独立运行的对外入口）。

它回答一个具体问题：给定一批「用户会怎么说」的查询和一份技能清单，
路由器把每条查询排到期望技能上的概率是多少？按难度分层出数，
这样"命中率 90%"不会把"明确关键词"和"口语化歧义"混成一锅。

与仓内 eval/unified_router.py 的分工：后者是生产路由器（四层：直连→Tag→
语义→Memory），依赖完整记忆根；本 CLI 只做**语义层**的 TF-IDF 打分，
输入输出全部自包含，因此在任何一台机器上 clone 完就能跑。

用法:
  python eval/hitrate_cli.py --skills-dir examples/skills --queries examples/queries.json
  python eval/hitrate_cli.py ... --json            # 机器可读
  python eval/hitrate_cli.py ... --top 3           # 同时报 Top-3
退出码: 0=完成 / 2=输入面不可判（缺目录、空清单、无期望技能）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_frontmatter(text: str) -> dict[str, str]:
    m = FRONT_RE.match(text)
    body = {}
    for line in (m.group(1).splitlines() if m else []):
        if ":" in line:
            k, _, v = line.partition(":")
            body[k.strip().lower()] = v.strip().strip('"\'')
    return body


def load_skills(skills_dir: Path) -> list[dict]:
    """两种布局都吃，返回值结构一致：

    - 扁平：`<dir>/<name>.md`（本仓 `examples/skills` 的形态）
    - Agent Skills 标准目录：`<dir>/<name>/SKILL.md`（anthropics/skills 的形态）

    打通后一条 `--skills-dir` 就能指向任一份标准格式的技能树做命中率评估，
    不必先把别人的仓库翻译成我们示例的形状。同名时**标准目录优先**（它是显式声明的
    技能身份），并保留扁平件以免有人靠文件名匹配期望技能。
    每个技能 profile = 名称 + 描述 + 触发词（与生产侧同构的三段文本）。
    """
    out: list[dict] = []
    seen: dict[str, int] = {}

    def add(name: str, text: str) -> None:
        fm = parse_frontmatter(text)
        name = fm.get("name") or name
        profile = " ".join([name, fm.get("description", ""), fm.get("triggers", "")])
        if not fm.get("description"):
            profile += " " + text[:400]
        if name in seen:
            out[seen[name]] = {"name": name, "profile": profile}
            return
        seen[name] = len(out)
        out.append({"name": name, "profile": profile})

    for p in sorted(skills_dir.glob("*.md")):
        add(p.stem, p.read_text(encoding="utf-8"))
    for p in sorted(skills_dir.glob("*/SKILL.md")):
        add(p.parent.name, p.read_text(encoding="utf-8"))
    return out


def score_matrix(skills: list[dict], queries: list[str]):
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        print("[FATAL] 需要 scikit-learn：pip install -r requirements.txt", file=sys.stderr)
        raise SystemExit(2)
    docs = [s["profile"] for s in skills]
    # 分词器必须能吃中文：默认的 \w+ 词切法会把整句中文当成**一个** token，
    # 查询与技能档案之间几乎不可能重叠 —— 实测那样 Top-1 只有 35.7%，
    # 且那是度量器的缺陷，不是路由质量的证据。改用字符级 n-gram。
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
    m = vec.fit_transform(docs + queries)
    return cosine_similarity(m[len(docs):], m[:len(docs)])


def evaluate(skills: list[dict], cases: list[dict], top: int) -> dict:
    names = [s["name"] for s in skills]
    queries = [c["query"] for c in cases]
    sim = score_matrix(skills, queries)
    per_case, tiers = [], {}
    for case, row in zip(cases, sim):
        order = [names[i] for i in row.argsort()[::-1]]
        rank = order.index(case["expected_skill"]) + 1 if case["expected_skill"] in names else None
        rec = {"query": case["query"], "tier": case.get("tier", "unspecified"),
               "expected": case["expected_skill"], "top1": order[0],
               "top1_score": round(float(row.max()), 4), "rank": rank}
        per_case.append(rec)
        t = tiers.setdefault(rec["tier"], {"n": 0, "top1": 0, "topn": 0})
        t["n"] += 1
        t["top1"] += int(rank == 1)
        t["topn"] += int(rank is not None and rank <= top)
    return {"skills": len(skills), "n_cases": len(cases), "top": top,
            "tiers": {k: {**v, "top1_rate": round(v["top1"] / v["n"], 4),
                          f"top{top}_rate": round(v["topn"] / v["n"], 4)} for k, v in tiers.items()},
            "overall": {"top1": sum(1 for r in per_case if r["rank"] == 1),
                        f"top{top}": sum(1 for r in per_case if r["rank"] and r["rank"] <= top)},
            "results": per_case}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills-dir", type=Path, required=True)
    ap.add_argument("--queries", type=Path, required=True)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-cases", action="store_true")
    args = ap.parse_args()

    if not args.skills_dir.is_dir():
        print(f"[FATAL] 技能目录不存在：{args.skills_dir}", file=sys.stderr)
        return 2
    skills = load_skills(args.skills_dir)
    cases = json.loads(args.queries.read_text(encoding="utf-8"))
    if not skills or not cases:
        print(f"[FATAL] 零输入不得记 PASS：skills={len(skills)} cases={len(cases)}", file=sys.stderr)
        return 2
    missing = {c["expected_skill"] for c in cases} - {s["name"] for s in skills}
    if missing:
        print(f"[FATAL] 查询里点名了清单中不存在的技能：{sorted(missing)}", file=sys.stderr)
        return 2

    res = evaluate(skills, cases, args.top)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    topn_key = "top%d_rate" % args.top
    o = res["overall"]
    n = res["n_cases"]
    print("技能 %d 个 / 查询 %d 条 / Top-N=%d" % (res["skills"], n, args.top))
    print("%-10s%6s%8s%11s%11s" % ("层级", "样本", "Top-1", "Top-1率", "Top-N率"))
    for t, v in res["tiers"].items():
        print("%-10s%6d%8d%10.1f%%%10.1f%%"
              % (t, v["n"], v["top1"], v["top1_rate"] * 100, v[topn_key] * 100))
    print("%-10s%6d%8d%10.1f%%%10.1f%%"
          % ("合计", n, o["top1"], o["top1"] / n * 100, o["top%d" % args.top] / n * 100))
    if args.show_cases:
        for r in res["results"]:
            if r["rank"] == 1:
                flag = "ok "
            elif r["rank"] and r["rank"] <= args.top:
                flag = "top"
            else:
                flag = "MISS"
            print("  [%s] rank=%s %s -> %s (期望 %s)"
                  % (flag, r["rank"], r["query"], r["top1"], r["expected"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
