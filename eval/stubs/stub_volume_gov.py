#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：A-project-handoff 体量治理判据（volume 五层 + 四道处置护栏 + 心跳自证）

判据面：volumegov.py 的 L1~L5 分层、auto_layers 白名单、L3 缓存双条件、单轮字节/件数帽、
        处置锁、账本 caplock、跨 schema 环比、在册治理任务清单、无人值守心跳龄期。
隔离手法：本体不造夹具 —— 转调技能自带的 `volume_gov_stub.py`（92 项断言，夹具一律建在
        系统临时目录），本包装只负责三件事：① 定位技能根 ② 取退出码 ③ 把 N/M 汇总行
        透传给 gate_stub_runner。

**取不到技能根 / 跑不起来 = FAIL，绝不记 SKIP**：把"外部不可达"读成"通过"是本仓
反复判红的形态（对照 `ci.yml` 的 routing-health SKIP 保绿 —— 镜像未挂载时它在公开
CI 上恒为 no-op，等于一条从未生效的判据被当成已交付）。
登记：eval/stubs/registry.json → id=VOLUME-gov, covers=[L1..L5]
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
PROJ = os.path.dirname(EVAL)
INNER = 'A-project-handoff/scripts/volume_gov_stub.py'
SUMMARY_RE = re.compile(r'^volume_gov_stub:\s*(\d+)/(\d+)\s*$')


def skill_roots():
    """技能根候选：项目 path_index 声明的 junction > 环境变量 > 焚诀同级目录。

    写死单一绝对路径 = 换机即失效（C23 同类教训）；但**一个都取不到时不猜、直接 FAIL**。
    """
    out = []
    idx = os.path.join(PROJ, 'eval', 'path_index_roots.json')
    if os.path.exists(idx):
        try:
            with open(idx, encoding='utf-8') as f:
                for p in json.load(f).get('skill_roots', []):
                    out.append(p)
        except (ValueError, OSError):
            pass
    env = os.environ.get('FENJUE_SKILLS_DIR')
    if env:
        # 显式覆盖 = 显式指定被测对象：**不再回落到别的树**。否则 override 写错时
        # 桩会默默去跑另一棵树，报一个"看着是绿的、量的却是别的对象"的结果
        # —— 与被测对象搞错，比直接 FAIL 危险得多。
        return [env]
    # 机器字面量走 config.GLOBAL_SKILLS（path-hygiene：字面量只许住 truth_constants）
    sys.path.insert(0, os.path.dirname(HERE))
    try:
        from config import GLOBAL_SKILLS
        out.append(GLOBAL_SKILLS)
    except Exception:
        pass
    out.append(os.path.join(os.path.dirname(PROJ), 'skill焚诀'))
    return [p for p in out if p]


def locate():
    for root in skill_roots():
        cand = os.path.join(root, *INNER.split('/'))
        if os.path.exists(cand):
            return cand, root
    return None, None


def main():
    path, root = locate()
    if not path:
        print('❌ 体量治理桩不可达 ⇒ 判 FAIL，不记 SKIP（不可达 ≠ 通过）。查过这些根: {0}'.format(
            ' | '.join(skill_roots())))
        print('volume_gov_stub: 0/1')
        print('[GATE:volume-gov-fail] 判据面未执行')
        return 1
    try:
        r = subprocess.run([sys.executable, path], capture_output=True, text=True,
                           encoding='utf-8', errors='replace',
                           # 实测内层桩 16s；预算取 110s（< 默认链天花板 120s，budget-lock
                           # 判据）。抬 timeout 掩盖慢是禁止的——慢就减量，不放宽天花板
                           timeout=110,
                           cwd=os.path.dirname(os.path.dirname(path)))
    except Exception as e:
        print('❌ 执行异常: {0} ⇒ FAIL（跑不起来不等于通过）'.format(e))
        print('volume_gov_stub: 0/1')
        return 1
    lines = [ln for ln in (r.stdout or '').splitlines() if ln.strip()]
    tail = [ln for ln in lines if SUMMARY_RE.match(ln.strip())]
    m = SUMMARY_RE.match(tail[-1].strip()) if tail else None
    if not m:
        print('❌ 内层桩未产出 N/M 汇总行 ⇒ FAIL（rc={0}）'.format(r.returncode))
        for ln in lines[-5:]:
            print('   | {0}'.format(ln[:160]))
        if r.stderr:
            print('   stderr: {0}'.format(r.stderr.strip()[:300]))
        print('volume_gov_stub: 0/1')
        return 1
    n, d = int(m.group(1)), int(m.group(2))
    for ln in lines:
        if ln.startswith('❌'):
            print(ln[:200])
    print('技能根: {0}'.format(root))
    ok = d > 0 and n == d and r.returncode == 0
    print('[GATE:volume-gov-{0}] {1} 项断言（含反例/变异体）'.format(
        'pass' if ok else 'fail', d))
    # N/M 汇总必须是**末行**：gate_stub_runner.run_stub 只解析 lines[-1] 的 `label: N/M`
    # （实测把 GATE 行放在后面就直接 FAIL —— 包装既有判据先读它的解析口径）
    print('volume_gov_stub: {0}/{1} (rc={2})'.format(n if ok else min(n, d - 1), d,
                                                     r.returncode))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
