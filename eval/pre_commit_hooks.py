#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pre_commit_hooks.py — 焚诀本地 pre-commit 门禁统一入口（R192/R193/R194/R198.6）

全量闸（**权威清单 = 模块级 GATES 列表顺序**；任一次失败 = 提交被拒）。
2026-09-24 对标轮修正：原文案写「十道闸」且条目编号跳号（1 → 12 → 2…10），实际 14 道 ——
门禁数与文案数各自腐烂，正是 C5/C16 要杀的病灶，只是发生在注释面。
对标轮四 D-21 续修：闸数与 PASS 行数字改由 GATES **运行时派生**，本注释不再声明「共 N 道」，
也不再抄写 C 项范围（`.git/hooks/*` 不被 git 跟踪 ⇒ 那里的静态数字必然腐烂）。

  1.  truth-consistency   verify_truth_consistency.py（真相源门禁全集；项数以该脚本输出为准）
                          （C17/C18 跨消费方排除清单/多写入方契约，C29 index.md 与派生评分产物
                          对账，均无 SKIP 逃生门）
  2.  secret-scan         暂存/跟踪文件含 sk-[A-Za-z0-9]{20,}
  3.  pytest              eval/tests
  4.  junction-health     R193；CI 无 junction 自动跳过
  5.  direct-map-guard    R193；eval/direct_map.d/ 存在 = 未入库直连规则（R192 实证 17 条）
  6.  duplicate-live-guard R194；活目录禁备份后缀/跨目录同名重复实现，publish/ 豁免
  7.  derived-indexes     R198.6；build_indexes.py --check 守恒（防 2026-08-16 假 FAIL 事故）
  8.  style-ratchet       风格棘轮（基线 eval/style_ratchet_baseline.json）
  9.  retire-reconcile    R198.6；黑名单 vs 注册表 vs 索引三方对账（防退役被拉回）
  10. index-refs          R196-05；涉及 memory_index.part3* 时 fail-closed
  11. path-index-due      R199；季度逾期，仅涉 path_index.md 时 fail-closed
  12. split-tool-selftest 2026-09-21；split_md_4kb.py 5 条自测
  13. skill-onboarding-audit 新技能上架合规自检
  14. tdd-gate            七步⑥ RED-GREEN 强制门（生产 .py 改动无测试证据 → 拒）
  15. gate-stubs          对标轮四 6-E/7-B；隔离桩全集 + 判据覆盖对账（桩红=判据真红镜像，
                          接线前桩红可长期存在，R3 D-13 预言于本轮第二次实证）
  16. push-health         对标轮六 D-39；本地领先远端的提交数（自动推送失败此前结构上不可见，
                          ≥3 判红 = 备份链已断，先 push 再堆提交）
  17. control-char-lock   对标轮十六 D-89；跟踪文本面里的控制字符（`\\b` 被解释成 0x08
                          曾静默打死接线判据的 import 半边，整条本地闸链全看不见）
  18. static-locks        对标轮十七 D-98 / 轮十八 D-112、D-114；把 CI-only 的七把静态锁（path-hygiene / part-size /
                          wiring-census / claim-count）在提交前本地复跑一遍——CI 拿不到 runner 时
                          这 11 条 CI-only 判据处于零约束，path-hygiene 实测红了两个多小时无人知

用法：由 .git/hooks/pre-commit 直接调用（不走 pre-commit 框架，根因见 hook 头部注释）；
也可手动 `python eval/pre_commit_hooks.py`。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROBE = object()  # "没传读数 ⇒ 自己去探盘"的哨兵（不能用 None：None 另有"探过但没数"之义）


def _find_pytest_python() -> str:
    """探测可运行 pytest 的解释器。

    pre-commit 框架以 `language: system` 执行 entry，`python` 解析为 PATH 解释器
    （本机 3.10.11 无 pytest）→ check_pytest 会失败。故统一探测 workbuddy 解释器
    （含 pytest），fallback 到 sys.executable。
    """
    candidates = [
        r"<USER_HOME>\.workbuddy\binaries\python\envs\default\Scripts\python.exe",  # machine-path-ok
        r"<USER_HOME>\.workbuddy\binaries\python\versions\3.13.12\python.exe",  # machine-path-ok
        sys.executable,
    ]
    for cand in candidates:
        if not cand or not os.path.isfile(cand):
            continue
        try:
            r = subprocess.run([cand, "-c", "import pytest"], capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                return cand
        except (OSError, subprocess.TimeoutExpired):
            continue
    return sys.executable


PY = _find_pytest_python()
SECRET_RE = re.compile(r"sk-[A-Za-z0-9]{20,}")
DUPLICATE_GUARD_DIRS = ["eval", "audit", "scripts", "feedback"]
BACKUP_MARKERS = ("_v1_backup", "_bak", ".bak", "_backup", "_old", "_legacy", "副本")
DUPLICATE_CODE_EXTS = (".py", ".ps1", ".sh", ".js")


def _run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    """统一子进程执行器。默认 1800s 上限防任一闸挂死提交；超时按该闸 FAIL 处理
    （returncode 124，判据不降低——只是把"永久挂起"变成"超时失败"）。"""
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "ignore")
        err = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode("utf-8", "ignore")
        err += f"\n[timeout] 命令超过 {timeout}s 被终止: {' '.join(cmd)}"
        return subprocess.CompletedProcess(cmd, 124, out, err)


