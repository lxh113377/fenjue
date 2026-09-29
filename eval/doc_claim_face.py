#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_claim_face.py — 文档里的端点计数必须与仓内真相源一致（缺判据即判 UNVERIFIED）。

立判据的一手缺陷（2026-09-29 对标轮实测）：
    `README.en.md` 写 "Cross-platform sync | 6 agents (WB / TR / CX / HM / ZC / OC)"，
    而**同一个仓**的 `eval/truth_constants.json` 里 `endpoints.active` 实测 7 项
    （wb/tr/cx/hm/zc/oc/qd）。`README.md`（中文面）已经把「六端」当成历史错误改掉，
    并在「实际使用案例」里主张「写死数字会被抓」——但英文面没人管：
    现成的 `eval/hardcoded_count_check.py` 判的是注册表 JSON 内部计数
    （`checked: 7` 全为 platform-*.json 的 skills_count⇄skills_list），
    文档面对象它一个都不看。⇒ 那句对外主张当时只对了一半。

口径：
    - 权威值从 `eval/truth_constants.json` 现算，本文件**不写端数常量**（避免第二份真相）。
    - 取数面 = 仓根 `README*.md` / `AGENTS.md` / `index.md` / `llms.txt` / `docs/*.md`，
      按结构单位（文件×命中行）记账，不按"扫到几个文件"。
    - 命中形状：`<数字> 个编码助手` / `<数字> agents` / `<数字> 端`。
    - 取数面为空 ⇒ UNVERIFIED（rc=2）：判据没看见东西不等于通过。

用法: python eval/doc_claim_face.py [--selftest]
退出码: 0=一致 / 1=有漂移(逐条点名) / 2=前提缺失(真相源或取数面不可读)
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRUTH = os.path.join(ROOT, "eval", "truth_constants.json")
FACE_PATTERNS = ["README*.md", "AGENTS.md", "index.md", "llms.txt",
                 os.path.join("docs", "*.md")]
# 数字与端点名词紧邻才算「在声明端数」；中间隔了别的词一律不判（宁漏不误伤）。
CLAIM_RE = re.compile(r"(\d+)\s*(?:个)?\s*(?:编码助手|端(?:到)?\b|agents?\b)", re.I)
# 行内代码 = 逐字引用，不是本仓在主张。本判据上线第二轮就抓到这个形状：
# docs/CASE_STUDY.md 要留痕「README.en.md 曾写 `6 agents`」这类**历史错值**，
# 而历史留痕不许改写（本仓铁律）⇒ 判据若把引文当主张，就等于逼人改掉证据。
# 所以匹配前先剥掉 `...` 片段；配套反例腿见 --selftest（裸声明必须命中、引文必须不命中）。
CODE_SPAN_RE = re.compile(r"`[^`]*`")


def strip_code(text: str) -> str:
    return CODE_SPAN_RE.sub("", text)


def authoritative_count() -> int:
    with open(TRUTH, encoding="utf-8-sig") as f:
        data = json.load(f)
    active = data["endpoints"]["active"]
    if not isinstance(active, list) or not active:
        raise ValueError("endpoints.active 不是非空列表，无法作为权威值")
    return len(active)


def face_files() -> list[str]:
    files: set[str] = set()
    for pat in FACE_PATTERNS:
        files.update(glob.glob(os.path.join(ROOT, pat)))
    return sorted(files)


def scan(files: list[str], want: int) -> tuple[list[str], int, list[str]]:
    """返回 (漂移清单, 命中数, 读不了的文件)。

    读不了不抛异常：判据自己崩掉的输出，和它想拦的违例，长得一模一样（rc≠0 + 无读数），
    归因成本会全压到下一个不带记忆的人身上。读不了的文件单列成盲区，不复用「零命中」。
    """
    bad, hits, unreadable = [], 0, []
    for path in files:
        try:
            f = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            unreadable.append(os.path.relpath(path, ROOT).replace(os.sep, "/"))
            continue
        with f:
            for line_no, line in enumerate(f, 1):
                for m in CLAIM_RE.finditer(strip_code(line)):
                    hits += 1
                    got = int(m.group(1))
                    if got != want:
                        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                        bad.append(f"{rel}:{line_no} 声明 {got}，真相源 {want}｜{line.strip()[:80]}")
    return bad, hits, unreadable


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    if not os.path.isfile(TRUTH):
        print(f"doc-claims UNVERIFIED: 真相源缺失 {os.path.relpath(TRUTH, ROOT)}", file=sys.stderr)
        return 2
    try:
        want = authoritative_count()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"doc-claims UNVERIFIED: 真相源解析失败（{exc}）", file=sys.stderr)
        return 2
    files = face_files()
    if not files:
        print("doc-claims UNVERIFIED: 取数面为空，检查未发生（盲区≠零）", file=sys.stderr)
        return 2
    bad, hits, unreadable = scan(files, want)
    if unreadable:
        print(f"doc-claims UNVERIFIED: {len(unreadable)} 份文档读不了 "
              f"（盲区，不构成通过）：{unreadable[:5]}", file=sys.stderr)
        return 2
    if bad:
        print(f"doc-claims FAIL: 扫 {len(files)} 份文档 / {hits} 处端数声明，漂移 {len(bad)} 处")
        for b in bad:
            print("  " + b)
        return 1
    print(f"doc-claims PASS: 扫 {len(files)} 份文档 / {hits} 处端数声明，与真相源 {want} 全一致")
    return 0


def selftest() -> int:
    """两条腿各绑一个方向：注入漂移必须红；把真相源撤掉必须 UNVERIFIED 而不是 PASS。"""
    import tempfile

    want = authoritative_count()
    with tempfile.TemporaryDirectory() as td:
        planted = os.path.join(td, "README.probe.md")
        with open(planted, "w", encoding="utf-8") as f:
            f.write(f"Cross-platform sync | {want + 4} agents (A / B / C)\n")
        bad, hits, _un = scan([planted], want)
        if hits != 1 or len(bad) != 1:
            print(f"[selftest FAIL] 反例腿没咬住：hits={hits} bad={len(bad)}")
            return 1
        print(f"[selftest ok] 反例腿判红：声明 {want + 4} 对真相源 {want}")
    with tempfile.TemporaryDirectory() as td:
        # 第二条反例腿（方向相反）：**逐字引用不得被当成主张**。
        # 没有这条腿，判据就会逼作者改掉历史错值的留痕——那是本仓铁律禁止的事。
        cited = os.path.join(td, "CITE.md")
        with open(cited, "w", encoding="utf-8") as f:
            f.write(f"英文 README 曾写 `{want - 1} agents`，现值以 truth_constants 为准\n")
        bad2, hits2, _ = scan([cited], want)
        if hits2 or bad2:
            print(f"[selftest FAIL] 引文腿被误判成主张：hits={hits2} bad={bad2}")
            return 1
        print("[selftest ok] 引文腿不误报（行内代码=逐字引用，不计主张）")
    with tempfile.TemporaryDirectory() as td:
        blank = os.path.join(td, "blank.md")
        open(blank, "w", encoding="utf-8").close()
        if scan([blank], want)[1] != 0:
            print("[selftest FAIL] 空文件不应产生命中")
            return 1
        ghost = os.path.join(td, "not-there.md")
        bad_g, hits_g, un_g = scan([ghost], want)
        if un_g != ["../.."] and len(un_g) != 1:
            print("[selftest FAIL] 读不了的文件没进盲区清单")
            return 1
        print(f"[selftest ok] 空面不误报、读不了记盲区（hits={hits_g} 盲区={len(un_g)}）")
    print("[GATE:doc-claims-selftest-pass]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
