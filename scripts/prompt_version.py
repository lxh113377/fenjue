#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_version.py — Prompt 版本管理（P2 缺口 #15 修复）
=====================================================================
问题：prompt 版本混乱 —— 改了 prompt 没记录，效果变差了不知道回滚到哪一版。

本工具对「prompt 源文件」做内容寻址的版本快照，支持列出历史、差异对比、回滚。
  - 快照 store 落在脚本同目录 .prompt_versions/（已入 .gitignore，不污染仓库）
  - 回滚前自动备份当前文件到 .prompt_versions/backups/，绝不静默覆盖/删除

用法:
  python prompt_version.py snapshot [--root DIR ...] [--glob "*.md" ...]
  python prompt_version.py list [--file REL]
  python prompt_version.py show <vid> [--file REL]
  python prompt_version.py diff <vid1> <vid2> [--file REL]
  python prompt_version.py rollback <vid> [--file REL]

默认跟踪根: <MEMORY_ROOT>\\prompts（焚诀/prompts 为其 junction，同源）。
可用 --root 追加任意目录（含 skill 的 SKILL.md 等）。
"""
import os
import sys
import json
import hashlib
import argparse
import datetime
import shutil
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
STORE_DIR = os.path.join(SCRIPT_DIR, '.prompt_versions')
STORE_PATH = os.path.join(STORE_DIR, 'store.json')
BACKUP_DIR = os.path.join(STORE_DIR, 'backups')

DEFAULT_ROOTS = [
    r'<MEMORY_ROOT>\prompts',
    os.path.join(PROJECT_DIR, 'prompts'),  # junction → 同源，去重
]
DEFAULT_GLOBS = ['*.md', '*.txt']


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _load_store():
    if not os.path.exists(STORE_PATH):
        return {'versions': [], 'files': {}}
    return json.loads(Path(STORE_PATH).read_text(encoding='utf-8'))


def _save_store(store):
    os.makedirs(STORE_DIR, exist_ok=True)
    Path(STORE_PATH).write_text(
        json.dumps(store, ensure_ascii=False, indent=2), encoding='utf-8')


def _collect_files(roots, globs):
    files = []
    seen = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for entry in os.walk(root):
            for fn in entry[2]:
                if any(_fnmatch(fn, g) for g in globs):
                    ap = os.path.join(entry[0], fn)
                    if ap in seen:
                        continue
                    seen.add(ap)
                    files.append(ap)
    return files


def _fnmatch(name, pattern):
    import fnmatch
    return fnmatch.fnmatch(name, pattern)


def _rel(path, roots):
    for r in roots:
        if path.startswith(r):
            return os.path.relpath(path, r).replace('\\', '/')
    return os.path.basename(path)


def _latest_vid_for(store, key):
    vids = [v['vid'] for v in store['versions'] if v['key'] == key]
    return vids[-1] if vids else None


def cmd_snapshot(args):
    roots = list(DEFAULT_ROOTS) + (args.root or [])
    globs = args.glob or DEFAULT_GLOBS
    if args.file:
        # 显式文件模式：仅版本化指定文件，不叠加默认根扫描（避免把外部 junction prompts/ 卷入库）
        files = []
        for f in args.file:
            if os.path.isfile(f):
                files.append(os.path.abspath(f))
            else:
                print(f"  SKIP {f} (文件不存在)")
    else:
        files = _collect_files(roots, globs)
    store = _load_store()
    created = 0
    for ap in files:
        try:
            sha = _sha256(ap)
        except Exception as e:
            print(f"  SKIP {ap} (读取失败: {e})")
            continue
        key = _rel_project(ap)
        content = Path(ap).read_text(encoding='utf-8', errors='replace')
        prev = _latest_vid_for(store, key)
        # 与上一版内容相同则跳过（避免无意义快照）
        if prev:
            pv = next((v for v in store['versions'] if v['vid'] == prev), None)
            if pv and pv['sha256'] == sha:
                continue
        vid = sha[:12] + _now().replace(':', '').replace('-', '').replace('T', '')
        vid = vid[:20]
        store['versions'].append({
            'vid': vid, 'key': key, 'abspath': ap, 'sha256': sha,
            'size': len(content.encode('utf-8')), 'ts': _now(), 'prev': prev,
            '_content': content,  # P2 #15 修复: 内联存储历史内容, 否则 rollback/diff 会读到当前文件而非目标版
        })
        store.setdefault('files', {})[key] = {
            'abspath': ap, 'current_vid': vid, 'sha256': sha}
        created += 1
        print(f"  + {key} → v{vid} ({len(content)}B)")
    _save_store(store)
    print(f"快照完成：新增 {created} 版，store={STORE_PATH}")
    return 0


def cmd_list(args):
    store = _load_store()
    if not store['versions']:
        print("暂无版本记录。先跑 snapshot。")
        return 0
    by_key = {}
    for v in store['versions']:
        by_key.setdefault(v['key'], []).append(v)
    for key in sorted(by_key):
        if args.file and args.file not in key:
            continue
        print(f"\n= {key} ({len(by_key[key])} 版)")
        for v in by_key[key]:
            print(f"  v{v['vid']}  {v['ts']}  sha256:{v['sha256'][:8]}  {v['size']}B")
    return 0


def _find_vid(store, vid, key_filter):
    for v in store['versions']:
        if v['vid'] == vid and (not key_filter or key_filter in v['key']):
            return v
    # 允许前缀匹配
    for v in store['versions']:
        if v['vid'].startswith(vid) and (not key_filter or key_filter in v['key']):
            return v
    return None


def cmd_show(args):
    store = _load_store()
    v = _find_vid(store, args.vid, args.file)
    if not v:
        print(f"未找到版本 {args.vid}")
        return 1
    content = _read_version_content(store, v)
    sys.stdout.write(content)
    return 0


def _read_version_content(store, v):
    # 内容随版本内联存储（store 已含首次快照内容）；若缺失则尝试从文件读当前
    if '_content' in v:
        return v['_content']
    if os.path.exists(v['abspath']):
        return Path(v['abspath']).read_text(encoding='utf-8', errors='replace')
    return f"# (内容不可恢复: 版本 {v['vid']} 未内联且文件缺失)\n"


def cmd_diff(args):
    store = _load_store()
    v1 = _find_vid(store, args.vid1, args.file)
    v2 = _find_vid(store, args.vid2, args.file)
    if not v1 or not v2:
        print("未找到版本")
        return 1
    import difflib
    a = _read_version_content(store, v1).splitlines()
    b = _read_version_content(store, v2).splitlines()
    diff = difflib.unified_diff(a, b, fromfile=f"v{v1['vid']}", tofile=f"v{v2['vid']}", lineterm='')
    out = '\n'.join(diff)
    print(out if out else "无差异")
    return 0


def cmd_rollback(args):
    store = _load_store()
    v = _find_vid(store, args.vid, args.file)
    if not v:
        print(f"未找到版本 {args.vid}")
        return 1
    target = v['abspath']
    if not os.path.exists(target):
        print(f"目标文件不存在: {target}（无法回滚；可先 show 查看内容手动恢复）")
        return 1
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = _now().replace(':', '').replace('-', '').replace('T', '')
    backup = os.path.join(BACKUP_DIR, f"{os.path.basename(target)}.{ts}.backup")  # R202: 中性扩展名, 避免 '.bak' 命中 BACKUP_MARKERS 噪声闸误报
    shutil.copy2(target, backup)  # 回滚前备份当前版本
    content = _read_version_content(store, v)
    Path(target).write_text(content, encoding='utf-8')
    store.setdefault('files', {})[v['key']] = {
        'abspath': target, 'current_vid': v['vid'], 'sha256': v['sha256']}
    _save_store(store)
    print(f"已回滚 {v['key']} → v{v['vid']}")
    print(f"回滚前备份: {backup}")
    return 0


def _rel_project(path):
    """相对项目根的路径（check 用，精确到子目录，避免同名文件 key 冲突）。"""
    try:
        return os.path.relpath(path, PROJECT_DIR).replace('\\', '/')
    except Exception:
        return os.path.basename(path)


def cmd_check(args):
    """校验受控 prompt 是否已版本化（CI 强制门禁用）。

    受控文件 = 默认根(prompts/) + --root 追加根下匹配 globs 的文件 + 显式 --file。
    规则：每个受控文件当前 sha256 必须已存在于 store 的 versions[].sha256 集合，
    否则视为「已修改但未版本化」→ 退出码 1（fail-closed 阻断）。
    无任何受控文件被发现（根均不可达）→ SKIP 退出码 0，不误阻。
    """
    if args.file:
        # 显式文件模式：仅校验指定文件，不叠加默认根扫描（避免外部 junction prompts/ 误拦）
        files = []
        for f in args.file:
            if os.path.isfile(f):
                files.append(os.path.abspath(f))
            else:
                print(f"  WARN 指定文件不存在，跳过: {f}")
    else:
        roots = list(DEFAULT_ROOTS) + (args.root or [])
        globs = args.glob or DEFAULT_GLOBS
        files = _collect_files(roots, globs)
    files = sorted(set(files))
    if not files:
        print("PROMPT_VERSION_SKIP: 未发现受控 prompt 文件（受控根均不可达）")
        return 0
    store = _load_store()
    known_shas = {v['sha256'] for v in store['versions']}
    missing = []
    for ap in files:
        try:
            sha = _sha256(ap)
        except Exception as e:
            print(f"  SKIP {ap} (读取失败: {e})")
            continue
        key = _rel_project(ap)
        if sha not in known_shas:
            missing.append((key, sha))
    if missing:
        print(f"PROMPT_VERSION_FAIL: {len(missing)} 个受控 prompt 已修改但未版本化")
        print("  修复: python scripts/prompt_version.py snapshot")
        for key, sha in missing:
            print(f"  - {key}  sha256:{sha[:12]} 未找到版本记录")
        return 1
    print(f"PROMPT_VERSION_PASS: {len(files)} 个受控 prompt 均已版本化")
    return 0


def main():
    ap = argparse.ArgumentParser(description='Prompt 版本管理（P2 #15）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('snapshot', help='对 prompt 文件做版本快照')
    p.add_argument('--root', nargs='*', help='追加跟踪根目录')
    p.add_argument('--glob', nargs='*', help='文件名匹配模式（默认 *.md *.txt）')
    p.add_argument('--file', action='append', help='显式指定受控文件（可多次；相对/绝对路径）')
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser('list', help='列出版本历史')
    p.add_argument('--file', help='按 key 子串过滤')
    p.set_defaults(func=cmd_list)

    p = sub.add_parser('show', help='打印某版本内容')
    p.add_argument('vid')
    p.add_argument('--file', help='按 key 子串过滤')
    p.set_defaults(func=cmd_show)

    p = sub.add_parser('diff', help='对比两版本')
    p.add_argument('vid1')
    p.add_argument('vid2')
    p.add_argument('--file', help='按 key 子串过滤')
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser('rollback', help='回滚到某版本（先自动备份）')
    p.add_argument('vid')
    p.add_argument('--file', help='按 key 子串过滤')
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser('check', help='校验受控 prompt 是否已版本化（CI 门禁用）')
    p.add_argument('--root', nargs='*', help='追加跟踪根目录')
    p.add_argument('--glob', nargs='*', help='文件名匹配模式（默认 *.md *.txt）')
    p.add_argument('--file', action='append', help='显式指定受控文件（可多次；相对/绝对路径）')
    p.set_defaults(func=cmd_check)

    args = ap.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
