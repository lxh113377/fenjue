# -*- coding: utf-8 -*-
"""技能可移植性棘轮（C20）—— SKILL.md 绝对路径引用的「只许降不许升」基线。

背景（2026-09-23 P0-1，Superpowers 对标产出）：对标项目用 `test-skill-structure.sh` 检查
skill 的 local path leakage，而本仓 151 个技能实测 **35 个含行内绝对路径、18 个含代码块内
绝对路径**，此前无任何判据阻止新增技能硬编码 `<MEMORY_ROOT>` / `C:/Users/<用户>`。

判定分级
--------
- ``code``   —— fenced code block 内的绝对路径（可执行示例 / 硬编码，高风险）
- ``inline`` —— 代码块外的说明性引用（文档叙述，低风险）

棘轮语义（同族：[[style_ratchet]]）
-----------------------------------
- 新增技能含绝对路径                  -> FAIL
- 既有技能 code / inline 计数上升      -> FAIL
- 计数下降但不为 0                    -> PASS（提示可 ``--update`` 收紧基线）
- 基线缺失 / 基线空 / 扫描面为空       -> FAIL（R247：无处可比不得判过）

CLI::

    python portability_ratchet.py                 # 校验（默认）
    python portability_ratchet.py --update        # 用当前实测重写基线（收紧）
    python portability_ratchet.py --json          # 机器可读输出
    python portability_ratchet.py --selftest      # 内置三要素自检（隔离桩转发用）
    python portability_ratchet.py --diff [--scan-root .] [--range auto]
        # 新增行直接 deny（任务⑦）：SKILL.md 新增行含绝对路径即 FAIL，
        # 无基线 grandfathering；空面 PASS（明示）。CI 可移植。
    python portability_ratchet.py --check-baseline
        # 基线内部一致性（CI 可移植）：totals 必须 == 明细之和，防注水调大基线。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import GLOBAL_SKILLS  # noqa: E402

DEFAULT_SKILLS_DIR = Path(GLOBAL_SKILLS)
BASELINE_NAME = "portability_baseline.json"
SCHEMA = "fenjue-portability-baseline-v1"
ABS_RE = re.compile(r"(?:D:\\|<USER_HOME>)")  # path-hygiene:ok（判据自身/自检夹具必须造出真实盘符形状）
FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
# --diff 拒绝面：只看 SKILL.md 新增行（.py 归 path_hygiene 管，文档元引用不管）
SKILL_GLOB = "SKILL.md"


def _baseline_path(baseline=None):
    return Path(baseline) if baseline else Path(__file__).resolve().parent / BASELINE_NAME


def _skills_root(skills_dir=None):
    return Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR


def skills_root_reachable(skills_dir=None):
    """技能根是否可达（含 ≥1 个 SKILL.md）。CI（ubuntu）不可达 → 调用方走 SKIP。"""
    root = _skills_root(skills_dir)
    if not root.is_dir():
        return False
    try:
        return any(root.glob("*/SKILL.md"))
    except OSError:
        return False


def scan(skills_dir=None):
    """扫描 ``<skills_dir>/*/SKILL.md``，返回 {skill: {'code': n, 'inline': m}}（仅含有命中的）。"""
    root = _skills_root(skills_dir)
    per = {}
    for fp in sorted(root.glob("*/SKILL.md")):
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        in_code, code, inline = False, 0, 0
        for ln in text.splitlines():
            if FENCE_RE.match(ln):
                in_code = not in_code
                continue
            n_abs = len(ABS_RE.findall(ln))
            if n_abs:
                if in_code:
                    code += n_abs
                else:
                    inline += n_abs
        if code or inline:
            per[fp.parent.name] = {"code": code, "inline": inline}
    return per


