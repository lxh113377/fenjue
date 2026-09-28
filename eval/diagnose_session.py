#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diagnose_session.py — 焚诀会话自诊（任务⑥：抄 diagnosing-superpowers）。

只诊行为（路由只诊映射，本工具诊会话内行为）：
  transcript = memory/2026-*.md + .workbuddy/memory/2026-*.md 的
  `<!-- footer:begin session=<id> --> … <!-- footer:end -->` 区
  + 同文件上下文行 + memory/sessions/savepoint-gate.jsonl 门禁记录。

硬规则（抄 diagnosing-superpowers）：
  - 每条 finding 必带 `path:line` 引用；无引用无结论。
  - 只读：不修改任何会话文件（bundle 校验 mtime）。
  - 数字全部来自 transcript 或当场命令输出，不凭记忆编。

用法：
    python eval/diagnose_session.py <session-id> [--json] [--bundle out.zip]
    exit 0 = 有定位（finding 可为空）/ 1 = 内部异常 / 2 = 未定位到会话（列候选）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from datetime import datetime

BEGIN_RE = re.compile(r"footer:begin\s+session=([^\s>]+)")
END_RE = re.compile(r"footer:end")
CAND_RE = re.compile(r"footer:begin\s+session=([^\s>]+)")
SKILL_RE = re.compile(r"\[skill清单\][^\n]*")
FAIL_RES = [re.compile(r"FAIL|❌|报错|失败|未通过"),
            re.compile(r"(\d+)/(\d+)\s*(PASS|pass)"),
            re.compile(r"BLOCK|拒绝|拦截")]
# 成功行豁免：含 "0 FAIL" 且含 PASS 的汇总行（如 "20 PASS / 0 FAIL"）不是 stumble
PASS_SUMMARY_RE = re.compile(r"\b0\s*FAIL\b")
CMD_RE = re.compile(r"(?:python|pytest|git|powershell|pwsh|node|npm)\s+[^\n]{4,120}")


def _log_files(root):
    out = []
    for sub in ("memory", os.path.join(".workbuddy", "memory")):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if re.match(r"^\d{4}-\d{2}-\d{2}(\.part\d+)?\.md$", fn):
                out.append(os.path.join(d, fn))
    return out


def list_candidates(root):
    found = []
    for fp in _log_files(root):
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for m in CAND_RE.finditer(f.read()):
                    if m.group(1) not in found:
                        found.append(m.group(1))
        except OSError:
            continue
    return found


def locate(root, sid):
    """返回 [{path, line, end_line, text}]（path 为相对 root）。"""
    secs = []
    for fp in _log_files(root):
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        rel = os.path.relpath(fp, root).replace("\\", "/")
        i = 0
        while i < len(lines):
            m = BEGIN_RE.search(lines[i])
            if m and m.group(1) == sid:
                j = i
                while j < len(lines) and not END_RE.search(lines[j]):
                    j += 1
                secs.append({"session": sid, "path": rel, "line": i + 1, "end_line": j + 1,
                             "text": "\n".join(lines[i:j + 1])})
                i = j + 1
            else:
                i += 1
    return secs


def _ctx_lines(root, sec, window=6):
    """footer 区前后文（行为证据：区外相邻行）。"""
    fp = os.path.join(root, sec["path"].replace("/", os.sep))
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    s = max(0, sec["line"] - 1 - window)
    e = min(len(lines), sec["end_line"] + window)
    for no in range(s + 1, e + 1):
        if no < sec["line"] or no > sec["end_line"]:
            out.append((no, lines[no - 1]))
    return out


