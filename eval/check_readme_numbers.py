#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_readme_numbers.py — README 分层命中率表 ⇄ 活算对账（M-8 后半，2026-09-29）。

立它的理由（对标报告 §4 M-8 未做的一半「逐 claim 双向 diff 工具」与
docs/DEBT_UNWIRED.md L-10 前提）：散文主张没有显式句柄时，逐句猜语义的
对账器第一版就命中 50 余处排版噪声（R236 补注③：不可解参数不配当闸）。
本件只核**数字表**这一类有精确句柄的主张 —— README.md 里那张
`| 档 | 样本 | Top-1 | Top-3 |` 表（easy/medium/hard/合计），每格都是一句
「现算应得 X」的断言，改分词器/改语料/改表任一处即红并点名到格。

取数面 = 与 CLI 同一批函数（`hitrate_cli.evaluate`，top=3），不是第二套算法；
表缺失/语料零输入/技能零件 ⇒ rc=2（UNVERIFIED，R247：空面不得当通过）。
退出码：0=全格一致 / 1=差集非空（逐格点名）/ 2=前提缺失。
用法: python eval/check_readme_numbers.py [--selftest]
"""
import json
import os
import re
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
sys.path.insert(0, EVAL_DIR)

README = os.path.join(PROJECT_DIR, "README.md")
SKILLS_DIR = os.path.join(PROJECT_DIR, "examples", "agent-skills", "skills")
QUERIES = os.path.join(PROJECT_DIR, "examples", "agent-skills", "queries.json")
TOP = 3
TIERS = ("easy", "medium", "hard")

ROW_RE = re.compile(
    r"^\|\s*(easy|medium|hard)\s*\|\s*(\d+)\s*\|\s*([\d.]+)%\s*\|\s*([\d.]+)%\s*\|",
    re.I)
TOTAL_RE = re.compile(
    r"^\|\s*合计\s*\|\s*(\d+)\s*\|\s*\*?\*?([\d.]+)%\*?\*?\s*\|\s*\*?\*?([\d.]+)%\*?\*?\s*\|")


class PremiseError(Exception):
    pass


def _load_hitrate():
    try:
        from hitrate_cli import evaluate, load_skills
    except ImportError:
        from eval.hitrate_cli import evaluate, load_skills  # type: ignore
    return evaluate, load_skills


def parse_table(text):
    """返回 {tier: (n, top1, top3), '合计': (n, top1, top3)}；表缺失即 {}。"""
    found = {}
    for line in text.splitlines():
        m = ROW_RE.match(line.strip())
        if m:
            found[m.group(1).lower()] = (int(m.group(2)), float(m.group(3)),
                                         float(m.group(4)))
            continue
        t = TOTAL_RE.match(line.strip())
        if t:
            found["合计"] = (int(t.group(1)), float(t.group(2)), float(t.group(3)))
    return found


def recompute():
    """活算各档与合计（百分比保留 1 位小数，与表同口径）。"""
    evaluate, load_skills = _load_hitrate()
    from pathlib import Path
    skills = load_skills(Path(SKILLS_DIR))
    if not skills:
        raise PremiseError(f"技能零件（取数面 {SKILLS_DIR}）：零输入不返回空候选")
    if not os.path.exists(QUERIES):
        raise PremiseError(f"查询文件缺失：{QUERIES}")
    with open(QUERIES, encoding="utf-8") as fh:
        cases = json.load(fh)
    if not cases:
        raise PremiseError("查询零条：空面不得当通过")
    rep = evaluate(skills, cases, TOP)
    out = {}
    for tier in TIERS:
        t = rep["tiers"].get(tier)
        if t is None:
            raise PremiseError(f"活算缺 {tier} 档（语料面变了，表与语料须同批改）")
        out[tier] = (t["n"], round(t["top1_rate"] * 100, 1),
                     round(t[f"top{TOP}_rate"] * 100, 1))
    n = rep["n_cases"]
    out["合计"] = (n, round(rep["overall"]["top1"] / n * 100, 1),
                   round(rep["overall"][f"top{TOP}"] / n * 100, 1))
    return out


def check(readme_text=None, live=None):
    """返回 (rc, issues)。issues 逐格点名，空即一致。"""
    if readme_text is None:
        if not os.path.exists(README):
            return 2, ["前提缺失：README.md 不存在"]
        with open(README, encoding="utf-8") as fh:
            readme_text = fh.read()
    table = parse_table(readme_text)
    want = list(TIERS) + ["合计"]
    if any(k not in table for k in want):
        return 2, [f"前提缺失：分层表缺行（现有 {sorted(table)}，期望 {want}）"]
    try:
        live = recompute() if live is None else live
    except PremiseError as exc:
        return 2, [f"前提缺失：{exc}"]
    issues = []
    for k in want:
        tn, t1, t3 = table[k]
        ln, l1, l3 = live[k]
        if (tn, t1, t3) != (ln, l1, l3):
            issues.append(f"README 分层表[{k}]声明({tn}, {t1}%, {t3}%)≠活算({ln}, {l1}%, {l3}%)")
    return (1 if issues else 0), issues


def _selftest():
    """双向自证（②/②-e）：真面绿；改一格恰好点名该格；删表即 rc=2。"""
    legs, red = [], []

    rc, issues = check()
    legs.append(("真面全格一致", rc == 0 and issues == []))
    if not (rc == 0 and issues == []):
        red.append(f"真面腿失败 rc={rc} issues={issues}")

    with open(README, encoding="utf-8") as fh:
        text = fh.read()
    mutated = text.replace("| hard | 15 | 53.3% | 80.0% |",
                           "| hard | 15 | 99.9% | 80.0% |", 1)
    assert mutated != text, "变异没注入（表行形态变了？先修变异再谈自证）"
    rc, issues = check(readme_text=mutated)
    ok = rc == 1 and sorted(issues) == [
        "README 分层表[hard]声明(15, 99.9%, 80.0%)≠活算(15, 53.3%, 80.0%)"]
    legs.append(("改 hard 格恰好点名 hard", ok))
    if not ok:
        red.append(f"变异腿失败 rc={rc} issues={issues}")

    rc, issues = check(readme_text="无表文档\n")
    ok = rc == 2 and len(issues) == 1
    legs.append(("删表即 UNVERIFIED", ok))
    if not ok:
        red.append(f"空面腿失败 rc={rc} issues={issues}")

    print(f"[GATE:readme-numbers-selftest-{'pass' if not red else 'FAIL'}] "
          f"{sum(1 for _, ok in legs if ok)}/{len(legs)}")
    for name, ok in legs:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}")
    return 1 if red else 0


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if "--selftest" in argv:
        return _selftest()
    rc, issues = check()
    if rc == 0:
        print("readme-numbers PASS: 分层表 4 行 12 格与活算一致")
    elif rc == 1:
        print("readme-numbers FAIL:")
        for i in issues:
            print(f"  - {i}")
    else:
        print("readme-numbers UNVERIFIED:")
        for i in issues:
            print(f"  - {i}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
