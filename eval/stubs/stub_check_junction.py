#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩：scripts/check_junction.ps1 的 ③ HM 逐技能 junction 扫描判据（R272，2026-09-23）

被包装对象：`scripts/check_junction.ps1`（2026-09-23 新增 ③ 段 + 五端 Known 表补全）
三要素：
  正例       = 逐技能 junction 全部可达            → exit 0，扫描计数可见
  违规样本-a = 1 条断链 junction（目标被删）        → exit 1 且报出该条（判据非恒真）
  违规样本-b = 实体目录冒充 junction                → exit 1 且报 MISMATCH
  边界-a     = 根存在但为空                        → exit 0 且显式打印「扫描 0 个」（非静默 PASS，R247）
  边界-b     = 根不存在                            → exit 0 但打印 WARN「不可信」（不得静默 PASS）

隔离手法：`-SkipKnownTable` 跳过 ① 真实机挂载表 + `-Roots @()` 关掉 ② 动态扫描，
夹具建在 %TEMP%（受管根之外），跑后清理（链接先 rmdir，再删临时树）。

登记：eval/stubs/registry.json → id=JUNCTION-hm-skills
"""
import os
import shutil
import subprocess
import sys
import tempfile

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PS1 = os.path.join(PROJECT_DIR, 'scripts', 'check_junction.ps1')

PASS = []


def say(ok, label, extra=''):
    PASS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', label, (' | ' + extra) if extra else ''))


def run_ps(fixture):
    """-SkipKnownTable + -Roots @()：夹具自足，不依赖本机真实挂载。"""
    cmd = "& '%s' -SkipKnownTable -Roots @() -HermesSkillsRoot '%s'" % (PS1, fixture)
    r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def mklink(link, target):
    return subprocess.run(['cmd', '/c', 'mklink', '/J', link, target],
                          capture_output=True, text=True, encoding='utf-8', errors='replace')


def rmdir(path):
    # 只删链接本身 / 空目录，不递归目标内容
    subprocess.run(['cmd', '/c', 'rmdir', '/q', path], capture_output=True,
                   text=True, encoding='utf-8', errors='replace')


def main():
    if not os.path.exists(PS1):
        print('被包装脚本缺失: %s' % PS1)
        print('stub_check_junction: 0/1')
        return 1

    base = tempfile.mkdtemp(prefix='fenjue_junction_stub_')
    links = []
    try:
        # ---- 正例 ----
        ok_root = os.path.join(base, 'ok')
        real = os.path.join(base, 'real_skill')
        os.makedirs(real)
        open(os.path.join(real, 'SKILL.md'), 'w', encoding='utf-8').write('# demo\n')
        os.makedirs(ok_root)
        rc, out = run_ps(ok_root)
        # 空夹具先走边界-a（正例留到有真实链接时再断言）
        say(rc == 0 and '扫描 0 个' in out and 'WARN' not in out,
            '边界-a 空根: exit 0 且显式打印扫描数（非静默 PASS）', 'rc=%d' % rc)

        l1 = os.path.join(ok_root, 'good-skill')
        mklink(l1, real)
        links.append(l1)
        rc, out = run_ps(ok_root)
        say(rc == 0 and '扫描 1 个' in out and '[FAIL]' not in out,
            '正例 可达 junction: exit 0 无异常', 'rc=%d' % rc)

        # ---- 违规样本-a：断链（先建链接再删目标，制造 dangling）----
        dang_root = os.path.join(base, 'dangling')
        tmp_real = os.path.join(base, 'real_tmp')
        os.makedirs(tmp_real)
        os.makedirs(dang_root)
        l2 = os.path.join(dang_root, 'ghost-skill')
        mklink(l2, tmp_real)
        links.append(l2)
        rmdir(tmp_real)          # 目标消失 → 链接成为断链
        rc, out = run_ps(dang_root)
        say(rc == 1 and 'ghost-skill' in out and '目标不可达' in out,
            '违规样本-a 断链 junction: exit 1 且点名报出', 'rc=%d' % rc)

        # ---- 违规样本-b：实体目录冒充 junction ----
        plain_root = os.path.join(base, 'plain')
        os.makedirs(os.path.join(plain_root, 'not-a-junction'))
        rc, out = run_ps(plain_root)
        say(rc == 1 and '不是 ReparsePoint' in out,
            '违规样本-b 实体目录: exit 1 且报 MISMATCH', 'rc=%d' % rc)

        # ---- 边界-b：根不存在 ----
        rc, out = run_ps(os.path.join(base, 'no_such_root'))
        say(rc == 0 and '[WARN]' in out and '不可信' in out,
            '边界-b 根不存在: exit 0 但显式 WARN 不可信', 'rc=%d' % rc)
    finally:
        for ln in links:
            if os.path.exists(ln) or os.path.islink(ln):
                rmdir(ln)
        shutil.rmtree(base, ignore_errors=True)

    n, d = sum(1 for x in PASS if x), len(PASS)
    print('stub_check_junction: %d/%d' % (n, d))
    return 0 if (d > 0 and n == d) else 1


if __name__ == '__main__':
    sys.exit(main())