def load_baseline(baseline=None):
    p = _baseline_path(baseline)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_baseline(per, baseline=None):
    p = _baseline_path(baseline)
    payload = {
        "schema": SCHEMA,
        "generated": datetime.now().strftime("%Y-%m-%d"),
        "note": ("C20 技能可移植性棘轮基线：绝对路径引用只许降不许升；新增技能禁含绝对路径。"
                 "只有 --update 才可收紧。code = 代码块内（高风险），inline = 行内说明（低风险）。"),
        "skills": {k: per[k] for k in sorted(per)},
        "totals": {
            "files_with_abs": len(per),
            "code": sum(v["code"] for v in per.values()),
            "inline": sum(v["inline"] for v in per.values()),
        },
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def check(baseline=None, skills_dir=None):
    """返回 ``(failures, notes, summary)``。"""
    root = _skills_root(skills_dir)
    current = scan(root)
    base = load_baseline(baseline)
    failures, notes = [], []

    n_files = len(list(root.glob("*/SKILL.md")))
    if n_files == 0:
        return (["未扫描到任何 SKILL.md（skills_dir 配置错误或判据面失效，R247）"], [], "扫描面为空")
    if base is None:
        return (["基线文件缺失（判据面失效，R247）—— 先跑 --update 生成基线"], [], "基线缺失")
    base_skills = base.get("skills") or {}
    if not base_skills:
        return (["基线 skills 为空（判据面失效，R247）—— 无处可比不得判过"], [], "基线为空")

    for name, cnt in sorted(current.items()):
        b = base_skills.get(name)
        if b is None:
            failures.append("新增绝对路径技能 {0}（code={1}/inline={2}）".format(
                name, cnt["code"], cnt["inline"]))
            continue
        if cnt["code"] > b.get("code", 0) or cnt["inline"] > b.get("inline", 0):
            failures.append("{0} 计数上升 code {1}->{2} / inline {3}->{4}".format(
                name, b.get("code", 0), cnt["code"], b.get("inline", 0), cnt["inline"]))

    for name, b in sorted(base_skills.items()):
        if name not in current and (b.get("code", 0) or b.get("inline", 0)):
            notes.append("{0} 已清零（可 --update 收紧基线）".format(name))

    summary = "棘轮正常：{0}/{1} 技能含绝对路径（code {2} / inline {3}）；基线 {4} 技能".format(
        len(current), n_files,
        sum(v["code"] for v in current.values()),
        sum(v["inline"] for v in current.values()),
        len(base_skills))
    return (failures, notes, summary)


# ── 新增行直接 deny（任务⑦：新 skill CI 直接 deny 绝对路径）───────────────────
def _git(cwd, *args):
    import subprocess
    return subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=60)


def _resolve_range(root):
    """--range auto 的基线自动推导：PR base → origin/master merge-base → HEAD~1。

    都不可用时返回 None（调用方退化为 worktree 模式：staged + 未暂存 + 未跟踪）。
    """
    base_ref = os.environ.get("GITHUB_BASE_REF", "")
    if base_ref:
        return "origin/%s...HEAD" % base_ref
    r = _git(root, "rev-parse", "--verify", "--quiet", "origin/master")
    if r.returncode == 0:
        m = _git(root, "merge-base", "origin/master", "HEAD")
        if m.returncode == 0 and m.stdout.strip():
            return "%s..HEAD" % m.stdout.strip()
    r = _git(root, "rev-parse", "--verify", "--quiet", "HEAD~1")
    if r.returncode == 0:
        return "HEAD~1..HEAD"
    return None


def _collect_added_skill_lines(root, rev_range=None):
    """收集 SKILL.md 新增行 [(rel, lineno_or_None, line)]。

    rev_range 为 None → worktree 模式：staged + 未暂存 diff + 未跟踪文件全文；
    否则 → `git diff <range> -- '*SKILL.md'` 的新增行（CI 用）。
    非 git 目录 → worktree 下全部 SKILL.md 按全文计入（显式严格，不静默）。
    """
    root = Path(root)
    out = []

    def _is_skill(path_str):
        return path_str.replace("\\", "/").endswith("/" + SKILL_GLOB) or \
            path_str.replace("\\", "/") == SKILL_GLOB

    r = _git(root, "rev-parse", "--is-inside-work-tree")
    in_git = r.returncode == 0 and r.stdout.strip() == "true"
    if not in_git:
        for fp in sorted(root.rglob(SKILL_GLOB)):
            try:
                lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            rel = str(fp.relative_to(root)).replace("\\", "/")
            for no, ln in enumerate(lines, 1):
                out.append((rel, no, ln))
        return out

    if rev_range == "auto":
        rev_range = _resolve_range(root)
    if rev_range:
        r = _git(root, "diff", "--no-color", "-U0", rev_range, "--", "*%s" % SKILL_GLOB)
        cur = None
        for ln in (r.stdout or "").splitlines():
            if ln.startswith("+++ "):
                p = ln[4:].strip()
                if p.startswith("b/"):
                    p = p[2:]
                cur = p if _is_skill(p) else None
                continue
            if cur and ln.startswith("+") and not ln.startswith("+++"):
                out.append((cur, None, ln[1:]))
        return out

    # worktree 模式：staged + 未暂存
    for args in (["diff", "--cached", "--no-color", "-U0", "--", "*%s" % SKILL_GLOB],
                 ["diff", "--no-color", "-U0", "--", "*%s" % SKILL_GLOB]):
        r = _git(root, *args)
        cur = None
        for ln in (r.stdout or "").splitlines():
            if ln.startswith("+++ "):
                p = ln[4:].strip()
                if p.startswith("b/"):
                    p = p[2:]
                cur = p if _is_skill(p) else None
                continue
            if cur and ln.startswith("+") and not ln.startswith("+++"):
                out.append((cur, None, ln[1:]))
    # 未跟踪的 SKILL.md：全文计入
    r = _git(root, "status", "--porcelain", "--untracked-files=all", "--", "*%s" % SKILL_GLOB)
    for ln in (r.stdout or "").splitlines():
        if not ln.startswith("??"):
            continue
        rel = ln[3:].strip().strip('"')
        fp = root / rel
        if not _is_skill(rel) or not fp.is_file():
            continue
        try:
            lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for no, line in enumerate(lines, 1):
            out.append((rel.replace("\\", "/"), no, line))
    return out