def _git_dirs() -> tuple:
    g = _run(["git", "rev-parse", "--git-dir"]).stdout.strip()
    c = _run(["git", "rev-parse", "--git-common-dir"]).stdout.strip()
    return (os.path.normpath(os.path.join(ROOT, g)) if g else "",
            os.path.normpath(os.path.join(ROOT, c)) if c else "")


def degraded_worktree(git_dir: str = "", common_dir: str = "") -> bool:
    """是否运行在 linked worktree 里（D-45）。

    隔离工作树里 `memory/` 等 junction 不物化、CI 产物也不在，判据面天生缺一半；
    实测主树 32 PASS/0 FAIL，而隔离树全量跑有 4 项红在读不到东西（不是内容漂移）。
    因此 worktree 内按 CI 同款 `--skip-external` 跑并**显式声明降级**——全量链仍在主
    工作树与 CI 上执行。取不到 git 时返回 False（宁可多判红，不静默降级）。
    """
    if not git_dir and not common_dir:
        git_dir, common_dir = _git_dirs()
    if not git_dir or not common_dir:
        return False
    return git_dir != common_dir


def check_truth() -> bool:
    extra = ["--skip-external"] if degraded_worktree() else []
    if extra:
        print("[truth-consistency] 降级模式：当前是 linked worktree（判据面天生不全，实测主树 32 PASS"
              " / 本树 24 PASS + 9 SKIP）⇒ 本树只跑可达判据，未覆盖项由主工作树与 CI 全量执行；"
              "需要全量本地自证请回主工作树提交。")
    r = _run([PY, os.path.join("eval", "verify_truth_consistency.py")] + extra)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode == 0:
        return True
    # 第 1 闸跑的是全量 verify，输入是整块磁盘当前态；多 agent 共享同一工作树时，
    # 别人在途的半成品会把我的提交一起拦死（对标轮五实测 4 例，红因全非本次引入）。
    # 归因逻辑与"仍必须拦"的三种情形见 eval/gate_scope_attribution.py（fail-closed）。
    # CI 端仍跑全量 verify，本地放行只是不替他人背锅，不是这条不查了。
    try:
        sys.path.insert(0, os.path.join(ROOT, "eval"))
        import gate_scope_attribution as gsa
        jr = _run([PY, os.path.join("eval", "verify_truth_consistency.py"), "--json"] + extra)
        data = json.loads(jr.stdout)
        results = data.get("results") if isinstance(data, dict) else data
        staged = gsa.staged_paths()
        prior = gsa.streaks()
        allow, items, banner = gsa.classify(results, staged, prior=prior)
        gsa.record(items, list(staged[0]))
        if allow:
            print("[truth-consistency] ⚠ 存在 FAIL，但经归因均为**他人存量红**（已落 shared_red_ledger）：")
            print(banner)
            debt = ["%s×%d" % (c, n) for c, n in sorted(prior.items())
                    if n >= gsa.EXEMPT_CAP]
            if debt:
                print("  在册存量红债务（连续豁免 ≥%d）：%s" % (gsa.EXEMPT_CAP, " ".join(debt)))
                print("  债务不会因提交而消失：修好后 python eval/gate_scope_attribution.py --resolve <ID> 真销账")
            print("  判据本身未削弱：CI 仍跑全量 verify；肇事提交（命中暂存面/不可归因）恒拦。")
            return True
        print("[truth-consistency] 归因结论：本次改动面命中或不可归因 ⇒ 仍阻断")
        print(banner)
    except Exception as e:  # noqa: BLE001  归因器坏掉不得变成放行通道
        print("[truth-consistency] 归因器不可用（%s）⇒ fail-closed 维持阻断" % e)
    return False


