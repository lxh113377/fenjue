#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate_stub_runner.py — 判据隔离桩统一复跑器（R272 建议 C 机器化落地）

把「新增判据必须附隔离桩」从**规则**升级为**可机检**：
  ① 复跑 eval/stubs/registry.json 登记的全部隔离桩（要求 N/N 全过、且 N>0）
  ② 覆盖检查：现存判据面（verify 的 C 项 id + lessons_fingerprints 的 check type）
     中，既不在 baseline_unstubbed 豁免表、又没有被任何桩覆盖的 → 报「未登记桩」

可复用性标准（见 A-get-memory Step 2.7）：下一个会话不做任何事，本检查仍生效。

用法:
  python eval/gate_stub_runner.py            # 人读版
  python eval/gate_stub_runner.py --json     # 机器读版

退出码: 0 = 全过；1 = 有桩失败 或 有未登记判据
"""
import json
import os
import re
import subprocess
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
STUBS_DIR = os.path.join(EVAL_DIR, 'stubs')
REGISTRY = os.path.join(STUBS_DIR, 'registry.json')
VERIFY = os.path.join(EVAL_DIR, 'verify_truth_consistency.py')
FP = os.path.join(EVAL_DIR, 'lessons_fingerprints.json')


def load_registry():
    with open(REGISTRY, encoding='utf-8') as f:
        return json.load(f)


def collect_judges():
    """现存判据面：verify 的 C 项 id + fingerprints 的 check type + 体量治理的五层。

    第三源（2026-09-26 补）：A-project-handoff 的 volumegov.LAYER_NAMES。它不在前两个
    分母里，意味着**新增一层不补桩，runner 永远不知道有人欠账** —— 体量判据带着 92 项
    断言却零门禁复跑，正是这么漏掉的。取不到技能根 ⇒ 记 WARN 并显式说明，不静默少算分母
    （分母少了 = 假绿；本仓 R247 同源：零命中不得记通过）。
    """
    checks = set()
    if os.path.exists(VERIFY):
        with open(VERIFY, encoding='utf-8') as f:
            checks = set(re.findall(r"\('(C\d+)',", f.read()))
    types = set()
    if os.path.exists(FP):
        with open(FP, encoding='utf-8') as f:
            types = set(re.findall(r'"type"\s*:\s*"([a-z_]+)"', f.read()))
    for layer in volume_layers():
        checks.add(layer)
    return checks, types


def skills_scripts_dir():
    """技能根的 `A-project-handoff/scripts` 目录（解析不到返回 ''）。

    单独成函数是为了**可注入**：桩件测试要改的是这一个返回值，而不是去动进程环境变量
    —— 动 env 会跨用例泄漏（实测同文件内后续的真实面测试读到上一个用例的假根，
    L 层因此从分母里掉出去，`covers` 声明反过来被判成幽灵覆盖）。
    """
    if EVAL_DIR not in sys.path:
        sys.path.insert(0, EVAL_DIR)
    try:
        from config import GLOBAL_SKILLS
    except Exception:
        GLOBAL_SKILLS = ''
    root = os.environ.get('FENJUE_SKILLS_DIR') or GLOBAL_SKILLS
    pkg = os.path.join(root, 'A-project-handoff', 'scripts') if root else ''
    return pkg if os.path.isdir(pkg) else ''


def volume_layers():
    """从技能根读 LAYER_NAMES（不写死层名：加一层就该由 runner 追着要桩）。

    机器字面量走 `config.GLOBAL_SKILLS`（path-hygiene 判据：机器字面量只许住在
    truth_constants 定义点，其它文件读它）。取不到 ⇒ 返回 [] 并显式打印，
    宁可让分母少一层可见地报出来，也不静默当成"没有欠账"。
    """
    pkg = skills_scripts_dir()
    if not pkg:
        print('  ⚠️ 体量治理分母不可达（技能根未挂载）⇒ L 层未计入分母')
        return []
    if pkg not in sys.path:
        sys.path.insert(0, pkg)
    try:
        from handoff_lib import volumegov as vg
    except Exception as e:
        print('  ⚠️ volumegov 导入失败（{0}）⇒ L 层未计入分母'.format(str(e)[:80]))
        return []
    return sorted(vg.LAYER_NAMES)


def run_stub(rel_path):
    """跑单桩：解析末行 `label: N/M`，要求 N==M 且 M>0。"""
    path = os.path.join(EVAL_DIR, rel_path.replace('/', os.sep))
    if not os.path.exists(path):
        return False, '桩文件缺失: %s' % rel_path
    try:
        r = subprocess.run([sys.executable, path], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=900,
                           cwd=PROJECT_DIR)
    except Exception as e:
        return False, '执行异常: %s' % e
    lines = [ln for ln in (r.stdout or '').strip().splitlines() if ln.strip()]
    # 可诊断性（对标轮五，CI 实测痛点）：桩在 ubuntu 上红时，runner 只报 "12/13" 或
    # "未解析到 N/M 汇总（末行=(空)）"，看不出**是哪一例**、也看不出崩溃原因（stderr 被吞）。
    # 失败时把桩自身的 [FAIL] 用例行与 stderr 尾部一并带出——不降低判据，只让红可查。
    fails = [ln.strip() for ln in lines if ln.strip().startswith('[FAIL]')]
    err_tail = ' ;; '.join((r.stderr or '').strip().splitlines()[-2:])[:220]

    def _with_detail(summary, ok):
        if ok:
            return summary
        bits = [summary]
        if fails:
            bits.append('失败例: ' + ' ;; '.join(c[:70] for c in fails[:3]))
        elif err_tail:
            bits.append('stderr: ' + err_tail)
        return ' | '.join(bits)

    last = lines[-1] if lines else ''
    m = re.search(r':\s*(\d+)/(\d+)', last)
    if not m:
        return (False, _with_detail('未解析到 N/M 汇总（末行=%s，rc=%d）'
                                    % (last[:80] or '(空)', r.returncode), False))
    n, d = int(m.group(1)), int(m.group(2))
    base = last[:100]
    tail = '' if 'rc=' in base else ' (rc=%d)' % r.returncode   # 被包装脚本自带 rc 时不重复打印
    ok = d > 0 and n == d
    return ok, _with_detail(base + tail, ok)


def compute_uncovered(live_checks, live_types, base_checks, base_types, stubs):
    """覆盖检查（可测纯函数，R272 补全）。

    返回 (uncovered, covered, ghost)：
      covered  = 各桩 `covers` 字段声明的判据 id/type 并集（**显式声明，禁靠猜**）
      uncovered= 现存判据中「既不在豁免表、又无桩声明覆盖」者
      ghost    = 桩声明覆盖了**不存在的判据**（防用假覆盖骗过门禁）

    ⚠️ 2026-09-23 修复：原实现 `uncovered = [c for c in live_checks if c not in base_checks]`
    完全没看桩 —— 意味着**新增判据永远无法通过**（只能塞进明令禁止的豁免表），
    registry `_note` 写的「被任何桩覆盖」这半条判据根本没落地（R263 同族：判据与实现不同构）。
    边界（R247）：`covers` 缺失 / 空 / 非字符串 → 该桩**不覆盖任何判据**，不得静默视为全覆盖。
    """
    covered = set()
    for s in (stubs or []):
        for c in (s.get('covers') or []):
            if isinstance(c, str) and c.strip():
                covered.add(c.strip())
    known = set(live_checks) | set(live_types)
    uncovered = sorted([c for c in live_checks if c not in base_checks and c not in covered]
                       + [t for t in live_types if t not in base_types and t not in covered])
    ghost = sorted(c for c in covered if c not in known)
    return uncovered, sorted(covered), ghost


def main():
    as_json = '--json' in sys.argv
    reg = load_registry()
    stubs = reg.get('stubs', [])
    base = reg.get('baseline_unstubbed', {})
    base_checks = set(base.get('verify_checks', []))
    base_types = set(base.get('fingerprint_checks', []))

    results = []
    fails = 0
    for s in stubs:
        ok, detail = run_stub(s.get('file', ''))
        if not ok:
            fails += 1
        results.append({'id': s.get('id'), 'judge': s.get('judge'),
                        'file': s.get('file'), 'ok': ok, 'detail': detail})

    # 覆盖检查：新增判据必须登记桩（豁免表只装历史判据，机器无法验证"人工没改豁免表"→ 输出条数自证）
    live_checks, live_types = collect_judges()
    uncovered, covered, ghost = compute_uncovered(
        live_checks, live_types, base_checks, base_types, stubs)

    if as_json:
        print(json.dumps({'schema': 'fenjue-gate-stub-runner-v1',
                          'stubs': results, 'stub_fails': fails,
                          'uncovered': uncovered, 'covered': covered, 'ghost_covers': ghost,
                          'baseline_checks': sorted(base_checks),
                          'baseline_types': sorted(base_types),
                          'live_checks': sorted(live_checks),
                          'live_types': sorted(live_types),
                          'all_pass': fails == 0 and not uncovered and not ghost},
                         ensure_ascii=False, indent=1))
    else:
        print('=' * 70)
        print('gate_stub_runner — 判据隔离桩统一复跑（R272）')
        print('=' * 70)
        for r in results:
            print('  [%s] %-20s %s' % ('OK  ' if r['ok'] else 'FAIL', r['id'], r['detail']))
        print('-' * 70)
        print('覆盖检查: 现存判据 verify C 项 %d / fingerprint check type %d | 豁免 %d+%d | 桩覆盖 %d | 未登记桩 %d'
              % (len(live_checks), len(live_types), len(base_checks), len(base_types),
                 len(covered), len(uncovered)))
        if covered:
            print('  桩声明覆盖（covers）: %s' % ', '.join(covered))
        if uncovered:
            print('  未登记桩的判据（新增判据必须补桩并登记 registry.json）: %s' % ', '.join(uncovered))
        if ghost:
            print('  ⚠️ 幽灵覆盖（桩声明了不存在的判据，防假覆盖）: %s' % ', '.join(ghost))
        print('  注: 豁免表冻结于 %s，**新增判据禁止加入豁免表**；新判据请用桩的 covers 字段声明覆盖'
              % reg.get('_updated', '?'))
        print('=' * 70)

    bad_all = bool(uncovered) or bool(ghost)
    tag = '[GATE:stub-pass]' if (fails == 0 and not bad_all) else '[GATE:stub-fail]'
    print(tag)
    if fails or bad_all:
        print('FAIL 桩失败 %d 个 / 未登记判据 %d 个 / 幽灵覆盖 %d 个'
              % (fails, len(uncovered), len(ghost)))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