def diff_deny(scan_root=None, rev_range=None):
    """新增 SKILL.md 绝对路径行直接 deny（无基线 grandfathering）。

    返回 (rc, message)：rc 0 = PASS，1 = FAIL（有新增绝对路径）。
    空面 → PASS，但消息明示「无新增 SKILL.md 行」（R247：空面不得静默）。
    """
    root = Path(scan_root) if scan_root else _skills_root()
    if not root.is_dir():
        root = Path.cwd()
    added = _collect_added_skill_lines(root, rev_range)
    if not added:
        return (0, "无新增 SKILL.md 行（扫描面为空，PASS；存量归棘轮基线管）")
    bad = [(rel, no, ln) for rel, no, ln in added if ABS_RE.search(ln)]
    if not bad:
        return (0, "新增 SKILL.md 行 %d，无绝对路径（PASS）" % len(added))
    msg = ["deny 新增绝对路径 %d 处（%d 新增行）：" % (len(bad), len(added))]
    for rel, no, ln in bad[:10]:
        where = "%s:%s" % (rel, no if no else "新增行")
        msg.append("   ❌ %s → %s" % (where, ln.strip()[:90]))
    msg.append("修复：改用 ${GLOBAL_MEMORY} / ${GLOBAL_SKILLS} 占位符 + 运行期解析兜底")
    return (1, "\n".join(msg))


def check_baseline_consistency(baseline=None):
    """基线文件内部一致性（CI 可移植：不读 <SKILLS_ROOT>，只验 committed 基线）。

    totals.files_with_abs/code/inline 必须 == skills 明细之和；
    注水（调大 totals 冒充收紧）→ FAIL。空 skills → FAIL（R247）。
    """
    base = load_baseline(baseline)
    if base is None:
        return (1, "基线文件缺失或不可解析（判据面失效，R247）")
    skills = base.get("skills") or {}
    if not skills:
        return (1, "基线 skills 为空（判据面失效，R247）")
    totals = base.get("totals") or {}
    exp = {"files_with_abs": len(skills),
           "code": sum(v.get("code", 0) for v in skills.values()),
           "inline": sum(v.get("inline", 0) for v in skills.values())}
    drift = {k: (totals.get(k), exp[k]) for k in exp if totals.get(k) != exp[k]}
    if drift:
        return (1, "基线 totals 与明细不一致（疑似注水/手改）：%s" % drift)
    return (0, "基线内部一致（%d 技能 / code %d / inline %d）" % (
        exp["files_with_abs"], exp["code"], exp["inline"]))


