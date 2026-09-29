#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""command_face_parity.py — 「对外声明的命令面」必须两面一致，且不得声明不存在的命令。

立判据的一手缺陷（2026-09-29 对标轮 §4 M-8 的后半句）：
    报告写「已重写英文面并接线判据；**未做逐 claim 双向 diff 工具**」。中文 README 与英文
    README 在同一天里严重分叉过一次（中文改「六端→七端」时英文没跟），当时的兜底是
    `doc_claim_face.py`——它判的是「文档数字 ⇄ 真相源」，两面各自与真相源对账，
    **不看两面彼此**。于是产生一个它盖不到的形状：两面都"自洽"，但一面承诺了另一面
    根本没有的用法。本件补的就是这一格，且只补这一格：
      · 数字与真相源的对账 = `doc_claim_face.py` 的既有职责，本件**不重复判**（同事实一处判）。
      · 本件判的是**命令面**：入口点、子命令、对外链接，三样都是语言无关的对象，
        所以可以逐 token 双向比，不需要翻译词典，也不会把 mermaid 图的中文标签判成分叉
        （第一版真按"代码块行集合"比，两面差 53 处、全是排版与译名噪声 ⇒
         一条第一版就命中 50 余行的尺子没资格当闸，按 R236 补注③ 收窄到命令 token）。

口径（权威值一律现算，判据内不写第二份常量）：
    入口点集 ← `pyproject.toml` 的 `[project.scripts]` 键；
    子命令集 ← 真跑 `python eval/fenjue_cli.py --help` 后解析 argparse 的 `{a,b,c}` 行
              （取**工具自述**，不去 AST 里数 add_parser——自述与实现不符正是本件要拦的事）；
    取数面 = README.md / README.en.md / llms.txt（llms.txt 是给 agent 读的机器友好面，
             它漏了命令，等于最该发现命令的读者发现不了）。
    取不到权威值、面为空、help 跑不动 ⇒ UNVERIFIED（rc=2）。命中 0 不等于通过。

退出码: 0=两面一致 / 1=差集非空或假承诺(逐条点名) / 2=前提缺失
用法:  python eval/command_face_parity.py [--selftest]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

try:
    import tomllib
except ModuleNotFoundError:  # py<3.11：本仓下限是 3.12，这里只为让"为什么装不出"可读
    tomllib = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
CLI = os.path.join(ROOT, "eval", "fenjue_cli.py")
FACES = ["README.md", "README.en.md", "llms.txt"]
# `fenjue <tok>` 与 `fenjue_cli.py <tok>` 两种 invocation 形态都算声明了子命令：
# 中文 README 用源码树形态、英文用装出来的入口点形态，这是排版差异不是内容差异。
# 两处约束都是本轮被真面咬出来的，别再放宽：
#   · `\s+` 会跨行——README 里一行结尾是 "…fenjue"、下一行开头是 "python" 就被拼成
#     一条"`fenjue python` 假承诺"（实测第一版就这么假红了一次）。只许同行空白。
#   · 只在**代码面**（围栏块 + 行内 code span）里找。散文里的 "fenjue" 后面跟什么
#     都不构成命令主张，而文档写命令一律在代码面，所以这个收窄不丢覆盖。
SUB_MENTION_RE = re.compile(r"fenjue(?:_cli\.py)?[ \t]+([a-z][a-z0-9-]{2,})")
FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


# help 里 argparse 会把子命令块换行续出去（usage 行与 positional 行各一次），
# 取**出现次数最多**的那一组作为自述集合，避免把 usage 的截断行当权威。
HELP_CHOICES_RE = re.compile(r"^\s*\{([a-z][a-z0-9,\- ]*)\}", re.M)


def code_face(text: str) -> str:
    """把一份文档里的"命令面"抽出来：所有围栏块 + 所有行内 code span。"""
    parts = FENCE_RE.findall(text) + INLINE_CODE_RE.findall(text)
    return "\n".join(parts)


class PremiseError(RuntimeError):
    """前提不成立。调用方一律转成 UNVERIFIED，不得转成 PASS。"""


