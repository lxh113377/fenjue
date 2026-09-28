#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install_hooks.py — 三受管仓的 git 钩子「装上 / 体检 / 修复」唯一入口（对标轮七 D-50）。

为什么需要（一手实测）：
  `.git/hooks/*` **不被 git 跟踪**，所以"版本化副本 + 换机重装"这句话此前只存在于钩子头部的
  手写注释里（`eval/hooks/post-commit:11` 的 `cp ... && chmod +x ...`），全仓没有任何安装器；
  而 P0-32 的提交说明写着「三仓已重实装」，实测焚诀本机 `.git/hooks/post-commit` 里
  `PUSH_ATTEMPTS` 出现 **0 次**，而 HEAD 那份版本化副本里出现 2 次 —— 声明与磁盘不符，
  且这类"装了什么"的漂移**从来没有判据**。同行做法：beads `make install` → `git config
  core.hooksPath .githooks`（钩子全量跟踪）、openclaw `npm prepare` → 幂等四态判定。

口径：
  - 源 = 仓内**版本化副本**（工作树文件），目标 = `<repo>/.git/hooks/<name>`；
  - 目标已存在且内容不同 → 判 `drift`，`--install` 先落 `.bak-<时间戳>` 再覆写，
    并**原样保留** IDE 注入的 tracker 段（`# BEGIN/END Qoder AI tracker` 之间）接在后面；
  - 源有未提交改动 → 拒绝安装（禁止把他人/别处未入库的中间态装进本机钩子）；
  - global_skills 用 `core.hooksPath=hooks`（钩子本体已跟踪），只核"配置在不在 + 文件在不在"，不复制。

退出码：0 = 全部 ok；1 = 有 missing/drift/blocked；2 = 环境不满足（非 git 仓）。
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, 'eval'))

import truth_constants as t  # noqa: E402

TRACKER_RE = re.compile(r'^# BEGIN Qoder AI tracker.*?^# END Qoder AI tracker.*$',
                        re.DOTALL | re.MULTILINE)

# (仓名, 仓根, [(钩子名, 版本化副本相对路径)])；GS 走 hooksPath，单列
REPOS = [
    ("fenjue", REPO_ROOT, [("pre-commit", "eval/hooks/pre-commit"),
                          ("post-commit", "eval/hooks/post-commit"),
                          ("pre-push", "eval/hooks/pre-push")]),
    ("global_memory", t.GLOBAL_MEMORY_ROOT, [("pre-commit", "scripts/hooks/pre-commit")]),
]
HOOKS_PATH_REPOS = [("global_skills", t.GLOBAL_SKILLS_ROOT, "hooks", "pre-commit")]


def _git(repo, *args):
    return subprocess.run(['git', '-C', repo] + list(args), capture_output=True,
                          text=True, encoding='utf-8', errors='replace')


def _tracker_tail(target_path):
    """从已装钩子里抽出 IDE tracker 段（换机/重装不得把宿主的追踪段弄丢）。"""
    if not os.path.isfile(target_path):
        return ''
    body = open(target_path, encoding='utf-8', errors='replace').read()
    m = TRACKER_RE.search(body)
    return ('\n' + m.group(0) + '\n') if m else ''


def _dirty(repo, rel):
    return _git(repo, 'status', '--porcelain', '--', rel).stdout.strip() != ''


def check(install=False, quiet=False):
    """返回 (rows, rc)。rows = (仓, 钩子, 状态, 说明)。"""
    rows = []
    for name, root, hooks in REPOS:
        if not os.path.isdir(os.path.join(root, '.git')):
            rows.append((name, '-', 'no-repo', f'{root}/.git 不存在'))
            continue
        for hook, rel in hooks:
            src = os.path.join(root, *rel.split('/'))
            dst = os.path.join(root, '.git', 'hooks', hook)
            if not os.path.isfile(src):
                rows.append((name, hook, 'missing-src', f'版本化副本不存在: {rel}'))
                continue
            source = open(src, 'rb').read()
            installed = open(dst, 'rb').read() if os.path.isfile(dst) else None
            same = installed is not None and _strip_tracker(installed) == _strip_tracker(source)
            if same and not _dirty(root, rel):
                rows.append((name, hook, 'ok', '与版本化副本一致'))
                continue
            why = ('源有未提交改动' if _dirty(root, rel) else
                   ('目标未安装' if installed is None else '目标与版本化副本不一致'))
            if not install:
                rows.append((name, hook, 'drift' if installed is not None else 'missing', why))
                continue
            status, note = _install(src, dst, source, root, rel)
            rows.append((name, hook, status, note))
    for name, root, path_cfg, hook in HOOKS_PATH_REPOS:
        cur = _git(root, 'config', '--get', 'core.hooksPath').stdout.strip()
        present = os.path.isfile(os.path.join(root, path_cfg, hook))
        if cur == path_cfg and present:
            rows.append((name, hook, 'ok', f'core.hooksPath={path_cfg}（钩子本体已跟踪）'))
        else:
            rows.append((name, hook, 'drift',
                         f'core.hooksPath={cur or "(未设置)"} 跟踪副本存在={present}'))
    if not quiet:
        width = max(len(r[0]) for r in rows)
        for repo, hook, status, note in rows:
            print(f'  {repo:<{width}} {hook:<12} {status:<11} {note}')
    bad = [r for r in rows if r[2] not in ('ok', 'installed')]
    rc = 2 if any(r[2] == 'no-repo' for r in rows) else (1 if bad else 0)
    return rows, rc


def _strip_tracker(data):
    body = data.decode('utf-8', errors='replace')
    return TRACKER_RE.sub('', body).strip().encode('utf-8')


def _install(src, dst, source, root, rel):
    if _dirty(root, rel):
        return ('blocked', '版本化副本有未提交改动，拒绝安装（先提交该文件）')
    if os.path.isfile(dst):
        bak = dst + '.bak-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        with open(bak, 'wb') as f:
            f.write(open(dst, 'rb').read())
    else:
        bak = None
    body = source + _tracker_tail(dst).encode('utf-8')
    with open(dst, 'wb') as f:
        f.write(body.replace(b'\r\n', b'\n'))
    os.chmod(dst, 0o755)
    return ('installed', f'已装（备份 {os.path.basename(bak) if bak else "无"}）')


def main(argv=None):
    ap = argparse.ArgumentParser(description='三受管仓 git 钩子体检/安装（D-50）')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--check', action='store_true', help='只读体检：ok/missing/drift')
    g.add_argument('--install', action='store_true', help='装到位（先备份，保留 tracker 段）')
    g.add_argument('--doctor', action='store_true', help='体检 + 打印最短修复路径')
    ns = ap.parse_args(argv)
    if ns.doctor:
        rows, rc = check()
        if rc:
            print('  修复: python scripts/install_hooks.py --install'
                  '（会先落 .bak-<时间戳>；源有未提交改动时拒绝安装并点名文件）')
        return rc
    rows, rc = check(install=ns.install)
    return rc


if __name__ == '__main__':
    sys.exit(main())