def check_secrets() -> bool:
    tracked = _run(["git", "ls-files", "-z"])
    staged = _run(["git", "diff", "--cached", "--name-only", "-z"])
    if tracked.returncode != 0 or staged.returncode != 0:
        print("[secret-scan] git 命令失败，无法扫描", file=sys.stderr)
        return False
    files = {f for f in (tracked.stdout + "\0" + staged.stdout).split("\0") if f}
    bad: list[str] = []
    for rel in sorted(files):
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for line_no, line in enumerate(fh, 1):
                    if SECRET_RE.search(line):
                        bad.append(f"{rel}:{line_no}")
        except OSError:
            continue
    if bad:
        print("[secret-scan] FAIL 检测到疑似密钥（sk-*）：")
        for item in bad:
            print("  " + item)
        return False
    print("[secret-scan] PASS 无 sk- 密钥")
    return True


def check_pytest() -> bool:
    # R278（2026-09-22）：显式 --basetemp 到**带秒级时间戳的专用目录**。
    # 原因：本机装有 safe-delete 保护钩子，pytest 默认 basetemp（%TEMP%\\pytest-of-*）
    # 在清理时会命中「批量删除确认」（实测 count 955 > threshold 500）并 raise SystemExit(1)
    # ⇒ pytest 恒以退出码 1 结束，**全量 pre-commit 恒 FAIL（环境性假失败，非测试不过）**。
    # 用一次性新目录规避跨轮次累积；失败时其内容保留供排查。
    import tempfile
    import time as _time
    _bt = os.path.join(tempfile.gettempdir(), "fenjue_pt_%d" % int(_time.time()))
    r = _run([PY, "-m", "pytest", "eval/tests", "-q", "-p", "no:cacheprovider",
              "--basetemp=" + _bt])
    sys.stdout.write(r.stdout[-6000:])
    sys.stderr.write(r.stderr[-2000:])
    return r.returncode == 0


def check_junctions() -> bool:
    """junction 健康检查（R193）：四端 junction 必须存在且指向 <MEMORY_ROOT>。
    CI（<MEMORY_ROOT> 不可达）自动跳过；本地任一 junction 失效 = 提交被拒。
    R206-01 对齐（2026-08-24 CC 直读定案）：cross_platform_map.json platform_facts
    声明「直读模式/无 junction 消费者」的端点不要求 junction 存在——与
    run-health-check.ps1 v1.3 的 DIRECT_READ 校验同口径，消除双消费者规则漂移。"""
    sys.path.insert(0, os.path.join(ROOT, "eval"))
    try:
        from truth_constants import GLOBAL_MEMORY, get_junction_pairs
    except Exception as e:
        print(f"[junction-health] 无法加载 truth_constants: {e}", file=sys.stderr)
        return False
    if not os.path.isdir(GLOBAL_MEMORY):
        print("[junction-health] SKIP: <MEMORY_ROOT> 不可达（CI 环境，无 junction）")
        return True
    import json
    direct_read = set()
    try:
        cpm_path = os.path.join(GLOBAL_MEMORY, "cross_platform_map.json")
        with open(cpm_path, encoding="utf-8") as f:
            facts = (json.load(f) or {}).get("platform_facts", {})
        for ep, txt in facts.items():
            if isinstance(txt, str) and ("直读模式" in txt or "无 junction 消费者" in txt):
                direct_read.add(str(ep).lower())
    except Exception as e:
        print(f"[junction-health] cross_platform_map 读取失败（保持严格校验）: {e}", file=sys.stderr)
    broken = []
    checked = 0
    skipped = 0
    for label, path, target in get_junction_pairs():
        ep = label.rsplit("_", 1)[0].lower()
        if ep in direct_read:
            skipped += 1
            print(f"[junction-health] SKIP {label}（cross_platform_map 登记直读模式，无 junction 消费者）")
            continue
        checked += 1
        try:
            ok = os.path.exists(path) and os.path.realpath(path) != os.path.abspath(path)
        except Exception as e:
            ok = False
            print(f"[junction-health] {label} 检查异常: {e}", file=sys.stderr)
        if not ok:
            broken.append(f"{label} -> {path}")
    if broken:
        print(f"[junction-health] FAIL: {len(broken)}/{checked} junction 失效")
        for b in broken:
            print("  " + b)
        return False
    print(f"[junction-health] PASS: {checked}/{checked} junction 健康（直读端点跳过 {skipped}）")
    return True


