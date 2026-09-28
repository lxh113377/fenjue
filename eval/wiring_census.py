#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wiring_census.py —— 「判据接线率」普查与棘轮（对标轮十四 D-74/D-77）。

一句话动机：本仓的"工具数"一直在涨，"被链跑到的工具数"从来没人统计 ⇒ 前几轮我两次把
"我 grep 不到" 说成 "它没接线"（install_hooks 一例）与"我 grep 少了" 说成数量（分卷件一例）。
本工具把分母/分子都换成结构枚举（见 eval/faces.py 的模块说明），并要求**接线率只升不降**。

分母 = `eval/`+`scripts/` 下定义了 `main()` 的可执行判据（不含 test_*）；
分子 = 该判据满足下列任一：
  · 其 slug 出现在 `run_gate.py --expect` 名单或某个 `run_gate.py <slug> "python <file>"` 步里；
  · 其某个公开 `def check_*`/`def hook_health` 等函数被本地链以**调用式**引用（不看文件名字面）。
**除自身文件外**（D-123 修正）：链的闭包把 `eval/*.py` 全读进来，于是判据自己 docstring 里那行
`python eval/foo.py` 会被算成"CI 在跑它"⇒ 接线率虚高。2026-09-25 实测：虚高 23/73，
接线率 0.7526 → **0.5155（分母 97 / 已接线 50；复算 `python eval/wiring_census.py --json`
与 `python -c "import sys;sys.path.insert(0,'eval');import wiring_census as w;c=w.census();print(c['rate'],len(c['wired']),c['denominator'])"`）**。
基线因此**下修**，与"为他人存量重标基线"不同：这是分子口径的缺陷修正，
修正前后各跑一遍独立实现（一次性探针脚本）两数一致 = 50。
未接线的只**点名并计数**，不判红（历史债）；判红条件是**接线率下降**或分母塌成 0（R247）。
退出码 0 合规 / 1 接线率下降或分母上升但接线数不增 / 2 判据面失效。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import faces  # noqa: E402

BASELINE = os.path.join(faces.ROOT, "eval", "wiring_baseline.json")
CHAIN_TEXT = None


def _chain_parts():
    """[(绝对路径, 文本)] —— 链的闭包。刻意保留路径，因为判据**自己的源码不算接线**（D-123）。"""
    chain = [faces.CI_YML, faces.PRE_COMMIT, faces.VERIFY,
             os.path.join(faces.ROOT, "eval", "hooks", "pre-commit"),
             os.path.join(faces.ROOT, "eval", "hooks", "post-commit"),
             os.path.join(faces.ROOT, "scripts", "run_gate.py")]
    # 链的**闭包**：verify 的分层实现与隔离桩都在 eval/ 子目录里，只读顶层文件会漏判
    # （实测 build_memory_index 被 governance_layer `import build_memory_index as bmi` 调用，
    #   只看 eval/verify_truth_consistency.py 时会把它错算成"未接线"）
    for d in (os.path.join(faces.ROOT, "eval"),
              os.path.join(faces.ROOT, "eval", "verify_checks"),
              os.path.join(faces.ROOT, "eval", "stubs")):
        if os.path.isdir(d):
            chain += [os.path.join(d, fn) for fn in sorted(os.listdir(d)) if fn.endswith(".py")]
    out = []
    for p in chain:
        if os.path.isfile(p):
            out.append((os.path.abspath(p),
                        open(p, encoding="utf-8", errors="replace").read()))
    return out


def _chain_text() -> str:
    return "\n".join(t for _, t in _chain_parts())


STEP_RE = re.compile(r"python\s+(?:eval|scripts)/([\w./-]+\.py)")


def _steps_in(text):
    return set(STEP_RE.findall(text))


def _hits_in(rel, text, steps, owners, ambiguous):
    """**某一个链文件**是否跑到该判据。调用方负责把判据自己的文件排除在外 ——
    docstring 里写一行 `python eval/foo.py` 就把自己算成"已接线"是本普查的原始缺陷（D-123）。
    """
    stem = os.path.basename(rel)[:-3]
    tail = rel.split("/", 1)[1] if "/" in rel else rel
    if tail in steps:
        return True
    if stem not in text:          # 子串预筛：绝大多数文件与它无关，别让正则空转
        return False
    if _import_hit(stem, text) or _member_hit(stem, text):
        return True
    return any(f not in ambiguous and rel in v and f in text and _called(text, f)
               for f, v in owners.items())


