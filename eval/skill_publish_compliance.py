#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skill_publish_compliance.py — 技能对外发布合规校验（P2E-2，2026-09-24）

对标：agentskills.io 规范（description ≤1024 字符 + frontmatter 标准字段）。
定位：技能库进 CC/API/agentskills 生态分发前的合规门 + 主仓 verify C28 常态门禁。

判据（三项硬 + 一项软）：
  A1 frontmatter 块存在（--- 包裹）且 name/description 必填非空；
  A2 description ≤1024 字符（agentskills 硬上限）；
  A3 顶层字段 ⊆ 冻结白名单（实测 20 键 ∪ 标准字段；新增字段须人决策后登记，
     防字段生态漂移——白名单是「字段名单」不是「违规豁免」，与内容安全豁免表无关）；
  W1 name 与目录名不一致 → 告警不阻断（存量 5 例：notion-* 目录简化 + __skillhub 后缀形态）。
扫描面：<SKILLS_ROOT>/*/SKILL.md 主文件头 4KB。

用法:
  python skill_publish_compliance.py              # 人读报告
  python skill_publish_compliance.py --json       # 机器读
  python skill_publish_compliance.py --selftest   # 判据隔离桩

退出码: 0 = 合规 / 1 = 有违规 / 2 = 用法错误
"""
from __future__ import annotations

import os
import re
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EVAL_DIR)
import config  # noqa: E402  运行时读（conftest monkeypatch 惯例，见 skill_security_scan 同款注）

DESC_MAX = 1024

# A3 白名单 = agentskills 标准字段 ∪ 2026-09-24 实测 166 技能面上存在的全部扩展键（冻结）。
# 新技能想用新顶层字段：先在此登记（人决策），否则 C28 FAIL —— 防的是生态漂移，不是拦合法字段。
ALLOWED_KEYS = {
    # agentskills / Qoder 标准
    "name", "description", "version", "license", "allowed-tools", "metadata",
    # 实测存量扩展键（2026-09-24 全量 166 技能顶层键枚举冻结，实测键集与白名单双向差集为空）
    "agent_created", "install_source", "connector_id", "enabled_at",
    "description_zh", "description_en", "triggers", "trigger", "homepage",
    "last_updated", "user-invocable", "tags", "source", "created", "domain",
    "risk", "updated", "owner", "maintainer", "disable-model-invocation",
    "permissions", "date", "dependency", "deprecated", "type", "user_created",
    "compatibility", "display_name", "display_name_en", "author", "platforms",
}

_FM_RE = re.compile(r"^\ufeff?---\r?\n(.*?)\r?\n---", re.S)
_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_.-]*):(.*)$", re.M)


def parse_frontmatter(text):
    """行式解析（不依赖 yaml）。返回 (fm_text|None, {key: value})——只认顶层键（无缩进行）。"""
    m = _FM_RE.match(text)
    if not m:
        return None, {}
    fm = m.group(1)
    top = {}
    for line in fm.splitlines():
        km = re.match(r"^([A-Za-z][A-Za-z0-9_.-]*):\s*(.*)$", line)
        if km:
            top[km.group(1)] = km.group(2).strip().strip('"\'')
    return fm, top


def check_skill(name, text):
    """返回 (violations, warnings)。"""
    v, w = [], []
    fm, top = parse_frontmatter(text)
    if fm is None:
        v.append({"skill": name, "check": "A1", "detail": "frontmatter 块缺失（--- 包裹）"})
        return v, w
    for req in ("name", "description"):
        if not top.get(req):
            v.append({"skill": name, "check": "A1", "detail": "必填字段 %s 缺失或为空" % req})
    desc = top.get("description", "")
    if len(desc) > DESC_MAX:
        v.append({"skill": name, "check": "A2",
                  "detail": "description %d 字符 > %d" % (len(desc), DESC_MAX)})
    extra = sorted(set(top.keys()) - ALLOWED_KEYS)
    if extra:
        v.append({"skill": name, "check": "A3", "detail": "顶层字段不在白名单: %s" % extra})
    if top.get("name") and top["name"] != name:
        w.append({"skill": name, "check": "W1",
                  "detail": "name=%s 与目录名不一致" % top["name"]})
    return v, w


def run_compliance(root=None):
    root = root or config.GLOBAL_SKILLS
    violations, warnings, n = [], [], 0
    if os.path.isdir(root):
        for skill in sorted(os.listdir(root)):
            sk = os.path.join(root, skill, "SKILL.md")
            if not os.path.isfile(sk):
                continue
            n += 1
            text = open(sk, encoding="utf-8", errors="ignore").read(8192)
            v, w = check_skill(skill, text)
            violations += v
            warnings += w
    return {
        "schema": "fenjue-skill-publish-compliance-v1",
        "skills": n, "violations": violations, "warnings": warnings,
        "pass": (n > 0 and not violations),
    }


def _selftest():
    import tempfile
    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    with tempfile.TemporaryDirectory() as td:
        def mk(skill, body):
            d = os.path.join(td, skill)
            os.makedirs(d)
            open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8").write(body)
        mk("good-skill", "---\nname: good-skill\ndescription: 合规技能。\nversion: 1.0\n---\n# ok\n")
        mk("no-fm", "# 没有 frontmatter\n")
        mk("long-desc", "---\nname: long-desc\ndescription: " + "x" * 1100 + "\n---\n")
        mk("weird-key", "---\nname: weird-key\ndescription: d\nnot_a_real_key_xyz: 1\n---\n")
        mk("alias-skill", '---\nname: other-name\ndescription: "带引号"\n---\n')
        res = run_compliance(td)
        vs = {x["skill"] for x in res["violations"]}
        ws = {x["skill"] for x in res["warnings"]}
        check("T1 正例:合规技能零违规零告警", "good-skill" not in vs | ws)
        check("T2 违规:frontmatter 缺失被拦", "no-fm" in vs)
        check("T2 违规:description 超 1024 被拦", any(x["check"] == "A2" for x in res["violations"]))
        check("T2 违规:未知顶层字段被拦",
              any(x["check"] == "A3" and x["skill"] == "weird-key" for x in res["violations"]))
        check("T3 告警:name 错位不阻断", "alias-skill" in ws and "alias-skill" not in vs)
        check("T3 边界:带引号 description 值正确剥离",
              not any(x["skill"] == "alias-skill" and x["check"] == "A1"
                      for x in res["violations"]))
        empty = run_compliance(os.path.join(td, "not-exist"))
        check("T4 边界:空扫描面不得静默过(R247)", empty["pass"] is False)
        check("T4 判定:有违规 → pass=False", res["pass"] is False)

    n = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("  [%s] %s" % ("OK  " if ok else "FAIL", label))
    print(f"skill_publish_compliance selftest: {n}/{len(cases)}")
    return 0 if n == len(cases) else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return _selftest()
    root = None
    if "--path" in argv:
        i = argv.index("--path")
        if i + 1 >= len(argv):
            print("用法错误: --path 需要目录", file=sys.stderr)
            return 2
        root = argv[i + 1]
    res = run_compliance(root=root)
    if "--json" in argv:
        import json
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print("=" * 64)
        print("技能发布合规校验（P2E-2）— 技能 %d 个" % res["skills"])
        for x in res["violations"]:
            print("  ❌ [%s] %s :: %s" % (x["check"], x["skill"], x["detail"]))
        for x in res["warnings"]:
            print("  ⚠️ [%s] %s :: %s" % (x["check"], x["skill"], x["detail"]))
        print("判定: %s" % ("PASS ✅" if res["pass"] else "FAIL ❌"))
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