def check_direct_map_dir() -> bool:
    """R193 护栏: eval/direct_map.d/ 存在 = 未入库直连规则 → 提交被拒。

    根因（R192 实证）：R184/R185 时代的直连补丁只放在未入库的 direct_map.d/ 分卷，
    清场删除后 direct_map.json 仍是剪枝版，盲测 284/284 静默掉到 268/284。
    直连规则只允许双写 eval/direct_map.json + eval/direct_layer.py _DIRECT_MAP_FALLBACK。
    """
    d = os.path.join(ROOT, "eval", "direct_map.d")
    if os.path.exists(d):
        print(f"[direct-map-guard] FAIL: {d} 存在（未入库直连规则，清场时会被误删）")
        print("    迁移步骤：将规则双写入 eval/direct_map.json + eval/direct_layer.py 的")
        print("    _DIRECT_MAP_FALLBACK，补回归用例到 test_router_regression.py，然后删除该目录。")
        return False
    print("[direct-map-guard] PASS: 无 direct_map.d（直连规则均在入库文件）")
    return True


def check_duplicates() -> bool:
    """R194 第六闸 duplicate-live-guard。

    扫描 eval/audit/scripts/feedback 活目录（publish/ 豁免——发布快照）：
    1. 禁备份后缀文件（_v1_backup/_bak/.bak/_backup/_old/_legacy/副本）
    2. 禁跨目录同名代码实现（同 basename 的 .py/.ps1/.sh/.js）
    """
    problems: list[str] = []
    seen: dict[str, list[str]] = {}
    for d in DUPLICATE_GUARD_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            # R198 豁免: .prompt_versions 是 prompt_version.py 的受控快照/回滚备份目录
            # (scripts/prompt_version.py:26-28, 已入 .gitignore)，其 backups/ 下的 .bak 为
            # 合法回滚产物，非噪声；与 publish/ 同类，跳过去重/后缀扫描。
            dirnames[:] = [x for x in dirnames if x not in ("__pycache__", ".prompt_versions")]
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                if ".prompt_versions" in rel:
                    continue
                low = fn.lower()
                if any(marker in low for marker in BACKUP_MARKERS):
                    problems.append(f"[backup-suffix] {rel}")
                    continue
                if low.endswith(DUPLICATE_CODE_EXTS):
                    seen.setdefault(low, []).append(rel)
    for basename, paths in sorted(seen.items()):
        if len(paths) > 1:
            problems.append(f"[duplicate-impl] {basename}: {', '.join(paths)}")
    if problems:
        print("[duplicate-live-guard] FAIL:")
        for p in problems:
            print("  " + p)
        print("    publish/ 为发布快照豁免；活目录残留请移 archive/ 或 git rm。")
        return False
    print("[duplicate-live-guard] PASS: 无备份后缀/跨目录同名重复实现")
    return True


def parse_dirty_porcelain(text: str) -> list:
    """从 `git status --porcelain` 挑出**工作树侧**脏路径（未提交/未跟踪）。

    第 1 列=暂存区状态，第 2 列=工作树状态；只看第 2 列非空非 `.` 的行，
    再加未跟踪（`??`）。这样"别人正在改但还没提交"的面就能和本次暂存面对照。
    """
    out = []
    for line in (text or "").splitlines():
        if len(line) < 4:
            continue
        xy = line[:2]
        if xy == "??":
            out.append(line[3:].strip())
        elif xy[1] not in (" ", "."):
            out.append(line[3:].strip())
    return [p for p in out if p]


def note_foreign_inflight(tag: str) -> None:
    """磁盘态闸门失败时的归因**提示**（D-46）：本闸读的是整块磁盘当前态，
    他人未提交的在途改动同样能把它判红。这里只点名可能的根因，**不因此放行**
    （把豁免推广到全部 16 道闸是另一个决策，见 GM 07 P0-35）。"""
    hint = []
    for repo in (ROOT, os.path.join("D:", os.sep, "global_memory")):
        if not os.path.isdir(repo):
            continue
        r = _run(["git", "-C", repo, "status", "--porcelain"])
        dirty = parse_dirty_porcelain(r.stdout)
        if dirty:
            hint.append("%s: %s%s" % (os.path.basename(repo),
                                      ", ".join(dirty[:6]),
                                      " …(+%d)" % (len(dirty) - 6) if len(dirty) > 6 else ""))
    if hint:
        print("[%s] 提示：本闸读磁盘当前态，以下**未提交在途改动**不在本次暂存面内，可能是根因"
              "（仅诊断，不因此放行）：%s" % (tag, " | ".join(hint)))


