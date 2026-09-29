#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_claim_face.py — 文档里的可现算计数必须与仓内实测一致（缺判据即判 UNVERIFIED）。

立判据的一手缺陷（2026-09-29 对标轮实测）：
    `README.en.md` 写 "Cross-platform sync | 6 agents (WB / TR / CX / HM / ZC / OC)"，
    而**同一个仓**的 `eval/truth_constants.json` 里 `endpoints.active` 实测 7 项
    （wb/tr/cx/hm/zc/oc/qd）。`README.md`（中文面）已经把「六端」当成历史错误改掉，
    并在「实际使用案例」里主张「写死数字会被抓」——但英文面没人管：
    现成的 `eval/hardcoded_count_check.py` 判的是注册表 JSON 内部计数
    （`checked: 7` 全为 platform-*.json 的 skills_count⇄skills_list），
    文档面对象它一个都不看。⇒ 那句对外主张当时只对了一半。

同一天第二次复发，形态是「判据在场、取数面只有一格」（对标第 79 轮一手）：
    本件当时判绿，读数 `doc-claims PASS: 扫 12 份文档 / 2 处端数声明`，
    而同一批 README 里 **6 类计数已经全失真**——`664 passed, 48 skipped` 对实跑
    `655 passed, 49 skipped`；`712 条用例` 对 704；`48 条跳过` 对 49；
    `70 个测试模块`（README「与源仓的关系」行）对盘面 74；`:81` 又写 74。
    门禁全绿 ≠ 它比过那些数。⇒ 端数一族之外一律是盲区，而盲区长得像通过。
    本轮因此把「计数族」做成表：**每族的权威值现算**，判据内不写第二份常量；
    取不到的族记**盲区**并显式印出，禁止复用「命中 0 = 通过」这个形状。

口径：
    - 权威值全部现算：端数 ← `eval/truth_constants.json`；测试模块数 ← `eval/tests/test_*.py`
      的实际件数；pytest 汇总行 ← 由调用方喂进来的**同一次跑批**日志（`--from-pytest-log`）。
    - 取数面 = 仓根 `README*.md` / `AGENTS.md` / `index.md` / `llms.txt` / `docs/*.md`
      / `eval/tests/EXCLUDED.md`，按结构单位（文件×命中行）记账，不按"扫到几个文件"。
    - 行内代码 = 逐字引用（历史错值留痕），剥掉后再匹配；配套反例腿见 --selftest。
    - 取数面为空 ⇒ UNVERIFIED（rc=2）：判据没看见东西不等于通过。
    - `--audit-receipts`（advisory，不改 rc）：列出「有计数、同行无复算命令也无时点」的声明。
      它现在只报不拦，因为按 R236 补注③ 与「新指标先量误报率」的规矩，一条第一版就
      命中 40 余行的尺子没有资格直接当闸——先量面，再谈升档。

用法: python eval/doc_claim_face.py [--selftest] [--from-pytest-log <路径>] [--audit-receipts]
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
                 os.path.join("docs", "*.md"),
                 os.path.join("eval", "tests", "EXCLUDED.md")]
# 「现状面」文件：里面的数字就是本仓此刻的主张。docs/ 下的 CASE_STUDY / DEBT_UNWIRED
# 不在此列——它们逐条写明「本轮实测」，属时点快照（历史留痕不许改写）。
CURRENT_FACE_PATTERNS = ["README.md", "README.en.md"]
# 数字与端点名词紧邻才算「在声明端数」；中间隔了别的词一律不判（宁漏不误伤）。
CLAIM_RE = re.compile(r"(\d+)\s*(?:个)?\s*(?:编码助手|端(?:到)?\b|agents?\b)", re.I)
# 测试模块声明：`74 个测试模块`。刻意不收 `跟踪文件数`/`wheel 体积` 这类
# 「每加一个文件就要改一次文档」的形状——一次正常提交就变不了绿的判据没资格当闸，
# 那两类改成文档里直接给复算命令（见 --audit-receipts 的留痕面）。
TEST_MODULE_RE = re.compile(r"(\d+)\s*个(?:测试模块|test modules?)", re.I)
# pytest 汇总声明：`655 passed, 49 skipped`。词序不固定（pytest 会把
# `1 failed, 654 passed, 49 skipped` 里的 failed 排在最前），所以不按顺序匹配，
# 而是把整行拆成 `<数字> <词>` 对再取——按顺序匹配的那条腿我在 selftest 里造了
# 一个反例（failed 在前的红面行）来钉住这件事：当时它被读成绿面权威值。
SUMMARY_TOKEN_RE = re.compile(r"(\d+)\s+(passed|failed|skipped|errors|xfailed|error)", re.I)
# 「非本面」措辞集：对账发生在 CI，所以本面＝CI 面，命中这些词的行按「它声明的是另一台机器」豁免。
# 刻意**不含** "Linux"——CI runner 就是 Linux，把 `CI 面（Linux runner）` 那句豁免掉，
# 这条腿就永远没内容可比了（第一版正是这么写的，selftest 的「CI 面错值必须红」腿当场不绿）。
OTHER_FACE_RE = re.compile(r"(本机|开发机|开发面|Windows|macOS|local|我的机器)", re.I)