def _called(text: str, ident: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(ident) + r"\s*\(", text) is not None


def _import_hit(stem: str, text: str) -> bool:
    """`import stem` / `from stem import …`，**词边界收尾**。

    边界是承重的：少了它，`import eval_tools_x` 会把 `eval_tools` 也算成已接线（假绿），
    而它自身被写成裸退格符时又永不成立（假红）。两种错法本轮各发生过一次，见 selftest。
    """
    return re.search(r"(?:import|from)\s+" + re.escape(stem) + r"\b", text) is not None


def _member_hit(stem: str, text: str) -> bool:
    """`stem.fn(` 形态的模块成员调用（前面不得是标识符字符，防 `xstem.fn(` 误命中）。"""
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(stem) + r"\.[a-z_]+\(", text) is not None


def _judge_fns(tools) -> dict:
    """判据函数名 → 定义它的工具清单（重名=按名调用无法归因到唯一模块）。"""
    owners = {}
    for rel in tools:
        try:
            body = open(os.path.join(faces.ROOT, rel.replace("/", os.sep)),
                        encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for f in re.findall(r"^def (check_[a-z0-9_]+|[a-z0-9_]*health[a-z0-9_]*)\(",
                            body, re.M):
            owners.setdefault(f, set()).add(rel)
    return {k: sorted(v) for k, v in owners.items()}


def _registry_declared() -> set:
    """`eval/stubs/registry.json` 里登记的桩路径（归一成 `eval/stubs/stub_x.py`）。

    为什么这也算接线：registry 是**机器消费**的接线声明 —— `gate_stub_runner.run_stub()`
    逐个 subprocess 跑这些文件，门禁由此被真跑。而 `_hits_in` 只认 Python 的 import /
    成员调用形态，JSON 声明永远命不中 ⇒ 21 个既有桩长期被算成"未接线"（分母虚高、
    分子虚低）。后果不只是数字难看：棘轮是"分母涨了分子也得涨"，于是**补一个正确接线的
    桩反而判红**，等于惩罚做对事的人。
    """
    path = os.path.join(faces.ROOT, "eval", "stubs", "registry.json")
    try:
        with open(path, encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, ValueError):
        return set()
    out = set()
    for s in reg.get("stubs", []):
        rel = str(s.get("file", "")).replace("\\", "/").lstrip("./")
        if rel:
            out.add(rel if rel.startswith("eval/") else "eval/" + rel)
    return out


def census(parts=None) -> dict:
    parts = _chain_parts() if parts is None else parts
    expect = set(faces.ci_expect_slugs())
    declared = _registry_declared()
    tools = faces.eval_tools()
    owners = _judge_fns(tools)
    ambiguous = {f for f, v in owners.items() if len(v) > 1}
    scanned = [(p, t, _steps_in(t)) for p, t in parts]
    wired, unwired = [], []
    for rel in tools:
        stem = os.path.basename(rel)[:-3]
        own = os.path.abspath(os.path.join(faces.ROOT, rel.replace("/", os.sep)))
        # CI 的 --expect 名单是结构事实（它本身就是"CI 会跑这条"的声明），不依赖文本；
        # 其余三种命中一律按"除自己以外的链文件"算 —— 自述用法行不是接线。
        hit = (stem.replace("_", "-") in expect or rel in declared or any(
            p != own and _hits_in(rel, t, st, owners, ambiguous) for p, t, st in scanned))
        (wired if hit else unwired).append(rel)
    return {"denominator": len(tools), "wired": sorted(wired), "unwired": sorted(unwired),
            "rate": round(len(wired) / len(tools), 4) if tools else 0.0,
            "ambiguous_fn_names": sorted(ambiguous)}


def judge(now: dict, base: dict | None) -> tuple:
    if not now["denominator"]:
        return "FAIL-FAST", "分母为空：判据面塌了（R247），不是零接线的通过"
    if base is None:
        return "FAIL-FAST", "无接线基线：先跑 --update-baseline 登记现状"
    if now["rate"] + 1e-9 < base.get("rate", 0.0):
        return "FAIL", f"接线率下降 {base['rate']:.4f} -> {now['rate']:.4f}"
    if now["denominator"] > base.get("denominator", 0) and len(now["wired"]) <= len(base.get("wired", [])):
        return "FAIL", (f"新增 {now['denominator'] - base['denominator']} 个判据但一个都没接线"
                        f"（分母涨、分子不涨 = 只造轮子不接线）")
    return "PASS", f"接线率 {now['rate']:.4f} >= 基线 {base.get('rate', 0):.4f}，分母 {now['denominator']}"


def selftest() -> int:
    """接线判据自身的判别力自证（对标轮十六 D-89）。

    真凶形状：`r"\\b"` 被写成单个退格符 0x08 ⇒ import 半边永不成立 ⇒ 4 个真已接线的
    判据被报成未接线，而棘轮把它当成"接线率在下降"。这条自证让**下次再被蛀**当场红，
    而不是等到棘轮给出一个方向都对不上的数。
    """
    ok = True
    src = open(os.path.abspath(__file__), "rb").read()
    bad = re.findall(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", src)
    if bad:
        ok = False
        print("[selftest] FAIL: 本判据源码含 %d 个控制字符（转义被解释过）" % len(bad))
    cases = [
        ("memory_recall_eval", "import memory_recall_eval as mre", True, "真 import 必须命中"),
        ("skill_security_scan", "from skill_security_scan import run_scan", True,
         "from 形态必须命中"),
        ("eval_tools", "import eval_tools_extra as et", False, "前缀撞名不得算接线（假绿）"),
        ("eval_tools", "# eval_tools 只是注释里提到", False, "非 import 语境不得算接线"),
        ("attribution_lock", "check_attribution_lock_health()", False,
         "同名长函数不得算模块接线"),
    ]
    for stem, text, want, why in cases:
        got = _import_hit(stem, text)
        if got != want:
            ok = False
            print("[selftest] FAIL: %s → %s（期望 %s）%r" % (why, got, want, text))
    if _member_hit("x", "xx.fn()"):
        ok = False
        print("[selftest] FAIL: `xx.fn(` 被算成 x 接线（前一字符守卫失效=撞名假绿）")
    if _member_hit("x", "x.check_it(t)"):
        pass
    else:
        ok = False
        print("[selftest] FAIL: 正常成员调用没命中")
    # D-123：`_hits_in` 只回答"这份文本里有没有跑到它"，"这份文本是不是它自己"由 census 判定 ——
    # 两层分开，才能把"自述用法行"与"真被链引用"分开算（合成夹具，不依赖仓库现状）
    owners_x = {"check_zzz": ["eval/zzz.py"]}
    if not _hits_in("eval/zzz.py", "python eval/zzz.py --json", _steps_in("python eval/zzz.py"),
                    owners_x, set()):
        ok = False
        print("[selftest] FAIL: 他文件的 `python eval/zzz.py` 步未被算成接线")
    if _hits_in("eval/zzz.py", "nothing at all here", set(), owners_x, {"check_zzz"}):
        ok = False
        print("[selftest] FAIL: 无关文本被判成接线（预筛或调用判定失效）")
    print("[selftest] %s %d 例（源码无控制符 + import/from/前缀撞名/注释/同名长函数"
          " + 成员调用两侧 + 接线命中两侧）" % ("PASS" if ok else "FAIL", len(cases) + 5))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="判据接线率棘轮（D-74）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="判别力自证（不读链、不比对基线）")
    ns = ap.parse_args(argv)
    if ns.selftest:
        return selftest()
    try:
        now = census()
    except (RuntimeError, OSError) as e:
        print(f"[wiring] FAIL-FAST: {e}")
        return 2
    if ns.update_baseline:
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(now, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"[wiring] 基线已写：分母 {now['denominator']} / 已接线 {len(now['wired'])} / "
              f"率 {now['rate']}")
        return 0
    base = json.load(open(BASELINE, encoding="utf-8")) if os.path.isfile(BASELINE) else None
    verdict, reason = judge(now, base)
    print(f"[wiring] {verdict}: {reason}")
    if ns.json:
        print(json.dumps(now, ensure_ascii=False))
    else:
        for rel in now["unwired"][:10]:
            print(f"  未接线: {rel}")
    return {"PASS": 0, "FAIL": 1}.get(verdict, 2)


if __name__ == "__main__":
    sys.exit(main())