def freshness_advisory(stale=_PROBE):
    """派生件新鲜度（D-120，advisory）：守恒 ≠ 新鲜，只报告、不改判定。

    口径基线（2026-09-25 实测）：4 个 SKILL.md 比编码件新，与 `disk_manifest` 的 sha 通道 4/4 全等，
    零误报 ⇒ 先以报告形态进链，不做阻断（新指标阻断要先量够误报率）。
    取不到数（无源面/无编码件）时显式写 UNVERIFIED —— 没数不许冒充"新鲜"。
    `stale=None` 与"没传参"必须能分开：前者是"探过了但没数"，后者才是"去探"，
    两义挤在一个哨兵上时，测试里传 None 会静默变成真去探盘（自己的测试抓出来的）。
    """
    if stale is _PROBE:
        try:
            eval_dir = os.path.join(ROOT, "eval")
            if eval_dir not in sys.path:
                sys.path.insert(0, eval_dir)
            import derivative_watch as dw
            stale = dw.stale_sources()
        except Exception as e:  # noqa: BLE001 — advisory 取数失败不得影响本闸判定
            print("[derived-indexes] 新鲜度（advisory）：UNVERIFIED %r" % (e,))
            return None
    if stale is None:
        print("[derived-indexes] 新鲜度（advisory）：UNVERIFIED（源面或编码件面为空）")
        return None
    if stale:
        print("[derived-indexes] 新鲜度（advisory）：%d 个 SKILL.md 比编码件新 ⇒ 派生件用过期输入编的，"
              "跑 build_indexes.py --apply（最早滞后 %.0fs：%s）"
              % (len(stale), stale[0]["lag_s"], ", ".join(x["source"] for x in stale[:5])))
    return stale


def check_derived_indexes() -> bool:
    """派生件守恒校验（R198.6）：build_indexes.py --check 只读验证，不写盘。

    拦截场景：磁盘 skill 源被批量入库/修改但 BGE/TF-IDF/注册表派生件未重建，
    提交时即 FAIL 并提示跑 --apply（2026-08-16 事故复盘固化）。
    CI（<MEMORY_ROOT> 不可达）时 build_indexes 内部自动 SKIP 相关项。
    """
    r = _run([PY, os.path.join("eval", "build_indexes.py"), "--check"])
    sys.stdout.write(r.stdout[-3000:])
    sys.stderr.write(r.stderr[-2000:])
    if r.returncode != 0:
        note_foreign_inflight("derived-indexes")
    freshness_advisory()
    return r.returncode == 0


def check_style_ratchet() -> bool:
    """风格债棘轮（R210-05）：style_ratchet.py 棘轮检查，新增风格违规拦截。

    与 path_hygiene 同款棘轮模式（基线 {文件: {规则码: 数量}}，只进不退）；
    ruff 不可用环境内部自动 SKIP 放行（不误伤只读/降级环境）。
    """
    r = _run([PY, os.path.join("eval", "style_ratchet.py")])
    sys.stdout.write(r.stdout[-2500:])
    sys.stderr.write(r.stderr[-1500:])
    return r.returncode == 0


def check_retire_reconcile() -> bool:
    """退役防回滚对账（R198.6）：retire_reconcile.py 三方对账，无回滚才放行。

    拦截场景：退役黑名单项被批量入库重新拉回注册表/索引（2026-08-16 事故）。
    提交时 FAIL 并提示 --repair + build_indexes --apply（fail-closed）。
    CI（<MEMORY_ROOT> 不可达）时 retire_reconcile 内部自动 PASS（无回滚判定）。
    """
    r = _run([PY, os.path.join("eval", "retire_reconcile.py"), "--json"])
    sys.stdout.write(r.stdout[-3000:])
    sys.stderr.write(r.stderr[-2000:])
    return r.returncode == 0


# R196-05：索引健康检查门禁（Step 4l CI 化）
# 触发条件：提交涉及 memory_index.part3*.md（主题指针表）→ 必查；其他提交仅当
#   check_index_refs 默认目标存在时轻量校验（不阻断非索引改动，避免噪音）。
INDEX_REF_GLOBS = ("memory_index.part3", "memory_index.part3-1")


def _commit_touches_index_refs() -> bool:
    """检测本次暂存提交是否涉及索引指针表。"""
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30)  # P1-6
        for line in (r.stdout or "").splitlines():
            if any(g in line for g in INDEX_REF_GLOBS):
                return True
    except Exception:
        return False
    return False