# 留痕审计（advisory）认的「有复算依据」标记：复算命令 / 时点 / 具面。
RECEIPT_RE = re.compile(r"(复算|实测|命令|`python |`gh |`git |`ls |`curl |基准日|@"
                        r"\d{4}-\d{2}-\d{2}|20\d\d-\d\d-\d\d|face=|面)")
# ⚠️ 结尾不写 `\b`：Python 把 CJK 当词字符，`处\b` 在「88 处告警」里根本不成界，
# 首跑就把整条审计读成「零缺留痕」（实测 missing=[]），等于一条恒绿的尺子。
COUNT_CLAIM_RE = re.compile(
    r"\b(\d[\d,]*)\s*(?:个测试模块|条用例|passed|skipped|处|条|个文件|跟踪文件|KB|MB)",
    re.I)
CODE_SPAN_RE = re.compile(r"`[^`]*`")


def strip_code(text: str) -> str:
    return CODE_SPAN_RE.sub("", text)


RED_TOKENS = ("failed", "error", "errors")


def parse_summary_line(line: str) -> tuple[int, int] | None:
    """一行 pytest 汇总 → (passed, skipped)。缺任一项或含 failed/error ⇒ None。

    `failed` 在内一律拒绝是有原因的：把「1 failed, 654 passed」读成绿面权威值，
    就是本仓反复拦的那种「聚合掩盖单节点失败」。
    """
    got: dict[str, int] = {}
    for m in SUMMARY_TOKEN_RE.finditer(line):
        got.setdefault(m.group(2).lower(), int(m.group(1)))
    if "passed" not in got or "skipped" not in got:
        return None
    if any(t in got for t in RED_TOKENS):
        return None
    return got["passed"], got["skipped"]


def authoritative_count() -> int:
    with open(TRUTH, encoding="utf-8-sig") as f:
        data = json.load(f)
    active = data["endpoints"]["active"]
    if not isinstance(active, list) or not active:
        raise ValueError("endpoints.active 不是非空列表，无法作为权威值")
    return len(active)


def authoritative_test_modules() -> int:
    """权威值 = 盘面 `eval/tests/test_*.py` 的实际件数，不取任何文档里的说法。"""
    found = glob.glob(os.path.join(ROOT, "eval", "tests", "test_*.py"))
    if not found:
        raise ValueError("eval/tests 下没有 test_*.py，取数面为空")
    return len(found)