def authoritative_scripts() -> set[str]:
    if tomllib is None:
        raise PremiseError("解释器无 tomllib，读不了 pyproject")
    if not os.path.isfile(PYPROJECT):
        raise PremiseError(f"pyproject 不在场：{_rel(PYPROJECT)}")
    try:
        with open(PYPROJECT, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:  # tomllib 的异常族不止一种，坏文件必须成盲区而不是崩判据
        raise PremiseError(f"pyproject 解析失败：{exc}") from exc
    scripts = set((data.get("project") or {}).get("scripts") or {})
    if not scripts:
        raise PremiseError("[project.scripts] 为空——没有入口点可核，不得判「已核过」")
    return scripts


def authoritative_subcommands() -> set[str]:
    if not os.path.isfile(CLI):
        raise PremiseError(f"CLI 载体不在场：{_rel(CLI)}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run([sys.executable, "-B", CLI, "--help"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=60, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PremiseError(f"--help 跑不动：{exc}") from exc
    # --help 在 argparse 里恒 rc=0；非零说明这个工具连自述能力都坏了
    text = proc.stdout + proc.stderr
    groups = [set(g.split(",")) for g in HELP_CHOICES_RE.findall(text)]
    groups = [g for g in groups if g and all(t.strip() for t in g)]
    if not groups:
        raise PremiseError(f"--help 输出里解析不出子命令自述行（rc={proc.returncode}）")
    best = max(groups, key=len)
    return {t.strip() for t in best if t.strip()}


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def read_face(name: str) -> str:
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        raise PremiseError(f"取数面缺失：{name}")
    with open(path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    if not text.strip():
        raise PremiseError(f"取数面为空文件：{name}（空面不得参与对账）")
    return text


def _code_lines(text: str) -> list[str]:
    """围栏块 + 行内 code span。取两种而不是只取围栏：README 的「可复算项」表把命令
    写在单元格的反引号里（英文面 `python -m pytest -q` 就是这一格），只扫围栏会漏掉它。"""
    return code_face(text).splitlines()


def addopts_carries_quiet() -> bool:
    """权威值：`[tool.pytest.ini_options].addopts` 里是否已有 -q。
    现取不写死——本件的立场是"判据内不存第二份常量"，这条也一样。"""
    if tomllib is None:
        raise PremiseError("解释器无 tomllib，读不了 addopts")
    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    addopts = ((data.get("tool") or {}).get("pytest") or {}).get("ini_options", {}).get("addopts")
    if addopts is None:
        raise PremiseError("pyproject 里没有 [tool.pytest.ini_options].addopts，"
                           "「-q 会不会叠成 -qq」这件事在本仓没有权威面可取")
    return any(t in ("-q", "--quiet", "-qq") for t in str(addopts).split())


# 参数段用 `(.*)` 而不是 `(\S.*)`：写成后者时 `python -m pytest -q`（pytest 与 -q 之间是空格）
# 整行都不匹配 ⇒ 判据对"它最想抓的那个形状"直接失明。是反例腿 5 把它逼出来的：
# 那条腿本想证明"教 -q 必须红"，结果红的是"这面找不到测命令"。
PYTEST_LINE_RE = re.compile(r"^\s*python\s+-m\s+pytest(.*)$")


def check_test_commands(texts: dict[str, str], pair: list[str]) -> tuple[list[str], int]:
    """族[测试命令行]：两面教人跑的那条测试命令必须**逐字相同**，且在 addopts 已带 -q 的
    仓里**不得再写 -q**。

    一手（本轮）：中文 README 写 `python -m pytest`（正确），英文 README 写
    `python -m pytest -q` ⇒ 与 addopts 的 -q 叠成 `-qq`，而 `-qq` 不打
    `N passed, M skipped` 那一行——评委照英文面跑完，拿到的是一份**没有用例数的绿**，
    而本仓 CI 的文档对账步判的正是那一行。同一条缺陷本轮在 `judge_verify.sh` 里
    也咬到过一次（那条回执的 PYTEST_RC=0 后面根本没有汇总行）。
    """
    bad: list[str] = []
    carries = addopts_carries_quiet()
    per_face: dict[str, set[str]] = {}
    for name in pair:
        found = set()
        for line in _code_lines(texts[name]):
            m = PYTEST_LINE_RE.match(line)
            if not m:
                continue
            found.add(line.strip())
            flags = (m.group(1) or "").split()
            if carries and any(f in ("-q", "-qq", "--quiet") for f in flags):
                bad.append(f"{name} 教的 `{line.strip()}` 叠了 -q，而 pyproject 的 addopts "
                           f"已带 -q ⇒ 实际是 -qq，`N passed, M skipped` 汇总行不会输出")
        if not found:
            raise PremiseError(f"{name} 的代码面（围栏块与行内 code span）里找不到任何 "
                               f"`python -m pytest` 行——该面没被测命令可核，不得当成通过")
        per_face[name] = found
    a, b = per_face[pair[0]], per_face[pair[1]]
    for only, who, other in ((a - b, pair[0], pair[1]), (b - a, pair[1], pair[0])):
        for line in sorted(only):
            bad.append(f"双语测试命令面分叉：`{who}` 教 `{line}` 而 `{other}` 没有")
    return bad, len(a | b)


def diff_faces(scripts: set[str], subs: set[str]) -> tuple[list[str], dict]:
    """返回 (违例清单, 读数)。读数里每项都是现算的集合，便于复算而不是只给结论。"""
    bad: list[str] = []
    texts = {name: read_face(name) for name in FACES}
    pair = [n for n in FACES if n.startswith("README")]
    if len(pair) != 2:
        raise PremiseError(f"双语对账需要两份 README 面，当前 FACES={FACES} 只挑出 {pair}")
    reading: dict[str, object] = {"faces": len(texts), "scripts": sorted(scripts),
                                  "subcommands": sorted(subs)}

    for name, text in texts.items():
        missing = sorted(s for s in scripts if s not in text)
        if missing:
            bad.append(f"{name} 未声明入口点 {missing}（权威 [project.scripts] 现算 "
                       f"{len(scripts)} 条）⇒ 读者按本页装完拿不到这些命令")

    declared: dict[str, set[str]] = {}
    for name, text in texts.items():
        cmdtext = code_face(text)
        mentioned = set(SUB_MENTION_RE.findall(cmdtext))
        declared[name] = mentioned & subs
        for g in sorted(mentioned - subs - scripts):
            # 减掉 scripts 是因为名册行（`fenjue fenjue-bench fenjue-hitrate …`）会被读成
            # "`fenjue` 后跟一个子命令"。`fenjue-bench` 本身是权威入口点，不是假承诺。
            bad.append(f"{name} 在代码面声明了权威自述里不存在的子命令 `fenjue {g}`"
                       f"（现算子命令集 {sorted(subs)}）⇒ 假承诺")

    a, b = declared[pair[0]], declared[pair[1]]
    for only, who, other in ((a - b, pair[0], pair[1]), (b - a, pair[1], pair[0])):
        for tok in sorted(only):
            bad.append(f"双语子命令面分叉：`{who}` 声明 `fenjue {tok}` 而 `{other}` 没有")

    reading["declared_subs"] = {k: sorted(v) for k, v in declared.items()}
    bad_t, n_lines = check_test_commands(texts, pair)
    bad += bad_t
    reading["pytest_lines"] = n_lines
    return bad, reading


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    try:
        scripts = authoritative_scripts()
        subs = authoritative_subcommands()
        bad, reading = diff_faces(scripts, subs)
    except PremiseError as exc:
        print(f"cmd-face-parity UNVERIFIED: {exc}", file=sys.stderr)
        return 2
    print(f"  入口点 {len(reading['scripts'])} 条 / 子命令 {len(reading['subcommands'])} 条 / "
          f"面 {reading['faces']} 份")
    print(f"  两面声明的子命令: {reading['declared_subs']}")
    if bad:
        print(f"cmd-face-parity FAIL: {len(bad)} 处（逐条点名）")
        for b in bad:
            print("  " + b)
        return 1
    print(f"cmd-face-parity PASS: 扫 {reading['faces']} 面，入口点全覆盖、"
          f"代码面无假承诺子命令、双语子命令集合相等")
    return 0


# --------------------------------------------------------------------- selftest
def selftest() -> int:
    """六条腿，方向成对：等价面必须绿 / 三种注入必须各红 / 跨行噪声必须不红 / 面缺失必须 UNVERIFIED。"""
    import tempfile

    scripts = authoritative_scripts()
    subs = authoritative_subcommands()
    if not scripts or not subs:
        print("[selftest FAIL] 权威值取不到，反例腿无从谈起")
        return 1
    print(f"[selftest ok] 权威值现算：入口点 {sorted(scripts)} 子命令 {sorted(subs)}")

    def put(tmp: str, name: str, body: str) -> None:
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(body)

    all_names = " ".join(sorted(scripts))
    # 面名必须真叫 README.md / README.en.md：diff_faces 按名字挑双语对，
    # 换成 zh.md/en.md 会走 PremiseError 分支，那是对账前提不成立，不是"测过了"。
    good_cmd = ("```bash\n" + all_names + "\n" + "\n".join(
        f"fenjue {s}" for s in sorted(subs)) + "\npython -m pytest\n```\n")
    with tempfile.TemporaryDirectory() as td:
        saved_root, saved_faces = ROOT, list(FACES)
        try:
            globals()["ROOT"] = td
            # 用切片赋值而不是 `FACES = [...]`：后者会让 FACES 在本函数里变成局部名，
            # 于是前面那句 `list(FACES)` 直接 UnboundLocalError（判据自己崩掉，
            # 和它想拦的违例长得一模一样）。
            FACES[:] = ["README.md", "README.en.md", "llms.txt"]
            put(td, "README.md", good_cmd)
            put(td, "README.en.md", good_cmd)
            put(td, "llms.txt", good_cmd)
            # 对偶腿（必须绿）：三面等价 ⇒ 零违例。只测拒绝侧的判据会让新能力永久 403 而全绿。
            bad0, _ = diff_faces(scripts, subs)
            if bad0:
                print(f"[selftest FAIL] 等价面被判分叉（判据缺陷，不是语料缺陷）：{bad0[:3]}")
                return 1
            print("[selftest ok] 对偶腿：三面等价 ⇒ 零违例")

            # 反例腿 1（假承诺）：代码面里塞一个自述里没有的子命令。
            put(td, "README.en.md", good_cmd + "```bash\nfenjue not-a-real-subcommand\n```\n")
            bad1, _ = diff_faces(scripts, subs)
            if not any("假承诺" in b and "not-a-real-subcommand" in b for b in bad1):
                print(f"[selftest FAIL] 假承诺子命令没被咬住：{bad1[:3]}")
                return 1
            print("[selftest ok] 反例腿1：`fenjue not-a-real-subcommand` 判红并点名")
            put(td, "README.en.md", good_cmd)

            # 反例腿 2（入口点缺声明）：从 llms 面抹掉一条入口点。
            # 取字典序最后一条：'fenjue' 是其余三条的前缀，拿它做替换会连坐三面，
            # 那条腿就退化成"什么都没测到但消息里含关键字"。
            victim = sorted(scripts)[-1]
            put(td, "llms.txt", good_cmd.replace(victim, "REMOVED"))
            bad2, _ = diff_faces(scripts, subs)
            if not any(victim in b for b in bad2):
                print(f"[selftest FAIL] 入口点缺声明没被咬住：{bad2[:3]}")
                return 1
            print(f"[selftest ok] 反例腿2：llms.txt 抹掉 {victim} ⇒ 判红点名")
            put(td, "llms.txt", good_cmd)

            # 反例腿 3（双语单面声明）：只给中文面留一个子命令。
            extra = sorted(subs)[-1]
            lean = good_cmd.replace(f"\nfenjue {extra}\n", "\n")
            put(td, "README.en.md", lean)
            bad3, _ = diff_faces(scripts, subs)
            if not any("双语子命令面分叉" in b and extra in b for b in bad3):
                print(f"[selftest FAIL] 单面声明没判成分叉：{bad3[:3]}")
                return 1
            print(f"[selftest ok] 反例腿3：{extra} 只在中文面 ⇒ 判分叉")
            put(td, "README.en.md", good_cmd)

            # 回归腿（真面咬出来的那条假红）：`fenjue` 在行尾、下一行以 python 开头，
            # 第一版用 \s+ 把两行拼成 `fenjue python`  ⇒ 判了个不存在的假承诺。
            prose = good_cmd + "\n本项目命令行入口叫 fenjue\npython 只作为兜底写法出现在源码树形态里\n"
            put(td, "README.md", prose)
            put(td, "README.en.md", prose)
            bad4, _ = diff_faces(scripts, subs)
            if any("python" in b and "假承诺" in b for b in bad4):
                print(f"[selftest FAIL] 跨行又拼出了假子命令（\\s+ 回归）：{bad4[:2]}")
                return 1
            print("[selftest ok] 回归腿：散文里的行尾 fenjue + 次行 python 不构成主张")

            # 反例腿 5（本轮真面咬到的那条）：英文面教 `python -m pytest -q`。
            # 两个方向都要红：叠 -q 本身（addopts 已带 -q ⇒ 汇总行消失）、以及两面不等。
            q_face = good_cmd.replace("python -m pytest\n", "python -m pytest -q\n")
            put(td, "README.en.md", q_face)
            bad5, _ = diff_faces(scripts, subs)
            if not any("叠了 -q" in b for b in bad5):
                print(f"[selftest FAIL] `-q` 叠加没判红：{bad5[:2]}")
                return 1
            if not any("双语测试命令面分叉" in b for b in bad5):
                print(f"[selftest FAIL] 两面测试命令不等没判红：{bad5[:2]}")
                return 1
            print("[selftest ok] 反例腿5：英文面教 `pytest -q` ⇒ 叠 -q 与分叉两条各点一行")

            # 反例腿 6（等式不能救错值）：两面都教 `-q` ⇒ 分叉腿静默，叠 -q 腿必须还红。
            # 没有这条，"两面一起写错"就成了放行条件，那等于把判据降级成一致性检查。
            put(td, "README.md", q_face)
            bad6, _ = diff_faces(scripts, subs)
            if not any("叠了 -q" in b for b in bad6) or any("分叉" in b for b in bad6):
                print(f"[selftest FAIL] 两面同错时的读数不对（应只判叠 -q、不判分叉）：{bad6[:2]}")
                return 1
            print("[selftest ok] 反例腿6：两面同教 `-q` ⇒ 仍判叠 -q（相等不是放行条件）")
            put(td, "README.en.md", good_cmd)
            put(td, "README.md", good_cmd)
        finally:
            globals()["ROOT"] = saved_root
            FACES[:] = saved_faces

        # 盲区腿 A：某面的代码面里没有测试命令 ⇒ PremiseError（"没东西可比"不得读成"一致"）。
        try:
            globals()["ROOT"] = td
            FACES[:] = ["README.md", "README.en.md", "llms.txt"]
            put(td, "README.en.md", "```bash\nfenjue doctor\n```\n")
            try:
                diff_faces(scripts, subs)
            except PremiseError:
                print("[selftest ok] 盲区腿A：某面无测试命令 ⇒ UNVERIFIED，不判一致")
            else:
                print("[selftest FAIL] 无测命令的面被读成已核过")
                return 1
        finally:
            FACES[:] = ["README.md", "README.en.md", "llms.txt"]
        put(td, "README.md", good_cmd)
        put(td, "README.en.md", good_cmd)
        put(td, "llms.txt", good_cmd)

        # 盲区腿 B（方向相反的一半）：面缺失 ⇒ PremiseError，不得读成 PASS。
        saved_root2 = ROOT
        try:
            globals()["ROOT"] = td
            FACES[:] = ["README.md", "README.en.md", "nope.txt"]
            try:
                diff_faces(scripts, subs)
            except PremiseError:
                print("[selftest ok] 面缺失记 UNVERIFIED（抛 PremiseError，不静默通过）")
            else:
                print("[selftest FAIL] 面缺失被读成已核过")
                return 1
        finally:
            globals()["ROOT"] = saved_root2
            FACES[:] = ["README.md", "README.en.md", "llms.txt"]

    print("[GATE:cmd-face-parity-selftest-pass] 9 项（1 对偶 + 6 注入/回归 + 2 盲区）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