# ── 内置三要素自检（隔离桩转发用）──────────────────────────────────────────
def _selftest():
    import tempfile

    cases = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        root = td / "skills"
        root.mkdir()

        def mk(name, body):
            d = root / name
            d.mkdir(exist_ok=True)
            (d / "SKILL.md").write_text(body, encoding="utf-8")

        mk("clean", "# Skill\n\n无绝对路径，纯说明。\n")
        mk("pinned", "# Skill\n\n见 <MEMORY_ROOT>\\x.md 的说明。\n")  # path-hygiene:ok（判据自身/自检夹具必须造出真实盘符形状）
        mk("coded", "# Skill\n\n```bash\npython run.py D:\\videos\\a.mp4\n```\n")  # path-hygiene:ok（判据自身/自检夹具必须造出真实盘符形状）
        base = td / "base.json"
        write_baseline(scan(root), base)

        # 1 正例：等于基线
        f, _n, _s = check(base, root)
        cases.append(("正例-恰等于基线不报", len(f) == 0))
        # 2 边界：等于基线（显式边界项）
        cases.append(("边界-基线含 code/inline 两类且不误报",
                      len(f) == 0 and scan(root)["coded"]["code"] == 1))

        # 3 违规样本 A：新增技能含绝对路径
        mk("newbie", "# Skill\n\n<SKILLS_ROOT>\\y.md\n")
        f, _n, _s = check(base, root)
        cases.append(("违规A-新增技能含路径", any("新增绝对路径技能 newbie" in x for x in f)))

        # 4 违规样本 B：既有技能 inline 计数上升
        mk("pinned", "# Skill\n\n见 <MEMORY_ROOT>\\x.md 与 <MEMORY_ROOT>\\z.md。\n")  # path-hygiene:ok（判据自身/自检夹具必须造出真实盘符形状）
        f, _n, _s = check(base, root)
        cases.append(("违规B-既有技能计数上升", any("pinned" in x and "计数上升" in x for x in f)))

        # 5 违规样本 C：既有技能 code 计数上升
        mk("coded", "# Skill\n\n```bash\npython run.py D:\\videos\\a.mp4 D:\\videos\\b.mp4\n```\n")  # path-hygiene:ok（判据自身/自检夹具必须造出真实盘符形状）
        f, _n, _s = check(base, root)
        cases.append(("违规C-代码块内计数上升", any("coded" in x and "计数上升" in x for x in f)))

        # 6 边界：基线文件缺失
        f, _n, _s = check(td / "nope.json", root)
        cases.append(("边界-基线缺失报错", len(f) == 1 and "基线" in f[0]))

        # 7 边界：扫描面为空
        empty = td / "empty"
        empty.mkdir()
        f, _n, _s = check(base, empty)
        cases.append(("边界-扫描面为空报错", len(f) == 1 and "未扫描到" in f[0]))

        # 8 边界：基线 skills 为空
        emptied = td / "empty_base.json"
        emptied.write_text(json.dumps({"schema": SCHEMA, "skills": {}}), encoding="utf-8")
        f, _n, _s = check(emptied, root)
        cases.append(("边界-基线为空报错", len(f) == 1 and "为空" in f[0]))

    passed = sum(1 for _n, ok in cases if ok)
    for n, ok in cases:
        print("  [{0}] {1}".format("OK" if ok else "FAIL", n))
    print("{0}/{1}".format(passed, len(cases)))
    return 0 if passed == len(cases) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="技能可移植性棘轮（C20）")
    ap.add_argument("--update", action="store_true", help="用当前实测重写基线（收紧）")
    ap.add_argument("--skills-dir", default=None, help="技能根目录（默认 <SKILLS_ROOT>）")
    ap.add_argument("--baseline", default=None, help="基线文件路径")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--diff", action="store_true",
                    help="新增行直接 deny：扫描 SKILL.md 新增行（staged+未暂存+未跟踪），"
                         "任何绝对路径新增即 FAIL（任务⑦：新 skill CI 直接 deny）")
    ap.add_argument("--range", default=None,
                    help="diff 基线区间（如 HEAD~1..HEAD；auto=自动推导 PR base/origin-master；"
                         "缺省=worktree 模式）")
    ap.add_argument("--scan-root", default=None, help="--diff 扫描根（缺省=技能根可达则用之，否则当前目录）")
    ap.add_argument("--check-baseline", action="store_true",
                    help="基线内部一致性（CI 可移植：只验 committed 基线 totals==明细，不读技能盘）")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.check_baseline:
        rc, msg = check_baseline_consistency(args.baseline)
        print(("✅ " if rc == 0 else "🔴 ") + msg)
        return rc
    if args.diff:
        rc, msg = diff_deny(args.scan_root, args.range)
        print(("✅ " if rc == 0 else "🔴 ") + msg)
        return rc
    if args.update:
        per = scan(args.skills_dir)
        p = write_baseline(per, args.baseline)
        print("✅ 基线已更新: {0}（{1} 技能 / code {2} / inline {3}）".format(
            p, len(per), sum(v["code"] for v in per.values()),
            sum(v["inline"] for v in per.values())))
        return 0

    failures, notes, summary = check(args.baseline, args.skills_dir)
    if args.json:
        print(json.dumps({"schema": "fenjue-portability-check-v1", "ok": not failures,
                          "summary": summary, "failures": failures, "notes": notes},
                         ensure_ascii=False, indent=2))
        return 1 if failures else 0
    print(("🔴 " if failures else "✅ ") + summary)
    for x in failures:
        print("   ❌ " + x)
    for x in notes:
        print("   ℹ️ " + x)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
