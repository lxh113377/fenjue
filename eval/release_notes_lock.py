#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""release_notes_lock.py —— 发布面必须能引用、且引用不得是编的（对标轮十八 D-114）。

一手对照（本轮 gh api 取证）：
  - `obra/superpowers`（与本仓同形态的 skill 框架仓）有 releases + tag：
    `gh api repos/obra/superpowers/releases --jq ".[0] | {tag_name, published_at}"`
    → v6.4.1 / 2026-09-19；根目录另有 `RELEASE-NOTES.md` 与 `.version-bump.json`
    （`gh api repos/obra/superpowers/contents/ --jq "[.[].name]|map(select(test(\"RELEASE|VERSION\")))"`）
  - `anthropics/skills`（第一方 skill 仓）**0 个 release**
    （`gh api repos/anthrosics/skills/releases --jq "length"` 见 README 口径）⇒ 无锚点也不是不行
  - 本仓此前：`git tag | wc -l` = 1 个孤立 tag、`gh release list` = 0、无 CHANGELOG/RELEASE-NOTES；
    而 `<MEMORY_ROOT>/meta/VERSION_LOCK.md` 第 3 行自己写着
    「原分卷随 GM 清空丢失，重建期以 STATUS.md + truth_constants.json 为版本权威」
    —— **版本账本存放在可被一次清空干掉的磁盘态里，且真的发生过一次**。

所以本锁要的不是"学大厂打 tag"，而是两条能机检的性质：
  P1 可引用：发布面每个条目必须带 ≥7 位 commit sha，且该 sha 在 git 里真存在
     （编一个不存在的 sha = 造一个引用即崩的版本点；R240「被引用的路径须实测存在」的版本版）
  P2 单调：条目时间戳不倒退、sha 只增不减（发布面不许被"顺手清理"变小）
  P3 面塌即失效：notes 文件缺失 / 一个条目都没有 / 不在 git 仓 ⇒ FAIL-FAST，不是"零违规"
  P4 tag 对账（只在有 tag 时生效）：每个 tag 指向的 commit 必须被发布面引用
     —— 打不打 tag 留给归属方；但打了就必须可追溯到"哪一条变更"

用法：python eval/release_notes_lock.py [--json | --selftest]
退出码：0 合规 / 1 违规 / 2 判据面失效
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVAL_DIR)
NOTES = os.path.join(ROOT, "RELEASE-NOTES.md")
# 远端核验是"周维护"节律的活，不该进每次提交 ⇒ 结果落一个不入库的状态文件，
# 默认链只读它的年龄（离线），超期就在 reason 里点名 —— 报告不阻断（advisory）。
STATE = os.path.join(EVAL_DIR, "release_face_state.json")
STALE_H = 168.0
ENTRY_RE = re.compile(r"^##\s+(R\d+[^\n]*)$", re.M)
# 首版用 \b 词边界，被自己的文档打了假阳性：tag 名 `R196-tdd-verify-diagnose-20260923`
# 里的 8 位日期全部落在 [0-9a-f] 集合内 ⇒ 被当成"一个不存在的 sha"。
# 现要求两侧既不是连字符也不是词字符：日期紧跟 `-` 即排除，独立 sha 仍能命中。
SHA_RE = re.compile(r"(?<![-\w])[0-9a-f]{7,40}(?![-\w])")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _git(*args, timeout=30):
    try:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def tracked_text(path: str = NOTES) -> str:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return open(path, encoding="utf-8").read()


def parse_entries(text: str) -> list:
    """`## R<编号> …` 一节 = 一个发布条目；返回 [{head, date, shas}]（按文件顺序=新在上）。"""
    heads = [(m.start(), m.group(1)) for m in ENTRY_RE.finditer(text)]
    out = []
    for i, (pos, head) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        body = text[pos:end]
        dm = DATE_RE.search(head) or DATE_RE.search(body)
        out.append({"head": head.strip(), "date": dm.group(1) if dm else None,
                    "shas": sorted(set(SHA_RE.findall(body)))})
    return out


def sha_exists(sha: str) -> bool:
    r = _git("cat-file", "-e", "%s^{commit}" % sha)
    return bool(r and r.returncode == 0)


def tag_targets() -> list:
    """已存在的轻量/附注 tag → 其指向的 commit sha（不强制打 tag，但打了就要能追溯）。"""
    r = _git("for-each-ref", "--format=%(refname:short) %(objectname)", "refs/tags")
    if not r or r.returncode != 0:
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2:
            peel = _git("rev-parse", "%s^{commit}" % parts[0])
            sha = (peel.stdout or "").strip() if peel and peel.returncode == 0 else parts[1]
            out.append({"tag": parts[0], "commit": sha})
    return out