def read_pytest_face(path: str) -> tuple[int, int]:
    """从跑批日志取最后一次汇总行。取不到就抛——不返回 (0, 0)。"""
    with open(path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    face = None
    for line in text.splitlines():
        parsed = parse_summary_line(line)
        if parsed:
            face = parsed
    if face is None:
        raise ValueError(f"日志里解析不到「N passed, M skipped」绿面汇总行：{path}")
    return face


def face_files() -> list[str]:
    files: set[str] = set()
    for pat in FACE_PATTERNS:
        files.update(glob.glob(os.path.join(ROOT, pat)))
    return sorted(files)


def current_face_files() -> list[str]:
    """现状面（README 双语两份）——pytest 汇总族只在这两门上真值对账。"""
    files: set[str] = set()
    for pat in CURRENT_FACE_PATTERNS:
        files.update(glob.glob(os.path.join(ROOT, pat)))
    return sorted(files)


def scan(files: list[str], want: int) -> tuple[list[str], int, list[str]]:
    """端数族。返回 (漂移清单, 命中数, 读不了的文件)。

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
                        bad.append(f"{_rel(path)}:{line_no} 声明 {got}，真相源 {want}"
                                   f"｜{line.strip()[:80]}")
    return bad, hits, unreadable


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def authoritative_excluded_modules() -> int:
    """已摘除模块数 = `eval/tests/EXCLUDED.md` 里具名行的条数（现算，去重）。

    注意这一族盖不到「源仓共 90 个」那半边：源仓是私有面，子集里既没有它的工作树也没有
    它的 git ⇒ 硬拿子集去比源仓，就是「判据量了另一个面」的复发。那两句的正确处置是
    在文档里给出复算命令（`git -C <源仓> ls-tree -r --name-only HEAD eval/tests/`），
    而不是在本判据里存一个 90。
    """
    path = os.path.join(ROOT, "eval", "tests", "EXCLUDED.md")
    names: set[str] = set()
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.startswith("|"):
                continue
            cells = [c.strip().strip("`") for c in line.split("|")]
            if len(cells) >= 3 and cells[1].startswith("test_") and cells[1].endswith(".py"):
                names.add(cells[1])
    if not names:
        raise ValueError("EXCLUDED.md 里解析不出任何具名模块行")
    return len(names)


def scan_test_modules(files: list[str], allowed: set[int]) -> tuple[list[str], int]:
    """`N 个测试模块` 必须落在本仓**现算得出的合法值集合**内，否则点名。

    为什么是集合而不是唯一权威值：同一个名词在文档里有两种真所指——
      `74 个测试模块`（在仓）与 `20 个测试模块未随子集分发`（已摘除）。
    第一版用「同行关键词」判哪一面，真面两个方向都判错（一手）：
      · README.md:81「74 个测试模块；未随包分发的模块及其原因见 EXCLUDED.md」——
        「未随包」修饰的是**另一批**模块，却落在同一行 ⇒ 74 被读成摘除面而假红；
      · README.md:216「另有 20 个测试模块**没有**随本子集分发」——粗体标记把
        `没有随` 打断 ⇒ 20 又读成在仓面而假红。
    两处错同根：**用散文词判断句法角色**。所以改为「凡合法现算值均放行」，
    集合外的任何数（含本仓历史上真用过的 70）一律点名。
    限度（写清楚，不假装覆盖）：把「在仓数」误写成摘除数这一格本族放行，
    由 `--audit-receipts` 的留痕面与评审面兜，不靠这里猜语义。
    """
    bad, hits = [], 0
    for path in files:
        try:
            f = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with f:
            for line_no, line in enumerate(f, 1):
                for m in TEST_MODULE_RE.finditer(strip_code(line)):
                    hits += 1
                    got = int(m.group(1))
                    if got not in allowed:
                        bad.append(f"{_rel(path)}:{line_no} 声明 {got} 个测试模块，"
                                   f"不在现算合法值 {sorted(allowed)} 内｜{line.strip()[:80]}")
    return bad, hits


def scan_pytest_summary(files: list[str], face: tuple[int, int]) -> tuple[list[str], int, int]:
    """与**同一次跑批**的汇总行对账。返回 (漂移清单, 本面命中数, 非本面豁免数)。

    两个必须写死的口径（都是本轮实测逼出来的，不是设计偏好）：
    1. **面要标出来才比**。同一份 `main` 本轮实测：Linux CI 面 `654 passed, 58 skipped`、
       Windows 本机面 `655 passed, 49 skipped`——两个数当时都真。第一版不分面直接全比，
       等于逼 README 只准留一个面，那是把「测到了什么」改成「测得了什么」。
       所以：行内出现**别的面**标记（本机/开发机/Windows/Linux 面…）⇒ 记豁免并计数打印；
       **没标面**的行 ⇒ 按「本面」处理（在 CI 里本面就是 CI 面，不给「忘了标面」留逃生门）。
    2. 这一族**不剥行内代码**：`README.md` 把汇总写成 `` `654 passed, 58 skipped` `` 是排版，
       不是逐字引用别人——按引用豁免就等于放过它。
    取数面只认「现状面」文件（`CURRENT_FACE_PATTERNS`）：`docs/CASE_STUDY.md`、
    `docs/DEBT_UNWIRED.md` 按本仓铁律是**时点快照**（写明「本轮实测」），拿今天的跑批
    去判它们＝逼作者改证据。历史留痕的复核方式是**追加更正段**，不是改写。
    """
    want_passed, want_skipped = face
    bad, hits, exempt = [], 0, 0
    for path in files:
        try:
            f = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with f:
            for line_no, line in enumerate(f, 1):
                got = parse_summary_line(line)
                if got is None:
                    continue
                hits += 1
                if OTHER_FACE_RE.search(line):
                    exempt += 1
                    continue
                if got != (want_passed, want_skipped):
                    bad.append(
                        f"{_rel(path)}:{line_no} 声明 {got[0]} passed, {got[1]} skipped，"
                        f"本次跑批实为 {want_passed} passed, {want_skipped} skipped"
                        f"｜面标记须写在**同一行**才算豁免（上一行不算，本判据不按窗口取面）"
                        f"｜{line.strip()[:80]}")
    return bad, hits, exempt


def audit_receipts(files: list[str]) -> list[str]:
    """advisory：计数断言所在行既无复算命令、也无时点/具名面 ⇒ 列为「缺留痕」。"""
    missing = []
    for path in files:
        try:
            f = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with f:
            for line_no, line in enumerate(f, 1):
                if not COUNT_CLAIM_RE.search(line):
                    continue
                if RECEIPT_RE.search(line):
                    continue
                missing.append(f"{_rel(path)}:{line_no}｜{line.strip()[:90]}")
    return missing


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    if not os.path.isfile(TRUTH):
        print(f"doc-claims UNVERIFIED: 真相源缺失 {_rel(TRUTH)}", file=sys.stderr)
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
    all_bad: list[str] = []
    blind: list[str] = []
    lines_out: list[str] = []

    bad, hits, unreadable = scan(files, want)
    if unreadable:
        print(f"doc-claims UNVERIFIED: {len(unreadable)} 份文档读不了 "
              f"（盲区，不构成通过）：{unreadable[:5]}", file=sys.stderr)
        return 2
    all_bad += bad
    lines_out.append(f"  族[端数] 命中 {hits} 处，权威值现算 {want}，漂移 {len(bad)}")

    # 族[测试模块]：在仓数与摘除数两个权威值都要现算；任一侧取不到 ⇒ 该侧记盲区。
    want_mod = want_excl = None
    try:
        want_mod = authoritative_test_modules()
    except ValueError as exc:
        blind.append(f"测试模块（在仓面）：{exc}")
    try:
        want_excl = authoritative_excluded_modules()
    except (OSError, ValueError) as exc:
        blind.append(f"测试模块（摘除面）：{exc}")
    if want_mod is not None and want_excl is not None:
        allowed = {want_mod, want_excl}
        bad_m, hits_m = scan_test_modules(files, allowed)
        all_bad += bad_m
        lines_out.append(f"  族[测试模块] 命中 {hits_m} 处，"
                         f"现算合法值 {sorted(allowed)}（在仓 {want_mod}/摘除 {want_excl}），"
                         f"漂移 {len(bad_m)}")

    # 族[pytest 汇总]：只有调用方给了「同一次跑批」的日志才核；没给就是盲区，
    # 明写出来——把「这次没喂日志」读成「文档与跑批一致」是本轮要根治的那个形状。
    log_path = None
    if "--from-pytest-log" in argv:
        i = argv.index("--from-pytest-log")
        if i + 1 < len(argv):
            log_path = argv[i + 1]
    if log_path:
        try:
            face = read_pytest_face(log_path)
        except (OSError, ValueError) as exc:
            face = None
            blind.append(f"pytest 汇总：{exc}")
        if face is not None:
            cfiles = current_face_files()
            if not cfiles:
                blind.append("pytest 汇总：现状面为空（README*.md 没读到）")
            else:
                bad_p, hits_p, exempt_p = scan_pytest_summary(cfiles, face)
                all_bad += bad_p
                lines_out.append(f"  族[pytest汇总] 现状面 {len(cfiles)} 份 / 本面命中 {hits_p} 处"
                                 f"（另有 {exempt_p} 处声明的是别的面，豁免），"
                                 f"本次跑批 {face[0]} passed/{face[1]} skipped，漂移 {len(bad_p)}")
    else:
        blind.append("pytest 汇总：未喂跑批日志（本面不核；CI 的 Test suite 步喂）")

    for b in lines_out:
        print(b)
    if "--audit-receipts" in argv:
        miss = audit_receipts(files)
        print(f"  [advisory] 缺复算留痕的计数断言 {len(miss)} 行（本行不改 rc）：")
        for m in miss[:12]:
            print("    " + m)
        if len(miss) > 12:
            print(f"    …其余 {len(miss) - 12} 行略")
    if blind:
        print(f"  [盲区] {len(blind)} 族未核： " + " ｜ ".join(blind))
    if all_bad:
        print(f"doc-claims FAIL: 扫 {len(files)} 份文档，漂移 {len(all_bad)} 处")
        for b in all_bad:
            print("  " + b)
        return 1
    print(f"doc-claims PASS: 扫 {len(files)} 份文档，{len(lines_out)} 族核过，端数与真相源 {want} 一致")
    return 0


def selftest() -> int:
    """每族至少两条方向相反的腿：注入漂移必须红；撤掉权威值必须 UNVERIFIED/盲区而不是 PASS。"""
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

    # ── 族[测试模块] 四腿：集合外必红 / 在仓值必绿 / 摘除值必绿（防假红回归）/ 旧错值必红 ──
    want_mod = authoritative_test_modules()
    want_excl = authoritative_excluded_modules()
    allowed = {want_mod, want_excl}
    with tempfile.TemporaryDirectory() as td:
        planted = os.path.join(td, "README.mod.md")
        with open(planted, "w", encoding="utf-8") as f:
            f.write(f"仓内有 {want_mod + 9} 个测试模块，逐模块原因见 EXCLUDED\n")
        bad_m, hits_m = scan_test_modules([planted], allowed)
        if hits_m != 1 or len(bad_m) != 1:
            print(f"[selftest FAIL] 测试模块反例腿没咬住：hits={hits_m} bad={len(bad_m)}")
            return 1
        print(f"[selftest ok] 测试模块族判红：声明 {want_mod + 9} 不在合法值 {sorted(allowed)} 内")
        ok_line = os.path.join(td, "README.ok.md")
        with open(ok_line, "w", encoding="utf-8") as f:
            f.write(f"仓内有 {want_mod} 个测试模块\n")
        if scan_test_modules([ok_line], allowed)[0]:
            print("[selftest FAIL] 正确值被误判成漂移（对偶腿不绿 ⇒ 判据缺陷，不是语料缺陷）")
            return 1
        print("[selftest ok] 测试模块族对偶腿转绿：声明值==在仓现算")
        # 第三条腿钉的是本判据**首跑真面时的两处假红**（README:81 的 74 与 :216 的 20）：
        # 关键词分类把两个方向都判错过，改成合法值集合后这两句都必须放行。
        both = os.path.join(td, "README.both.md")
        with open(both, "w", encoding="utf-8") as f:
            f.write(f"| `eval/tests/` | {want_mod} 个测试模块；未随包分发的模块及其原因见 EXCLUDED.md |\n")
            f.write(f"另有 {want_excl} 个测试模块**没有**随本子集分发\n")
        bad_b = scan_test_modules([both], allowed)[0]
        if bad_b:
            print(f"[selftest FAIL] 两种真所指又被判成漂移（假红回归）：{bad_b}")
            return 1
        print(f"[selftest ok] 在仓值与摘除值同放行：{want_mod} 与 {want_excl} 都是合法现算值")
        stale = os.path.join(td, "README.stale.md")
        with open(stale, "w", encoding="utf-8") as f:
            f.write("覆盖 70 个测试模块 / 712 条用例\n")
        if not scan_test_modules([stale], allowed)[0]:
            print("[selftest FAIL] 旧错值 70 没被咬住（集合退化成了白名单）")
            return 1
        print("[selftest ok] 历史错值 70 判红：合法值集合不是白名单")

    # ── 族[pytest 汇总] 腿：错值必红 / 对偶必绿 / 标了别面的行必须豁免 / 没标面的必须比 ──
    with tempfile.TemporaryDirectory() as td:
        doc = os.path.join(td, "README.face.md")
        with open(doc, "w", encoding="utf-8") as f:
            f.write("干净 clone 面实测：664 passed, 48 skipped，rc=0\n")
        bad_p, hits_p, _x = scan_pytest_summary([doc], (655, 49))
        if hits_p != 1 or len(bad_p) != 1:
            print(f"[selftest FAIL] pytest 汇总反例腿没咬住：hits={hits_p} bad={len(bad_p)}")
            return 1
        print("[selftest ok] pytest 汇总族判红：声明 664/48 对跑批 655/49")
        bad_p2, hits_p2, _x2 = scan_pytest_summary([doc], (664, 48))
        if hits_p2 != 1 or bad_p2:
            print(f"[selftest FAIL] pytest 汇总对偶腿不绿：hits={hits_p2} bad={len(bad_p2)}")
            return 1
        print("[selftest ok] pytest 汇总族对偶腿转绿：声明值==跑批值")
        # 面标记两半都要测（只测一边，就会在另一个方向上造出必红的闸）：
        two = os.path.join(td, "README.two.md")
        with open(two, "w", encoding="utf-8") as f:
            f.write("CI 面（Linux runner，与 CI 徽章同一次跑批）：654 passed, 58 skipped\n")
            f.write("Windows 本机面（2026-09-29 实测）：655 passed, 49 skipped\n")
        bad_t, hits_t, exempt_t = scan_pytest_summary([two], (654, 58))
        if hits_t != 2 or exempt_t != 1 or bad_t:
            print(f"[selftest FAIL] 面标记没生效：hits={hits_t} 豁免={exempt_t} bad={bad_t}")
            return 1
        bad_t2, _h2, _e2 = scan_pytest_summary([two], (654, 57))
        if len(bad_t2) != 1:
            print(f"[selftest FAIL] 没标面的行没被当本面比：bad={len(bad_t2)}")
            return 1
        print("[selftest ok] 面标记双向：本机面那行豁免、未标面的 CI 行照比（错值判红）")
        # 第四条腿：面标记**必须在同一行**。真面第一版就因为 markdown 换行把「本机面（Windows…」
        # 留在上一行，导致 655/49 那行没被豁免 ⇒ CI 必红。这条腿钉住「不引入窗口逻辑」这个决定。
        wrapped = os.path.join(td, "README.wrap.md")
        with open(wrapped, "w", encoding="utf-8") as f:
            f.write("- 本机面（Windows + Python 3.12.2，按精确 pin 装出来的隔离 venv）：\n")
            f.write("  `655 passed, 49 skipped`，rc=0\n")
        bad_w, hits_w, exempt_w = scan_pytest_summary([wrapped], (654, 58))
        if exempt_w != 0 or len(bad_w) != 1:
            print(f"[selftest FAIL] 面标记换行后仍被豁免（本判据按行取面，不扩窗口）："
                  f"豁免={exempt_w} bad={len(bad_w)}")
            return 1
        print("[selftest ok] 面标记换行不生效：豁免=0、该行判红并点名「须同行」")

        # 盲区腿（方向相反的一半）：喂一份没有汇总行的日志 ⇒ 必须抛，不得回 (0,0)。
        junk = os.path.join(td, "junk.log")
        with open(junk, "w", encoding="utf-8") as f:
            f.write("collecting ... \nno output here\n")
        try:
            read_pytest_face(junk)
        except ValueError:
            print("[selftest ok] 坏跑批日志记盲区（抛异常，不返回 (0,0) 冒充量到零）")
        else:
            print("[selftest FAIL] 坏跑批日志被读成 (0,0)——零命中与量到零同形")
            return 1
        # 有 failed 的汇总行不得当权威值（否则「636 passed, 2 failed, 49 skipped」
        # 会被读成绿面，正是「聚合掩盖单节点失败」那一族）。
        redlog = os.path.join(td, "red.log")
        with open(redlog, "w", encoding="utf-8") as f:
            f.write("1 failed, 654 passed, 49 skipped in 30.00s\n")
        try:
            read_pytest_face(redlog)
        except ValueError:
            print("[selftest ok] 含 failed 的汇总行拒绝作权威值")
        else:
            print("[selftest FAIL] 红面跑批被当成绿权威值")
            return 1

    # ── advisory 留痕审计：必须真能区分「有复算」与「裸数字」 ──
    with tempfile.TemporaryDirectory() as td:
        a = os.path.join(td, "A.md")
        with open(a, "w", encoding="utf-8") as f:
            f.write("实测 88 处告警（`python -m ruff check .`）\n")
            f.write("另有 122 处告警\n")
        miss = audit_receipts([a])
        if len(miss) != 1 or "122" not in miss[0]:
            print(f"[selftest FAIL] 留痕审计认不出裸数字：{miss}")
            return 1
        print("[selftest ok] 留痕审计：带复算命令的行放行、裸计数行点名")

    print("[GATE:doc-claims-selftest-pass]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