def check_index_refs() -> bool:
    """索引健康检查（R196-05 CI 门禁）：check_index_refs.py --json。

    - 触发（暂存提交涉及 memory_index.part3*.md）→ fail-closed：缺失即阻断；
    - 非索引改动 → 轻量校验：默认目标缺失仅提示不阻断（避免无关提交被
      历史遗留缺失误伤；周维护 Step 4l 兜底处理）；
    - 与周维护 Step 4l 衔接：CI 每次索引变更即查，周维护兜底例行化。
    """
    script = os.path.join("eval", "check_index_refs.py")
    r = _run([PY, script, "--json"])
    sys.stdout.write(r.stdout[-3000:])
    sys.stderr.write(r.stderr[-2000:])
    touched = _commit_touches_index_refs()
    if touched:
        # 触及索引改动 → fail-closed：任何缺失（exit 1）即拦截
        return r.returncode == 0
    # 未触及索引 → 轻量校验：全绿放行；缺失（exit 1）为历史遗留/非本次改动，
    # 仅提示不阻断（周维护 Step 4l 全量检查兜底）
    if r.returncode != 0:
        print("  ⚠️ 索引默认目标存在缺失（非本次索引改动，不阻断；"
              "周维护 Step 4l / routing_index_health.py 处理）")
    return True


PATH_INDEX_GLOB = "path_index.md"


def _commit_touches_path_index() -> bool:
    """检测本次暂存提交是否涉及 path_index.md（触发 fail-closed 的判据）。"""
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30)  # P1-6
        for line in (r.stdout or "").splitlines():
            if PATH_INDEX_GLOB in line:
                return True
    except Exception:
        return False
    return False


def check_path_index_due() -> bool:
    """季度逾期检测（R199 第 10 闸）：path_index.md 季度实测校验逾期 → 拦截提交。

    退出码约定（check_path_index_due.py）：0=未逾期 / 1=逾期（须先做 Step 4m 校验）/
    2=状态字段缺失或损坏（配置错误，同样拦截防放行）。
    逾期阈值：当前日期 > 状态字段「下次」日期（=下次当天不算逾期，当天可校验）。
    触发条件（R199 降噪，2026-08-17）：仅本次提交涉及 path_index.md 改动 →
    fail-closed（逾期/配置错误拦截）；其余提交仅警告不阻塞（避免季度状态误伤
    无关提交——复刻 index-refs 闸 _commit_touches 模式）。
    """
    script = os.path.join("eval", "check_path_index_due.py")
    r = _run([PY, script])
    sys.stdout.write(r.stdout[-2000:])
    sys.stderr.write(r.stderr[-1000:])
    touched = _commit_touches_path_index()
    if touched:
        # 触发（涉 path_index.md 改动）→ fail-closed：逾期/配置错误均拦截
        return r.returncode == 0
    # 非触发 → 仅警告不阻塞（周维护 Step 4m 全量处理）
    if r.returncode != 0:
        print("  ⚠️ path_index 季度校验状态异常（非本次 path_index 改动，不阻断；"
              "周维护 Step 4m / check_path_index_due.py 处理）")
    return True


def check_split_tool_selftest() -> bool:
    """第 12 闸（2026-09-21）：split_md_4kb.py 自测。

    覆盖 5 条：split 字节无损 / resnap 缩水安全闸 / prune 孤儿归档 /
    unify-names 幂等 / 单一定义点静态检查（拦「两处各写一份」复发）。
    全部在 %TEMP% 沙箱内跑，不触碰全局记忆根（见 truth_constants.GLOBAL_MEMORY_ROOT）与真实 _split_backup。
    """
    r = _run([PY, os.path.join('skill', 'tools', 'split_md_4kb.py'), 'selftest'])
    sys.stdout.write(r.stdout[-2000:])
    sys.stderr.write(r.stderr[-1000:])
    return r.returncode == 0


def check_skill_onboarding_audit() -> bool:
    """第 13 闸（2026-09-21）：新技能上架审计（本地只读）——

    拦「新技能忘记登记 / 忘记同步镜像」：跑 A-skill-onboarding 的 --audit（只读，不改盘），
    内含结构/噪声/安全 + 登记覆盖（磁盘 vs 注册表，排除退役）+ 镜像只读比对。
    该脚本位于本机全局技能根（truth_constants.GLOBAL_SKILLS_ROOT，CI 不可见）→ 缺失时优雅跳过（不误伤最小环境）。
    """
    # 路径由单一定义点拼装（truth_constants.GLOBAL_SKILLS_ROOT），禁止写盘符字面量（path_hygiene ratchet）
    try:
        sys.path.insert(0, os.path.join(ROOT, 'eval'))
        from truth_constants import GLOBAL_SKILLS_ROOT  # noqa: E402
        script = os.path.join(GLOBAL_SKILLS_ROOT, 'A-skill-onboarding', 'assets', 'skill_onboarding.py')
    except Exception as e:
        print('  ⚠ 无法解析全局技能根（%s）→ 跳过上架审计' % e)
        return True
    if not os.path.exists(script):
        print('  ⚠ 未找到 %s（非本机环境）→ 跳过上架审计' % script)
        return True
    r = _run([PY, script, '--audit'])
    sys.stdout.write(r.stdout[-2500:])
    sys.stderr.write(r.stderr[-800:])
    return r.returncode == 0