def diagnose(root, sid):
    """返回 {session, sections, findings:[{dim, cite, what}]}。"""
    secs = locate(root, sid)
    findings = []
    for sec in secs:
        cite_sec = "%s:%d" % (sec["path"], sec["line"])
        for m in SKILL_RE.finditer(sec["text"]):
            ln = sec["text"][:m.start()].count("\n") + sec["line"]
            findings.append({"dim": "skills", "cite": "%s:%d" % (sec["path"], ln),
                             "what": m.group(0).strip()[:160]})
        for ln_no, ln in _ctx_lines(root, sec):
            if PASS_SUMMARY_RE.search(ln) and "PASS" in ln:
                continue  # 成功汇总行（如 20 PASS / 0 FAIL）不是 stumble
            for rx in FAIL_RES:
                m = rx.search(ln)
                if m:
                    findings.append({"dim": "stumbles",
                                     "cite": "%s:%d" % (sec["path"], ln_no),
                                     "what": ln.strip()[:160]})
                    break
        cmds = {}
        for lineno, ln in enumerate(sec["text"].splitlines(), sec["line"]):
            m = CMD_RE.search(ln)
            if m:
                key = m.group(0).strip()[:100]
                cmds.setdefault(key, []).append("%s:%d" % (sec["path"], lineno))
        for cmd, cites in sorted(cmds.items()):
            if len(cites) >= 2:
                findings.append({"dim": "repeated-work", "cite": cites[0],
                                 "what": "重复命令 x%d：%s" % (len(cites), cmd)})
    # 门禁记录关联（同源行为证据）
    gate = os.path.join(root, "memory", "sessions", "savepoint-gate.jsonl")
    if os.path.isfile(gate):
        try:
            with open(gate, encoding="utf-8", errors="replace") as f:
                for no, ln in enumerate(f, 1):
                    if sid in ln:
                        findings.append({"dim": "gates",
                                         "cite": "memory/sessions/savepoint-gate.jsonl:%d" % no,
                                         "what": ln.strip()[:160]})
        except OSError:
            pass
    return {"session": sid, "sections": len(secs), "findings": findings}


def render_md(root, sid, rep):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = ["# 会话自诊 — %s" % sid, "",
           "> 工具：eval/diagnose_session.py | %s | sections=%d | findings=%d" % (
               ts, rep["sections"], len(rep["findings"])),
           "> 硬规则：每条 finding 必带 path:line；数字来自 transcript 当场提取。", ""]
    if not rep["sections"]:
        out += ["## 未定位", "", "候选 sessions：%s" % (", ".join(list_candidates(root)[:20]) or "无")]
        return "\n".join(out) + "\n"
    out += ["## Findings", ""]
    for f in rep["findings"]:
        out.append("- [%s] `%s` %s" % (f["dim"], f["cite"], f["what"]))
    if not rep["findings"]:
        out.append("- （本区无 stumbles/skills/repeated-work/gates 命中）")
    return "\n".join(out) + "\n"


def bundle(root, sid, outpath):
    """打包：报告 + 引用原文节选。返回 0/1/2（2=未定位）。"""
    rep = diagnose(root, sid)
    if not rep["sections"]:
        return 2
    md = render_md(root, sid, rep)
    try:
        with zipfile.ZipFile(outpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("diagnose_%s.md" % sid, md)
            ev = []
            for sec in locate(root, sid):
                ev.append("### %s:%d-%d\n%s" % (
                    sec["path"], sec["line"], sec["end_line"], sec["text"]))
            z.writestr("evidence.txt", "\n\n".join(ev))
    except OSError:
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="焚诀会话自诊（行级证据 + bundle）")
    ap.add_argument("session", help="footer session id")
    ap.add_argument("--project", default=None, help="项目根（缺省=焚诀仓）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--bundle", default=None, help="bundle 输出 zip 路径")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.project) if args.project else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    rep = diagnose(root, args.session)
    if not rep["sections"]:
        print("未定位到会话 %s；候选：%s" % (
            args.session, ", ".join(list_candidates(root)[:20]) or "无"))
        return 2
    if args.bundle:
        rc = bundle(root, args.session, args.bundle)
        if rc != 0:
            print("bundle 失败 rc=%d" % rc)
            return 1
        print("bundle 已落盘：%s" % args.bundle)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(render_md(root, args.session, rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
