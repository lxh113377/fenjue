#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""control_char_lock.py —— 跟踪面里不允许存在「被解释过的转义」残留（对标轮十六 D-89）。

一手病灶（本轮实测）：`eval/wiring_census.py:64` 的 import 半边写的是 `r"\\b"`，落盘成
**单个退格符 0x08** ⇒ 正则变成「模块名后必须跟一个退格」，永远不成立。接线率棘轮因此
连续把 4 个真已接线的判据报成未接线（0.7065 → 0.7021 的"下降"就是它造出来的假红），
而链上 16 道闸 + 33 项真相校验**没有任何一道**看得见这个字节。

机制：文本模式写入时 `\\b` `\\a` `\\v` `\\f` `\\e` 这类转义被解释成真控制符
（同族第 6/第 7 形态，见 GM `feedback-backslash-control-chars`）。它不改变文件可读性，
只静默改掉语义——肉眼、diff、lint 全都不报。

分母口径：`faces.tracked_files()` = `git ls-files -z`（NUL 分隔，中文路径不漏），
只判文本扩展名。反向断言：面 < MIN_FACE 或不在 git 仓 ⇒ exit 2（R247：面塌了不是"零违规"）。
豁免表为空是刻意的——控制符没有"这里就该有一个"的合法场景；真要放就得先改本锁并给理由。

退出码：0 干净 / 1 有控制符 / 2 判据面失效。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import faces  # noqa: E402

BAD_RE = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
TEXT_EXT = (".py", ".md", ".json", ".jsonl", ".yml", ".yaml", ".sh", ".txt",
            ".toml", ".ini", ".cfg", ".html", ".css", ".js", ".ts", ".ps1",
            ".bat", ".tsx", ".svg", ".sql")
# 控制符 → 写入前那个字面量的样子（指得出"原意"，失败才可归因，D-81 同法）
MEANING = {0x00: "NUL（多为截断/编码错）", 0x07: "\\a", 0x08: "\\b", 0x0b: "\\v",
           0x0c: "\\f", 0x0d: "\\r", 0x1b: "\\e"}
MIN_FACE = 300


def text_face(paths=None) -> list:
    """跟踪面里的文本件（分母；由结构枚举得出，不由 grep 命中数得出）。"""
    src = faces.tracked_files() if paths is None else paths
    # 只剥 "./" 前缀：lstrip("./") 会连 `.github/…` 的首点开头条目一起吞掉（漏判面）
    norm = [p.replace(os.sep, "/")[2:] if p[:2] == "./" else p.replace(os.sep, "/")
            for p in src]
    return [p for p in norm if p.lower().endswith(TEXT_EXT)]


def scan_bytes(data: bytes) -> list:
    """一字节一记录：行号 + 码位 + 该行上下文（截断，避免把二进制糊上屏）。"""
    out = []
    for m in BAD_RE.finditer(data):
        code = m.group()[0]
        line = data.count(b"\n", 0, m.start()) + 1
        out.append({"line": line, "code": code,
                    "hex": "0x%02x" % code,
                    "means": MEANING.get(code, "无对应转义"),
                    "ctx": data[max(0, m.start() - 60):m.start() + 20]
                    .replace(b"\n", b" ").decode("utf-8", "replace")})
    return out


def scan_paths(paths, root=None) -> list:
    root = root or faces.ROOT
    findings = []
    for rel in paths:
        try:
            with open(os.path.join(root, rel.replace("/", os.sep)), "rb") as f:
                hits = scan_bytes(f.read())
        except OSError:
            continue
        for h in hits:
            h["path"] = rel
            findings.append(h)
    return findings


def unresolvable(paths, root=None) -> list:
    """枚举器给出解析不到的路径 = 分母在骗人（漏判通道，须显式可见而非静默 continue）。"""
    root = root or faces.ROOT
    return [p for p in paths
            if not os.path.isfile(os.path.join(root, p.replace("/", os.sep)))]