def check_tdd_gate() -> bool:
    """第 14 闸（2026-09-23，任务④ TDD 入七步⑥）：生产 .py 改动必须有测试证据。

    跑 eval/tdd_gate.py（worktree 模式：staged + 未暂存）——无测试代码 deny；
    另含毁库测试黑名单（2026-09-23 远端推平事故：测试禁 push --force /
    core.worktree / worktree add 等 repo-mutating 操作）。
    """
    r = _run([PY, os.path.join("eval", "tdd_gate.py")])
    sys.stdout.write(r.stdout[-2500:])
    sys.stderr.write(r.stderr[-800:])
    return r.returncode == 0


def check_gate_stubs() -> bool:
    """第 15 闸（2026-09-24 对标轮四 6-E/7-B）：隔离桩全集 + 判据覆盖对账。

    桩是「测裁判的裁判」。接线前实测：`[GATE:stub-fail]` 长期存在而提交照过
    （R3 D-13 预言，本轮 C25 真红镜像第二次实证）——故本闸入链。
    桩失败通常意味着**判据真红**（夹具直接跑真实 check_*），修判据而非修桩。
    """
    r = _run([PY, os.path.join("eval", "gate_stub_runner.py")])
    sys.stdout.write(r.stdout[-2500:])
    sys.stderr.write(r.stderr[-800:])
    return r.returncode == 0


def check_push_health() -> bool:
    """第 16 闸（对标轮六 D-39）：本地领先远端的提交数。

    自动推送钩子写的是 `git push ... >/dev/null 2>&1 || true`，失败结构上不可见；
    今晚实测 GM 仓一次提交落地后推送撞车、本地领先 1 个提交而全场无提示。
    本仓「破坏性操作有 Git 兜底」的前提是**远端真有一份**，故把领先数变成每次提交都量的数：
    1~2 个只警告（可能是临时断网），≥3 个判红（备份链已断，先 push 再堆提交）。
    """
    sys.path.insert(0, os.path.join(ROOT, "eval"))
    try:
        import push_health
    except Exception as e:  # noqa: BLE001
        print("[push-health] 判据不可用（%s）⇒ 不以此拦正常提交" % e)
        return True
    verdict, msg = push_health.judge(push_health.ahead_count())
    print("[push-health] %s: %s" % (verdict, msg))
    # D-121 的消费端补线：回执读数原先只在 `python eval/push_health.py` 手工跑时出现，
    # 本闸走的是 in-process 的 judge()，等于"状态文件有人写、没人读"（D-61 族自照）。
    try:
        ci_verdict, ci_msg = push_health.ci_state_health()
        print("[push-health] CI 回执（advisory）%s: %s" % (ci_verdict, ci_msg))
    except Exception as e:  # noqa: BLE001 — advisory 取不到数不得影响本闸判定
        print("[push-health] CI 回执（advisory）UNVERIFIED：%r" % (e,))
    return verdict != "fail"


def check_control_chars() -> bool:
    """第 17 闸（对标轮十六 D-89）：跟踪文本面里的控制字符。

    一手病灶：`eval/wiring_census.py:64` 的 `r"\\b"` 被写成真退格符 0x08，import 半边正则
    永不成立 ⇒ 接线棘轮连续误报 4 个判据未接线，而前 16 道闸没有一道看得见这个字节。
    本闸首跑实测：面 762 个跟踪文本件，修复后 0 命中、修复前 1 命中（误报率 0，符合
    「新指标先量误报率再接线」）。面塌了判 FAIL-FAST 而不是"零违规"（R247）。
    """
    r = _run([PY, os.path.join("eval", "control_char_lock.py")], timeout=60)
    sys.stdout.write(r.stdout[-2500:])
    sys.stderr.write(r.stderr[-800:])
    if r.returncode == 0:
        return True
    note_foreign_inflight("control-char-lock")
    return False