def remote_tags(timeout=45):
    """远端 tag 清单（D-115：本仓唯一的 tag 曾只存在于这台机器上）。

    `git tag | wc -l` = 1 而 `git ls-remote --tags origin | wc -l` = 0 —— 版本点没推出去，
    换机/他人签出就看不见，和 2026-09-21 那次「GM 清空把版本分卷一起带走」是同一类风险。
    网络/权限取不到时返回 None ⇒ 该规则**跳过而不是判过**（fail-open 只在取不到数时，
    且 reason 里必须写明未验证）。
    """
    try:
        r = subprocess.run(["git", "-C", ROOT, "ls-remote", "--tags", "origin"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = set()
    for line in (r.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].startswith("refs/tags/"):
            out.add(parts[1][len("refs/tags/"):].rstrip("^{}"))
    return out


def _remote_note(remote, has_tags: bool, state_age_h=None,
                 remote_attempted: bool = False) -> str:
    """未联网时不许写"已验证"，也不许什么都不说 —— reason 里必须交代远端核验的时点。"""
    if remote is not None or not has_tags:
        return ""
    if remote_attempted:
        return "（本轮 --remote 联网未取得远端清单 ⇒ 离线或无凭证，远端可见性仍未验证）"
    if state_age_h is None:
        return "（tag 远端可见性从未核验过：跑一次 `python eval/release_notes_lock.py --remote`）"
    if state_age_h > STALE_H:
        return "（距上次 --remote 远端核验 %.0f 小时 > %d 小时 ⇒ 超期未核验）" % (state_age_h, STALE_H)
    return "（距上次 --remote 远端核验 %.0f 小时，本轮默认链不联网）" % state_age_h


def write_state(res: dict, path: str = STATE, now=None) -> dict:
    """把 --remote 的核验结果落盘（时间戳 + 判据），供下次离线运行报告"多久没核验了"。"""
    ts = now or datetime.datetime.now()
    payload = {"schema": "fenjue-release-face-state-v1",
               "ts": ts.strftime("%Y-%m-%dT%H:%M:%S"),
               "verdict": res.get("verdict"), "entries": res.get("entries"),
               "remote_tags": res.get("remote_tags"), "reason": res.get("reason")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return payload


def read_state(path: str = STATE, now=None):
    """返回带 age_h 的字典；文件缺失/损坏/无时间戳 ⇒ None（取不到数就不冒充"刚核验过"）。"""
    try:
        d = json.loads(open(path, encoding="utf-8").read())
        then = datetime.datetime.strptime(d["ts"], "%Y-%m-%dT%H:%M:%S")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    ref = now or datetime.datetime.now()
    d["age_h"] = (ref - then).total_seconds() / 3600.0
    return d


def judge(entries: list, tags=None, exists=None, notes_bytes: int = 0,
          remote=None, state_age_h=None, remote_attempted: bool = False) -> dict:
    # `exists=None` 而非 `exists=sha_exists`：默认参数在 def 时绑定，桩住模块属性会打不中判据
    exists = exists or sha_exists
    if notes_bytes == 0:
        return {"verdict": "FAIL-FAST", "reason": "发布面文件为空（R247：空不是零违规）",
                "violations": []}
    if not entries:
        return {"verdict": "FAIL-FAST",
                "reason": "发布面解析不出任何 `## R<编号>` 条目 ⇒ 判据面无对象", "violations": []}
    v = []
    for e in entries:
        fake = [s for s in e["shas"] if not exists(s)]
        if fake:
            v.append({"head": e["head"], "why": "引用了 git 里不存在的 sha", "shas": fake[:5]})
        if not e["shas"]:
            v.append({"head": e["head"], "why": "条目没有任何 commit sha ⇒ 不可引用", "shas": []})
        if not e["date"]:
            v.append({"head": e["head"], "why": "条目无日期 ⇒ 无法判单调", "shas": []})
    dates = [e["date"] for e in entries if e["date"]]
    if dates != sorted(dates, reverse=True):
        v.append({"head": "(顺序)", "why": "条目日期非「新在上」单调：%s" % dates[:6], "shas": []})
    cited = {s for e in entries for s in e["shas"]}
    unpushed = [] if remote is None else sorted({t["tag"] for t in (tags or [])
                                                 if t["tag"] not in remote})
    for name in unpushed:
        # D-115：本仓唯一的 tag `R196-...` 推远端前 `git ls-remote --tags origin` = 0，
        # 即"发布点只活在这台机器上"——换机/CI 干净签出看不见，与 2026-09-21 GM 清空
        # 丢版本分卷是同一类风险。远端取不到（无凭证/离线）时跳过并在 reason 里声明，
        # 不假装"已验证"。
        v.append({"head": "(tag %s)" % name,
                  "why": "tag 只在本地存在、远端不可见 ⇒ 换机即失联", "shas": []})
    for t in (tags or []):
        tc = t["commit"]
        # sha 是缩写友好的：发布面可以写 7 位短号，tag 给的是全号 ⇒ 必须按前缀双向比，
        # 比 `tc[:7] in cited` 这种"长度刚好相等才认"的写法会在 8 位短号上误判成未引用
        if not any(c == tc or c.startswith(tc[:7]) or tc.startswith(c[:7]) for c in cited):
            v.append({"head": "(tag %s)" % t["tag"],
                      "why": "tag 指向的 commit %s 未被发布面引用" % tc[:12],
                      "shas": []})
    return {"verdict": "FAIL" if v else "PASS",
            "reason": "%d 个条目 / %d 个可引用 sha / %d 个 tag%s" % (
                len(entries), len(cited), len(tags or []),
                _remote_note(remote, bool(tags), state_age_h, remote_attempted)),
            "remote_tags": None if remote is None else len(remote),
            "violations": v}


def probe(path: str = NOTES, use_remote: bool = False, state_path: str = STATE) -> dict:
    """默认**不打网络**（D-79 墙钟教训）：本锁跑在每次提交的第 18 闸里，
    而 `git ls-remote --tags` 实测一次 2.5~2.8s ⇒ 网络往返不进默认链。
    `--remote` 显式开启（周维护/人工核验用）并落状态文件；不开时 reason 里写明"未验证"
    以及**上次核验是多久前**（超 STALE_H 就点名超期），不写"已验证"。"""
    try:
        text = tracked_text(path)
    except FileNotFoundError:
        return {"verdict": "FAIL-FAST", "reason": "发布面文件不存在：%s" % path,
                "violations": [], "entries": 0}
    entries = parse_entries(text)
    remote = remote_tags() if use_remote else None
    age = None if use_remote else (read_state(state_path) or {}).get("age_h")
    res = judge(entries, tag_targets(), notes_bytes=len(text.encode("utf-8")),
                remote=remote, state_age_h=age, remote_attempted=use_remote)
    res["entries"] = len(entries)
    res["remote_checked"] = bool(use_remote)
    if use_remote:
        res["state_written"] = write_state(res, state_path)["ts"]
    return res


def selftest() -> int:
    """判别力自证：正反两向都要抓到；**例数由清单长度得出**（声明计数对不上清单就是 D-109 那个坑）。"""
    good = "## R18 发布面条目 2026-09-25\n- 变更见 abc1234 与 def4567\n"
    ents = parse_entries(good)
    tags = [{"tag": "R7-x", "commit": "e" * 40}]
    body = "## R7 锚 2026-09-23\n- " + "e" * 40 + "\n"
    cases = []

    def case(name, cond):
        cases.append((name, bool(cond)))

    case("条目/sha 解析", len(ents) == 1 and len(ents[0]["shas"]) == 2)
    case("合法条目判过（不误报）",
         judge(ents, [], exists=lambda s: True, notes_bytes=len(good))["verdict"] == "PASS")
    r2 = judge(ents, [], exists=lambda s: False, notes_bytes=len(good))
    case("假 sha 判红", r2["verdict"] == "FAIL" and "不存在" in r2["violations"][0]["why"])
    r3 = judge([{"head": "R9 无 sha 条目 2026-01-01", "date": "2026-01-01", "shas": []}],
               [], exists=lambda s: True, notes_bytes=100)
    case("无 sha 条目判红", r3["verdict"] == "FAIL" and "不可引用" in r3["violations"][0]["why"])
    case("空面 FAIL-FAST（R247：空不是零违规）",
         judge(ents, [], exists=lambda s: True, notes_bytes=0)["verdict"] == "FAIL-FAST")
    old_first = parse_entries("## R18 新 2026-09-25\n- abc1234\n\n## R17 旧 2026-09-20\n- def4567\n")
    backwards = parse_entries("## R17 旧 2026-09-20\n- def4567\n\n## R18 新 2026-09-25\n- abc1234\n")
    case("正常顺序判过",
         judge(old_first, [], exists=lambda s: True, notes_bytes=60)["verdict"] == "PASS")
    case("时间倒序判红（单调失效）",
         judge(backwards, [], exists=lambda s: True, notes_bytes=60)["verdict"] == "FAIL")
    hyphen = parse_entries("## R7 锚点 2026-09-23\n"
                           "- tag R196-tdd-verify-diagnose-20260923 未推送远端\n")
    case("连字符里的 8 位日期不当 sha", not hyphen[0]["shas"])
    plain = parse_entries("## R7 锚 2026-09-23\n- 见 09bb834 与 987d43f 两笔\n")
    case("独立 sha 不漏（边界收太紧会漏报）", len(plain[0]["shas"]) == 2)
    # tag 全号 vs 发布面短号：必须按前缀双向比 —— 首版用 `tc[:7] in cited` 的集合成员判定，
    # 遇到 8 位短号就误判「未引用」（写测试时被抓出来）
    case("tag 以全号被引用判过",
         judge(parse_entries(body), tags, exists=lambda s: True,
               notes_bytes=60)["verdict"] == "PASS")
    case("tag 以 8 位短号被引用判过",
         judge(parse_entries("## R7 锚 2026-09-23\n- 见 eeeeeeee 短号\n"), tags,
               exists=lambda s: True, notes_bytes=60)["verdict"] == "PASS")
    case("tag 未被引用判红",
         judge(parse_entries("## R7 锚 2026-09-23\n- 无关 abcdef1\n"), tags,
               exists=lambda s: True, notes_bytes=60)["verdict"] == "FAIL")
    case("本地有 tag 而远端 0 个 ⇒ 判红（D-115）",
         judge(parse_entries(body), tags, exists=lambda s: True, notes_bytes=60,
               remote=set())["verdict"] == "FAIL")
    case("tag 已推远端 ⇒ 判过（误报会逼人绕闸）",
         judge(parse_entries(body), tags, exists=lambda s: True, notes_bytes=60,
               remote={"R7-x"})["verdict"] == "PASS")
    off = judge(parse_entries(body), tags, exists=lambda s: True, notes_bytes=60, remote=None)
    case("远端不可达不判红（离线不得判红）", off["verdict"] == "PASS")
    case("从未核验 ⇒ reason 点名「从未」", "从未核验" in off["reason"])
    stale = judge(parse_entries(body), tags, exists=lambda s: True, notes_bytes=60,
                  remote=None, state_age_h=STALE_H + 24)
    case("状态超期 ⇒ reason 点名「超期未核验」", "超期未核验" in stale["reason"])
    fresh = judge(parse_entries(body), tags, exists=lambda s: True, notes_bytes=60,
                  remote=None, state_age_h=1.0)
    case("刚核验过 ⇒ reason 报时点且不判红",
         "1 小时" in fresh["reason"] and fresh["verdict"] == "PASS")
    tried = judge(parse_entries(body), tags, exists=lambda s: True, notes_bytes=60,
                  remote=None, remote_attempted=True)
    case("--remote 联网失败 ⇒ 写「联网未取得」而不是「已验证」", "联网未取得" in tried["reason"])
    tmp = os.path.join(tempfile.gettempdir(), "fenjue_release_state_selftest.json")
    try:
        write_state({"verdict": "PASS", "entries": 8, "remote_tags": 1, "reason": "x"},
                    tmp, now=datetime.datetime(2026, 9, 25, 12, 0, 0))
        st = read_state(tmp, now=datetime.datetime(2026, 9, 25, 18, 0, 0))
        case("状态文件 write/read 往返且 age_h 算得对",
             st is not None and abs(st["age_h"] - 6.0) < 1e-9)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("{损坏")
        case("状态文件损坏 ⇒ read_state 返 None（不冒充核验过）", read_state(tmp) is None)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    bad = [n for n, p in cases if not p]
    for n in bad:
        print("[selftest] FAIL: %s" % n)
    print("[selftest] %s %d 例（解析 / 假阳性 / 顺序单调 / tag 引用与远端三态 / 核验时点与状态文件）"
          % ("PASS" if not bad else "FAIL", len(cases)))
    return 0 if not bad else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="发布面可引用锁（D-114）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--remote", action="store_true",
                    help="额外查 tag 的远端可见性（会打一次 git ls-remote，默认不开）")
    ap.add_argument("--state", default=None,
                    help="远端核验状态文件路径（默认与判据同目录，可注入以做测试）")
    ns = ap.parse_args(argv)
    state_path = ns.state or STATE
    if ns.selftest:
        return selftest()
    res = probe(use_remote=ns.remote, state_path=state_path)
    if ns.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print("[release-notes] %s: %s" % (res["verdict"], res["reason"]))
        for x in res["violations"][:10]:
            print("  - %s：%s%s" % (x["head"][:48], x["why"],
                                    (" 例:%s" % ",".join(x["shas"][:3])) if x["shas"] else ""))
    return {"PASS": 0, "FAIL": 1}.get(res["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