def judge(face_n: int, findings: list, face=None, from_git=True) -> tuple:
    """from_git=False 用于显式子集（`--paths`）：面下限不适用，但空面仍判失效（R247）。"""
    if face is None:
        face = face_n
    if not from_git:
        if face == 0:
            return "FAIL-FAST", "显式指定的面为空：没有对象可判，不是「零控制符」"
        if findings:
            return "FAIL", "子集面 %d 个中发现 %d 处控制字符" % (face, len(findings))
        return "PASS", "子集面 %d 个，0 处控制字符" % face
    if face < MIN_FACE:
        return "FAIL-FAST", ("文本跟踪面只有 %d 个（下限 %d）：枚举器或 git 出问题了，"
                             "这不是\"零控制符\"" % (face, MIN_FACE))
    if findings:
        kinds = sorted({f["means"] for f in findings})
        return "FAIL", ("%d 处控制字符散在 %d 个文件（形态：%s）" % (
            len(findings), len({f["path"] for f in findings}), ", ".join(kinds)))
    return "PASS", "跟踪文本面 %d 个，0 处控制字符" % face


def selftest() -> int:
    """判别力自证：没有反例的判据等于没有判据（R238 两层含对照）。"""
    ok = True
    dirty = b'fn = re.search(r"' + bytes([8]) + b'", text)'
    hits = scan_bytes(dirty)
    if len(hits) != 1 or hits[0]["code"] != 8 or hits[0]["means"] != "\\b":
        ok = False
        print("[selftest] FAIL: 退格符没被抓到/没报出原意 \\b：%s" % hits)
    clean = ('# -*- coding: utf-8 -*-\nimport os\npath = "C:/a/b"\n'
             'tab\there\n').encode("utf-8")
    if scan_bytes(clean):
        ok = False
        print("[selftest] FAIL: 正常 UTF-8 + 制表符被判成控制字符（误报会淹掉真信号）")
    st, why = judge(0, [])
    if st != "FAIL-FAST":
        ok = False
        print("[selftest] FAIL: 空面未被判成判据面失效（R247）， got=%s" % st)
    st2, _ = judge(1200, [{"path": "a.py", "line": 3, "code": 8,
                           "hex": "0x08", "means": "\\b", "ctx": b""}])
    if st2 != "FAIL":
        ok = False
        print("[selftest] FAIL: 注入反例后仍判 %s（判据不判别）" % st2)
    print("[selftest] %s 4 例（抓退格 / 不误报 / 空面失效 / 反例判红）"
          % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def evaluate(face: list, from_git=True) -> dict:
    """主/机读两条出口共用同一判定（禁两份实现漂移）。"""
    bad = unresolvable(face)
    findings = scan_paths(face)
    if bad:
        verdict, reason = "FAIL-FAST", ("枚举器给出 %d 个解析不到的路径 ⇒ 面在骗人"
                                        "（扫描只会静默跳过它们）：%s"
                                        % (len(bad), ", ".join(bad[:5])))
    else:
        verdict, reason = judge(len(face), findings, from_git=from_git)
    return {"verdict": verdict, "reason": reason, "face": len(face),
            "total": len(findings), "violations": findings[:50]}


def run_json(argv=None) -> dict:
    """供 `eval/gate_stub_runner.py` / 归因链消费的机器可读出口（D-63 同款契约）。"""
    try:
        face = text_face(faces.tracked_files())
    except (RuntimeError, OSError) as e:
        return {"verdict": "FAIL-FAST", "reason": str(e), "face": 0, "violations": []}
    return evaluate(face)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="跟踪面控制字符静态锁（D-89）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="跑判别力自证（不读盘）")
    ap.add_argument("--paths", nargs="*", default=None, help="限定面（默认=全跟踪文本面）")
    ns = ap.parse_args(argv)
    if ns.selftest:
        return selftest()
    try:
        face = text_face(faces.tracked_files() if ns.paths is None else ns.paths)
    except (RuntimeError, OSError) as e:
        print("[control-char] FAIL-FAST: %s" % e)
        return 2
    res = evaluate(face, from_git=ns.paths is None)
    verdict, reason = res["verdict"], res["reason"]
    findings = res["violations"]
    if ns.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print("[control-char] %s: %s" % (verdict, reason))
        for f in findings[:15]:
            print("  %s:%d %s（原意 %s）… %s" % (
                f["path"], f["line"], f["hex"], f["means"], f["ctx"][:70]))
        if res["total"] > 15:
            print("  …另 %d 处（--json 看全量）" % (res["total"] - 15))
    return {"PASS": 0, "FAIL": 1}.get(verdict, 2)


if __name__ == "__main__":
    sys.exit(main())