def check_static_locks() -> bool:
    """第 18 闸（对标轮十七 D-98 / 轮十八 D-112、D-114）：把 CI-only 静态锁在本地也跑一遍。

    为什么要有这把闸（一手）：对账 CI `--expect` 名单与本地 GATES 曾发现 19 条 slug 里
    **11 条本地不跑**；而 CI 自 2026-09-25T06:57:56Z 起连红 20+ 次、job `steps=0`。
    这 11 条在那段时间里**零约束**，其中 `path-hygiene` 真的红了两个多小时
    （12 个文件的新增盘符字面量）没有任何人看见 —— 本闸就是那次的直接后果。
    CI 为什么红见 `eval/ci_block_reason.py`（D-113）：不是配额，是账号计费/支出上限。

    收录口径（三条同时成立才进来，避免把本地拖成第二个 CI）：
      ① 本身在 CI `--expect` 阻断名单里（本地不发明判据）；
      ② 工作树语义自洽 —— 不依赖 CI 产物目录、不依赖外盘可达性；
      ③ 实测当前全绿且单把 <1s（整闸实测 3s 内）。
    现收录七把：`path-hygiene` / `part-size` / `wiring-census` / `claim-count --staged` /
    `budget-lock` / `portability --check` / `release-notes`。
    仍留在 CI 档的五条各有硬理由：`attribution` 读 CI 产物目录（本地必假红）、
    `adversarial`/`historical`/`negative`/`portability-diff` 要跑模型或真资产；
    它们的行为已在干净 Linux 容器里复现过，**远端 `steps>0` 的回执仍待 runner 恢复后补验**。
    """
    locks = [("path-hygiene", [os.path.join("eval", "path_hygiene.py")]),
             ("part-size", [os.path.join("eval", "part_size_lock.py")]),
             ("wiring-census", [os.path.join("eval", "wiring_census.py")]),
             ("claim-count-staged", [os.path.join("eval", "claim_count_lock.py"), "--staged"]),
             # D-112：本轮在容器里实测这两把也全绿，且各自 <0.5s ⇒ 一并镜像
             ("budget-lock", [os.path.join("eval", "budget_ceiling_lock.py")]),
             ("portability-consistency", [os.path.join("eval", "portability_ratchet.py"),
                                          "--check"]),
             # D-114：发布面可引用锁（轮十八新增，直接双侧接线，不留"只造轮子不接线"）
             ("release-notes", [os.path.join("eval", "release_notes_lock.py")])]
    bad = []
    for name, args in locks:
        r = _run([PY] + args, timeout=90)
        first = (r.stdout or "").strip().splitlines()
        print("[static-locks] %-17s rc=%d %s" % (name, r.returncode,
                                                 (first[0][:96] if first else "(无输出)")))
        if r.returncode != 0:
            bad.append(name)
            sys.stdout.write((r.stdout or "")[-1200:])
            sys.stderr.write((r.stderr or "")[-400:])
    if bad:
        print("static-locks FAIL: %s（这七条同为 CI --expect 阻断项）" % ", ".join(bad))
        note_foreign_inflight("static-locks")
        return False
    return True


# 权威清单：闸名与顺序的唯一表达点（消费方 = main() / hook 派生文案 / 自测断言）。
# 新增闸必须在此追加并同步模块 docstring 编号；eval/tests/test_pre_commit_gates.py 拦漂移。
GATES = [("truth-consistency", check_truth), ("secret-scan", check_secrets),
         ("pytest", check_pytest), ("junction-health", check_junctions),
         ("direct-map-guard", check_direct_map_dir), ("duplicate-live-guard", check_duplicates),
         ("derived-indexes", check_derived_indexes),
         ("style-ratchet", check_style_ratchet),
         ("retire-reconcile", check_retire_reconcile),
         ("index-refs", check_index_refs),
         ("path-index-due", check_path_index_due),
         ("split-tool-selftest", check_split_tool_selftest),
         ("skill-onboarding-audit", check_skill_onboarding_audit),
         ("tdd-gate", check_tdd_gate),
         ("gate-stubs", check_gate_stubs),
         ("push-health", check_push_health),
         ("control-char-lock", check_control_chars),
         ("static-locks", check_static_locks)]

GATE_NAMES = [name for name, _fn in GATES]


def main() -> int:
    failed = []
    for name, fn in GATES:
        print(f"=== [{name}] ===")
        if not fn():
            failed.append(name)
    if failed:
        print(f"pre-commit FAIL: {', '.join(failed)}")
        return 1
    # 数字派生自 GATES，禁静态抄写（D-21）；「GATES-COUNT:」行由 .git/hooks/pre-commit 读取回显
    print("pre-commit PASS: " + " + ".join(GATE_NAMES) + " 全部通过")
    print("GATES-COUNT: %d" % len(GATES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
