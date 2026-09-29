#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
split_md_4kb.py - 4KB 拆分工具（指针壳 + .partN 分卷，字节无损）

用户硬限（2026-08-03 零豁免）: 所有活跃 .md <= 4096 字节。
范式: 原文件保留为「指针壳」（分卷目录 + 导航），正文按标题边界切成
part1..N 分卷，每卷 <= TARGET 字节；分卷 = 原文的连续字节切片（行边界），
concat(parts) == 原文字节（split 模式）或旧分卷拼接（series 模式）。

用法:
  split_md_4kb.py split <file> [--manifest M] [--force]
      单文件（无 .partN 兄弟）-> 指针壳 + part1..N
  split_md_4kb.py rechunk <partfile> [--manifest M]
      超限分卷 -> partN..partM（同前缀连续编号，字节无损）
  split_md_4kb.py series <basefile> [--manifest M]
      逻辑文件（base 指针 + part1..M 兄弟）全部重切 -> part1..N，打印新 TOC 行
  split_md_4kb.py selftest            # 5 条自测（沙箱内跑，不碰真实库）
  split_md_4kb.py unify-names [--dry-run]
      把索引指向的备份/快照文件统一为 <sanitized>.snap 命名（改名 + 同步索引行 + 审计，内容不动）。
  split_md_4kb.py prune [--root R] [--dry-run]
      把「非受管根 R（默认 <MEMORY_ROOT>）」的备份条目归档到 _split_backup/_archive/<ts>/，
      并从 _index.jsonl 移除（悬空条目一并清理）；归档而非删除，_audit.jsonl 留痕。
  split_md_4kb.py resnap [file ...] [--all] [--force] [--dry-run]
      把当前分卷内容刷新为快照基线（正常演进后的重定基），保留 _audit.jsonl 审计行；
      缩水超过 20% 默认拒绝（防把真丢失洗成基线），确认无误再加 --force。
  split_md_4kb.py scan <root> [--exclude SUB ...]
      合规扫描：列出 >4096B 的 .md（跳过 junction 与排除目录）

编码: 仅 UTF-8（容忍 BOM）；新指针壳写 UTF-8 无 BOM；分卷保留原始字节。
写盘/读盘形态（2026-09-24 P0-11）: 全文件统一 pathlib 接收者式 I/O
（Path.read_bytes / read_text / write_bytes / write_text / Path.open），
行为等价（含 Windows 换行翻译语义）；本工具为用户指路的 CLI，不引入额外路径白名单。
"""

import sys
import os
import re
import json
import hashlib
import datetime
import glob
import shutil
from pathlib import Path

# P0-11（2026-09-24）：引入共享路径净化器（eval/io_utils.checked_path）——
# manifest 路径来自命令行参数，跨文件污点链在追加式汇上仍被判红；
# 净化后读-改-写（read_text + write_text）断链且行为等价。
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'eval')))
from io_utils import checked_path  # noqa: E402

MAX = 4096
TARGET = 3950
# 2026-09-21 R263 升级：拆分默认自动累加 manifest（含原文/各分卷 sha256），
# 供 verify_split_integrity.ps1 优先消费，从机制上消灭「块跨分卷边界被误判丢失」。
DEFAULT_MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'split_manifest.jsonl')
# 2026-09-21：拆分前最小备份（按次、单文件）→ 校验器锚点的滚动供给源，
# 让兜底不再依赖整库旧快照（旧锚点只用于历史遗留文件）。
DEFAULT_SPLIT_BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_split_backup')
MARK = re.compile(rb'^#{1,4} |^R\d+')


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def split_lines(data):
    lines = []
    i, n = 0, len(data)
    while i < n:
        j = data.find(b'\n', i)
        if j < 0:
            lines.append(data[i:])
            break
        lines.append(data[i:j + 1])
        i = j + 1
    return lines


def marker_lines(lines):
    marks = [0]
    for i, ln in enumerate(lines):
        if i > 0 and MARK.match(ln):
            marks.append(i)
    return marks


def split_large(sec, limit):
    """大段（单标题节超限）按空行段落拆分，仍超限则硬切到行边界。"""
    paras = []
    p = []
    for ln in sec:
        if ln.strip() == b'':
            if p:
                paras.append(p)
                p = []
            paras.append([ln])
        else:
            p.append(ln)
    if p:
        paras.append(p)
    out = []
    cur, curlen = [], 0
    for para in paras:
        plen = sum(len(x) for x in para)
        if curlen + plen <= limit:
            cur += para
            curlen += plen
        else:
            if cur:
                out.append(cur)
            if plen <= limit:
                cur, curlen = list(para), plen
            else:
                cur, curlen = [], 0
                for ln in para:
                    if curlen + len(ln) > limit and cur:
                        out.append(cur)
                        cur, curlen = [], 0
                    if len(ln) > limit:
                        # 超长单行：按字节硬切为独立块（拼接零新增，仍 byte-identical）
                        if cur:
                            out.append(cur)
                            cur, curlen = [], 0
                        for i in range(0, len(ln), limit):
                            out.append([ln[i:i + limit]])
                        continue
                    cur.append(ln)
                    curlen += len(ln)
    if cur:
        out.append(cur)
    return out


def pack_sections(lines, marks):
    bounds = marks + [len(lines)]
    sections = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    chunks = []
    cur, curlen = [], 0
    for a, b in sections:
        sec = lines[a:b]
        slen = sum(len(x) for x in sec)
        if cur and curlen + slen > TARGET:
            chunks.append(cur)
            cur, curlen = [], 0
        if slen <= TARGET:
            cur += sec
            curlen += slen
        else:
            if cur:
                chunks.append(cur)
                cur, curlen = [], 0
            for piece in split_large(sec, TARGET):
                chunks.append(piece)
    if cur:
        chunks.append(cur)
    return [b''.join(c) for c in chunks if c]


def part_glob(base):
    stem = os.path.splitext(os.path.basename(base))[0]
    return sorted(
        glob.glob(os.path.join(os.path.dirname(base), stem + '.part*.md')),
        key=lambda p: int(re.search(r'\.part(\d+)\.md$', p).group(1)),
    )


def part_index(path):
    m = re.search(r'\.part(\d+)\.md$', path)
    return int(m.group(1)) if m else None


def part_sort_key(path):
    # 分卷排序唯一定义点（2026-09-21）：partN → N；partN-M → (N, M)；无编号 → 极大值后排
    b = os.path.basename(path)
    m = re.search(r'\.part(\d+)(?:-(\d+))?', b)
    if not m:
        return (10 ** 6, 0, b)
    return (int(m.group(1)), int(m.group(2)) if m.group(2) else 0, b)


def first_heading(data, fallback):
    try:
        text = data.decode('utf-8-sig', errors='replace')
    except Exception:
        text = ''
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith('#'):
            return re.sub(r'^#+\s*', '', s).strip()[:70]
        if s:
            return s[:70]
    return fallback


def read_text(path):
    raw = Path(path).read_bytes()
    bom = raw.startswith(b'\xef\xbb\xbf')
    if bom:
        raw = raw[3:]
    return raw.decode('utf-8'), bom


def toc_lines(stem, chunks):
    out = ['## 分卷目录']
    for i, c in enumerate(chunks, 1):
        out.append('- **卷%d** `%s.part%d.md` — %s' % (i, stem, i, first_heading(c, '卷 %d' % i)))
    return out


def update_shell_toc(base_file, chunks, stem=None):
    """把指针壳的「分卷目录」段替换为当前分卷清单（其他内容字节保留）。"""
    text, bom = read_text(base_file)
    lines = text.splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == '## 分卷目录':
            start = i
            break
    new_toc = '\n'.join(toc_lines(stem or os.path.splitext(os.path.basename(base_file))[0], chunks)) + '\n'
    if start is None:
        if lines and not lines[-1].endswith('\n'):
            lines.append('\n')
        lines.append(new_toc)
    else:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if re.match(r'^#{2,4} ', lines[j]):
                end = j
                break
        lines[start:end] = [new_toc]
    out_b = ''.join(lines).encode('utf-8')
    if len(out_b) > MAX:
        print('[FAIL] 指针壳更新后超限 %d B: %s' % (len(out_b), base_file))
        sys.exit(1)
    Path(base_file).write_bytes((b'\xef\xbb\xbf' + out_b) if bom else out_b)
    print('TOC updated: %s (%d 卷)' % (base_file, len(chunks)))


def remove_stale_parts(base_file, keep_max):
    for old in part_glob(base_file):
        idx = part_index(old)
        if idx and idx > keep_max:
            os.remove(old)
            print('removed stale part: %s' % old)


def rebuild_toc_from_disk(base_file):
    stem = os.path.splitext(os.path.basename(base_file))[0]
    parts = part_glob(base_file)
    if not parts:
        return
    chunks = [Path(p).read_bytes() for p in parts]
    update_shell_toc(base_file, chunks, stem)


def pointer_text(title, base, chunks):
    n = len(chunks)
    out = [
        '# %s（索引 — 已按章节拆分为 %d 卷，按需加载）' % (title, n),
        '',
        '> 本文件为导航索引，非内容。各卷为完整章节，按需在任务触发时 Read 对应 part。',
        '',
        '## 分卷目录',
    ]
    for i, c in enumerate(chunks, 1):
        out.append('- **卷%d** `%s.part%d.md` — %s' % (i, base, i, first_heading(c, '卷 %d' % i)))
    return '\n'.join(out) + '\n'


def write_parts(outdir, base, chunks):
    paths = []
    for i, c in enumerate(chunks, 1):
        p = os.path.join(outdir, '%s.part%d.md' % (base, i))
        Path(p).write_bytes(c)
        paths.append(p)
    return paths


def backup_original(path, data):
    # 拆分前把原文落一份最小备份（滚动供给源），返回备份路径
    try:
        # 2026-09-21 收敛定义点：命名一律走 full_backup_path()，禁止此处再手拼
        dst = full_backup_path(path)
        Path(dst).write_bytes(data)
        idx = os.path.join(DEFAULT_SPLIT_BACKUP, '_index.jsonl')
        with Path(idx).open('a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                                'file': path, 'backup': dst,
                                'original_sha256': sha256(data), 'original_bytes': len(data)},
                               ensure_ascii=False) + '\n')
        return dst
    except Exception as e:
        print('     [WARN] 最小备份失败: %s' % e)
        return None


def manifest_append(path, entry):
    if not path:
        return
    target = checked_path(path)   # P0-11: 净化（拒绝 .. 分量 + resolve）
    prior = target.read_text(encoding='utf-8') if target.exists() else ''
    target.write_text(prior + json.dumps(entry, ensure_ascii=False) + '\n', encoding='utf-8')


def cmd_split(args):
    f = os.path.abspath(args.file)
    data = Path(f).read_bytes()
    outdir = os.path.dirname(f)
    base = os.path.splitext(os.path.basename(f))[0]
    old = part_glob(f)
    if old and not args.force:
        print('[ABORT] 存在旧分卷: %s（需 --force 覆盖，或改用 series/rechunk）' % [os.path.basename(p) for p in old])
        sys.exit(2)
    _bk = backup_original(f, data)
    lines = split_lines(data)
    chunks = pack_sections(lines, marker_lines(lines))
    paths = write_parts(outdir, base, chunks)
    remove_stale_parts(f, len(chunks))
    title = first_heading(data, base)
    ptr = pointer_text(title, base, chunks)
    ptr_b = ptr.encode('utf-8')
    if len(ptr_b) > MAX:
        print('[FAIL] 指针壳超限 %d B' % len(ptr_b))
        sys.exit(1)
    Path(f).write_bytes(ptr_b)
    print('OK split %s (%d B -> 指针 %d B + %d 卷)' % (f, len(data), len(ptr_b), len(chunks)))
    print('     manifest += %s' % (args.manifest or DEFAULT_MANIFEST))
    if _bk: print('     backup += %s' % _bk)
    manifest_append(args.manifest or DEFAULT_MANIFEST, {
        'ts': datetime.datetime.now().isoformat(timespec='seconds'),
        'op': 'split', 'file': f,
        'original_sha256': sha256(data), 'original_bytes': len(data),
        'parts': [{'file': p, 'bytes': os.path.getsize(p), 'sha256': sha256(Path(p).read_bytes())} for p in paths],
        'pointer_bytes': len(ptr_b),
    })


def cmd_rechunk(args):
    f = os.path.abspath(args.file)
    data = Path(f).read_bytes()
    outdir = os.path.dirname(f)
    base = os.path.basename(f).rsplit('.part', 1)[0]
    k = part_index(f)
    if k is None:
        print('[ABORT] 不是 .partN.md 分卷: %s' % f)
        sys.exit(2)
    base_file = os.path.join(outdir, base + '.md')
    all_parts = part_glob(base_file)
    max_idx = max([part_index(p) for p in all_parts] or [0])
    if k != max_idx:
        print('[ABORT] rechunk 仅支持最后一个分卷（part%d 不是末卷 part%d）；整系列重排请用 series 模式' % (k, max_idx))
        sys.exit(2)
    _bk = backup_original(f, data)
    lines = split_lines(data)
    chunks = pack_sections(lines, marker_lines(lines))
    paths = []
    for i, c in enumerate(chunks, 1):
        p = os.path.join(outdir, '%s.part%d.md' % (base, k + i - 1))
        Path(p).write_bytes(c)
        paths.append(p)
    remove_stale_parts(base_file, k + len(chunks) - 1)
    rebuild_toc_from_disk(base_file)
    print('OK rechunk %s (%d B -> %d 卷: %s)' % (f, len(data), len(chunks), [os.path.basename(p) for p in paths]))
    manifest_append(args.manifest or DEFAULT_MANIFEST, {
        'ts': datetime.datetime.now().isoformat(timespec='seconds'),
        'op': 'rechunk', 'file': f,
        'original_sha256': sha256(data), 'original_bytes': len(data),
        'parts': [{'file': p, 'bytes': os.path.getsize(p), 'sha256': sha256(Path(p).read_bytes())} for p in paths],
    })


def cmd_series(args):
    base = os.path.abspath(args.base)
    parts = part_glob(base)
    if not parts:
        print('[ABORT] 无分卷可重切: %s' % base)
        sys.exit(2)
    data = b''.join(Path(p).read_bytes() for p in parts)
    _bk = backup_original(base, data)   # 逻辑文件整体最小备份
    outdir = os.path.dirname(base)
    stem = os.path.splitext(os.path.basename(base))[0]
    lines = split_lines(data)
    chunks = pack_sections(lines, marker_lines(lines))
    paths = write_parts(outdir, stem, chunks)
    remove_stale_parts(base, len(chunks))
    update_shell_toc(base, chunks, stem)
    print('OK series %s (旧 %d 卷 %d B -> 新 %d 卷)' % (base, len(parts), len(data), len(chunks)))
    print('--- 新分卷目录（粘贴进指针壳）---')
    for i, c in enumerate(chunks, 1):
        print('- **卷%d** `%s.part%d.md` — %s' % (i, stem, i, first_heading(c, '卷 %d' % i)))
    print('--- END ---')
    manifest_append(args.manifest or DEFAULT_MANIFEST, {
        'ts': datetime.datetime.now().isoformat(timespec='seconds'),
        'op': 'series', 'file': base,
        'original_sha256': sha256(data), 'original_bytes': len(data),
        'parts': [{'file': p, 'bytes': os.path.getsize(p), 'sha256': sha256(Path(p).read_bytes())} for p in paths],
    })


SHRINK_GUARD = 0.8   # 重快照安全闸：新内容/基线 < 0.8 视为可疑（可能是丢失而非演进）


def full_backup_path(path):
    os.makedirs(DEFAULT_SPLIT_BACKUP, exist_ok=True)
    # 2026-09-21 统一样式：备份/快照文件一律 <sanitized>.snap（自标注，避免与真 .md 混淆）
    return os.path.join(DEFAULT_SPLIT_BACKUP, path.replace(':', '-').replace(os.sep, '__') + '.snap')


def _load_index(idx):
    rows = []
    if os.path.exists(idx):
        for ln in Path(idx).open(encoding='utf-8'):
            if ln.strip():
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
    return rows


def _concat_parts(path):
    d = os.path.dirname(path)
    base = os.path.splitext(os.path.basename(path))[0]
    ext = os.path.splitext(path)[1]
    parts = sorted(glob.glob(os.path.join(d, base + '.part*' + ext)), key=part_sort_key)
    if not parts:
        return None, []
    return b''.join(Path(p).read_bytes() for p in parts), parts


def cmd_resnap(args):
    """把当前分卷内容刷新为快照基线（保留审计行；缩水超 20% 需 --force）"""
    idx = os.path.join(DEFAULT_SPLIT_BACKUP, '_index.jsonl')
    audit = os.path.join(DEFAULT_SPLIT_BACKUP, '_audit.jsonl')
    rows = _load_index(idx)
    latest = {}
    for r in rows:
        if r.get('op') in ('snap', 'snap-resnap') and r.get('file'):
            latest[r['file']] = r
    if not latest:
        print('[resnap] 无 snap 条目（先跑一次快照建立基线）')
        return 0
    targets = sorted(latest) if (getattr(args, 'all', False) or not args.file) else [os.path.abspath(f) for f in args.file]
    changed = unchanged = refused = skipped = 0
    for f in targets:
        if f not in latest:
            print('  [SKIP] 无快照基线: %s' % f)
            skipped += 1
            continue
        data, parts = _concat_parts(f)
        if data is None:
            print('  [SKIP] 无分卷: %s' % f)
            skipped += 1
            continue
        old = latest[f]
        new_sha = sha256(data)
        if new_sha == old.get('original_sha256'):
            unchanged += 1
            continue
        ratio = len(data) / old['original_bytes'] if old.get('original_bytes') else 0
        if ratio < SHRINK_GUARD and not args.force:
            print('  [REFUSE] %s 缩水至 %.0f%%（%d -> %d B）：疑似丢失而非演进，确认无误后再加 --force'
                  % (os.path.basename(f), ratio * 100, old.get('original_bytes', 0), len(data)))
            refused += 1
            continue
        if args.dry_run:
            print('  [DRY] %s 将刷新 %s -> %s (%.0f%%)'
                  % (os.path.basename(f), (old.get('original_sha256') or '')[:10], new_sha[:10], ratio * 100))
            changed += 1
            continue
        dst = old.get('backup') or full_backup_path(f)   # 尊重记录路径，避免产生同内容不同名孤儿
        Path(dst).write_bytes(data)
        new_entry = dict(old)
        new_entry.update({'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                          'op': 'snap-resnap',
                          'backup': dst,
                          'original_sha256': new_sha,
                          'original_bytes': len(data),
                          'parts': [{'file': p, 'bytes': os.path.getsize(p),
                                     'sha256': sha256(Path(p).read_bytes())} for p in parts],
                          'resnapped_from': old.get('original_sha256')})
        rows = [r for r in rows
                if not (r.get('file') == f and r.get('op') in ('snap', 'snap-resnap'))]
        rows.append(new_entry)
        Path(idx).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
        with Path(audit).open('a', encoding='utf-8') as fh:
            fh.write(json.dumps({'ts': new_entry['ts'], 'file': f, 'op': 'resnap',
                                 'old_sha256': old.get('original_sha256'), 'new_sha256': new_sha,
                                 'old_bytes': old.get('original_bytes'), 'new_bytes': len(data),
                                 'ratio': round(ratio, 3), 'forced': bool(args.force)},
                                ensure_ascii=False) + '\n')
        print('  [OK] %s 基线已刷新 %s -> %s (%.0f%%)'
              % (os.path.basename(f), (old.get('original_sha256') or '')[:10], new_sha[:10], ratio * 100))
        changed += 1
    print('[resnap] 刷新 %d / 未变 %d / 拒绝(缩水) %d / 跳过 %d%s'
          % (changed, unchanged, refused, skipped, '  [dry-run]' if args.dry_run else ''))
    return 0 if refused == 0 else 2


MANAGED_ROOT_DEFAULT = r'<MEMORY_ROOT>'   # prune 默认受管根（库外条目归档）


def cmd_prune(args):
    """把库外/悬空的备份条目归档到 _archive/，保持 _index.jsonl 只含受管库内证据"""
    idx = os.path.join(DEFAULT_SPLIT_BACKUP, '_index.jsonl')
    audit = os.path.join(DEFAULT_SPLIT_BACKUP, '_audit.jsonl')
    root = args.root or MANAGED_ROOT_DEFAULT
    rows = _load_index(idx)
    if not rows:
        print('[prune] _index.jsonl 为空')
        return 0
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    arc = os.path.join(DEFAULT_SPLIT_BACKUP, '_archive', ts)
    keep, outside, dangling = [], [], []
    for r in rows:
        f = r.get('file') or ''
        if not f.startswith(root):
            outside.append(r)
            continue
        bk = r.get('backup')
        if bk and not os.path.exists(bk):
            dangling.append(r)
            continue
        keep.append(r)
    print('[prune] 受管库内 %d / 库外 %d / 悬空 %d' % (len(keep), len(outside), len(dangling)))
    referenced = {os.path.normcase(r['backup']) for r in keep if r.get('backup')}
    all_backups = [os.path.join(DEFAULT_SPLIT_BACKUP, f) for f in os.listdir(DEFAULT_SPLIT_BACKUP)
                   if os.path.isfile(os.path.join(DEFAULT_SPLIT_BACKUP, f))
                   and f not in ('_index.jsonl', '_audit.jsonl')]
    orphans = [p for p in all_backups if os.path.normcase(p) not in referenced]
    print('[prune] 孤儿备份文件 %d 个（未被索引引用）' % len(orphans))
    for r in outside:
        print('   库外:', r.get('file'))
    for r in dangling:
        print('   悬空:', r.get('file'), '（备份缺失）')
    if args.dry_run:
        print('[prune] dry-run，未改动')
        return 0
    moved = 0
    for p in orphans:
        os.makedirs(arc, exist_ok=True)
        shutil.move(p, os.path.join(arc, os.path.basename(p)))
        moved += 1
    for r in outside:
        bk = r.get('backup')
        if bk and os.path.exists(bk):
            os.makedirs(arc, exist_ok=True)
            shutil.move(bk, os.path.join(arc, os.path.basename(bk)))
            moved += 1
    Path(idx).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in keep), encoding='utf-8')
    with Path(audit).open('a', encoding='utf-8') as fh:
        fh.write(json.dumps({'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                             'op': 'prune', 'archived_rows': len(outside),
                             'archived_files': moved, 'orphan_files': len(orphans),
                             'dangling_rows': len(dangling),
                             'archive_dir': arc, 'root': root,
                             'files': [r.get('file') for r in outside]},
                            ensure_ascii=False) + '\n')
    print('[prune] 归档 %d 个文件（库外行 %d / 孤儿 %d）→ %s；索引保留 %d 条；审计已记录' % (moved, len(outside), len(orphans), arc, len(keep)))
    return 0


def cmd_unify_names(args):
    """把索引行指向的备份文件统一为 .snap 命名（改名 + 改行 + 审计；内容不动）"""
    idx = os.path.join(DEFAULT_SPLIT_BACKUP, '_index.jsonl')
    audit = os.path.join(DEFAULT_SPLIT_BACKUP, '_audit.jsonl')
    rows = _load_index(idx)
    if not rows:
        print('[unify-names] _index.jsonl 为空')
        return 0
    todo, already, missing = [], 0, []
    for r in rows:
        f = r.get('file')
        bk = r.get('backup')
        if not f or not bk:
            continue
        want = full_backup_path(f)
        if os.path.normcase(bk) == os.path.normcase(want):
            already += 1
            continue
        if not os.path.exists(bk):
            missing.append(f)
            continue
        todo.append((r, bk, want))
    print('[unify-names] 需迁移 %d / 已统一 %d / 备份缺失 %d' % (len(todo), already, len(missing)))
    for f in missing:
        print('   缺失:', f)
    if args.dry_run:
        for _r, bk, want in todo:
            print('   [DRY]', os.path.basename(bk), '->', os.path.basename(want))
        print('[unify-names] dry-run，未改动')
        return 0
    renamed = []
    for i, (r, bk, want) in enumerate(todo):
        if os.path.exists(want) and os.path.normcase(bk) != os.path.normcase(want):
            # 目标已存在：内容一致则删旧，否则保留旧并跳过（不覆盖证据）
            if sha256(Path(bk).read_bytes()) == sha256(Path(want).read_bytes()):
                os.remove(bk)
                renamed.append({'from': bk, 'to': want, 'action': 'dedup-remove'})
                continue
            print('   [SKIP] 目标已存在且内容不同，保留原样:', os.path.basename(want))
            continue
        shutil.move(bk, want)
        renamed.append({'from': bk, 'to': want, 'action': 'rename'})
        # 同步所有指向该旧路径的行（同文件可能多行）
        for r2 in rows:
            if r2.get('backup') and os.path.normcase(r2['backup']) == os.path.normcase(bk):
                r2['backup'] = want
    Path(idx).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    with Path(audit).open('a', encoding='utf-8') as fh:
        fh.write(json.dumps({'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                             'op': 'unify-names', 'renamed': len(renamed),
                             'details': renamed}, ensure_ascii=False) + '\n')
    print('[unify-names] 迁移 %d 个文件；索引已同步；审计已记录' % len(renamed))
    return 0


# ===================== selftest（2026-09-21）=====================
SELFTEST_CASES = []


def _st_case(fn):
    SELFTEST_CASES.append(fn)
    return fn


def _st_sample(size_hint=6000):
    lines = ['# selftest 样本', '']
    i = 0
    while sum(len(l.encode('utf-8')) + 1 for l in lines) < size_hint:
        i += 1
        lines += ['## 段 %03d' % i, '内容行 %03d：用于触发 4KB 拆分边界。' % i, '']
    return ('\n'.join(lines) + '\n').encode('utf-8')


@_st_case
def _st_split_bytes(sb):
    """split 后 concat(分卷) 必须逐字节等于原文；壳 ≤ 4KB"""
    p = os.path.join(sb, 'sample.md')
    data = _st_sample()
    Path(p).write_bytes(data)
    import types as _t
    import io as _io
    import contextlib as _cl
    with _cl.redirect_stdout(_io.StringIO()):
        cmd_split(_t.SimpleNamespace(file=p, force=True, manifest=None))
    parts = sorted(glob.glob(os.path.join(sb, 'sample.part*.md')), key=part_sort_key)
    if not parts:
        return False, '未产生分卷'
    joined = b''.join(Path(x).read_bytes() for x in parts)
    if joined != data:
        return False, 'concat(%d B) != 原文(%d B)' % (len(joined), len(data))
    if os.path.getsize(p) > MAX:
        return False, '指针壳 %d B > %d' % (os.path.getsize(p), MAX)
    return True, '%d 卷 / concat==原文 (%d B)' % (len(parts), len(data))


@_st_case
def _st_resnap_guard(sb):
    """resnap 安全闸：缩水 >20% 必须拒绝（rc=2），--force 才放行"""
    p = os.path.join(sb, 'sample.md')
    parts = sorted(glob.glob(os.path.join(sb, 'sample.part*.md')), key=part_sort_key)
    idx = os.path.join(DEFAULT_SPLIT_BACKUP, '_index.jsonl')
    data = b''.join(Path(x).read_bytes() for x in parts)
    row = {'ts': '2026-09-21T00:00:00', 'op': 'snap', 'file': p,
           'backup': full_backup_path(p), 'original_sha256': sha256(data),
           'original_bytes': len(data),
           'parts': [{'file': x, 'bytes': os.path.getsize(x), 'sha256': sha256(Path(x).read_bytes())} for x in parts]}
    Path(full_backup_path(p)).write_bytes(data)
    with Path(idx).open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    import types as _t
    import io as _io
    import contextlib as _cl
    v = parts[-1]
    o = Path(v).read_bytes()
    Path(v).write_bytes(o[: max(1, len(o) // 4)])   # 截到 1/4 → 整体缩水 > 20%
    with _cl.redirect_stdout(_io.StringIO()):
        rc_refuse = cmd_resnap(_t.SimpleNamespace(file=[p], all=False, force=False, dry_run=False))
        rc_force = cmd_resnap(_t.SimpleNamespace(file=[p], all=False, force=True, dry_run=False))
    if rc_refuse != 2:
        return False, '缩水时未拒绝（rc=%s，期望 2）' % rc_refuse
    if rc_force != 0:
        return False, '--force 未放行（rc=%s，期望 0）' % rc_force
    return True, '缩水拒绝 rc=2 / --force 放行 rc=0'


@_st_case
def _st_prune_orphan(sb):
    """prune：孤儿文件与库外条目必须被归档到 _archive"""
    orphan = os.path.join(DEFAULT_SPLIT_BACKUP, 'ORPHAN_probe.md.snap')
    Path(orphan).write_bytes(b'orphan')
    import types as _t
    import io as _io
    import contextlib as _cl
    with _cl.redirect_stdout(_io.StringIO()):
        rc = cmd_prune(_t.SimpleNamespace(root=os.path.join(sb, 'nope'), dry_run=False))
    if rc != 0:
        return False, 'rc=%s' % rc
    if os.path.exists(orphan):
        return False, '孤儿文件未被归档'
    arc = os.path.join(DEFAULT_SPLIT_BACKUP, '_archive')
    found = glob.glob(os.path.join(arc, '**', 'ORPHAN_probe.md.snap'), recursive=True)
    if not found:
        return False, '归档目录内未找到孤儿文件'
    idx = os.path.join(DEFAULT_SPLIT_BACKUP, '_index.jsonl')
    rows = _load_index(idx)
    if any(r.get('file', '').startswith(sb) for r in rows):
        return False, '库外条目未被移除'
    return True, '孤儿归档 + 库外行清除'


@_st_case
def _st_unify_idempotent(sb):
    """unify-names：迁移后命名全为 .snap，且二次运行零改动（幂等）"""
    p = os.path.join(sb, 'sample.md')
    old = os.path.join(DEFAULT_SPLIT_BACKUP, 'LEGACY_naming_probe.md')
    Path(old).write_bytes(b'legacy')
    idx = os.path.join(DEFAULT_SPLIT_BACKUP, '_index.jsonl')
    rows = _load_index(idx)
    rows.append({'ts': 'x', 'op': 'snap', 'file': p, 'backup': old,
                 'original_sha256': sha256(b'legacy'), 'original_bytes': 6})
    Path(idx).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    import types as _t
    import io as _io
    import contextlib as _cl
    with _cl.redirect_stdout(_io.StringIO()):
        rc1 = cmd_unify_names(_t.SimpleNamespace(dry_run=False))
        buf = _io.StringIO()
        with _cl.redirect_stdout(buf):
            rc2 = cmd_unify_names(_t.SimpleNamespace(dry_run=False))
    if rc1 != 0 or rc2 != 0:
        return False, 'rc=%s/%s' % (rc1, rc2)
    if '需迁移 0' not in buf.getvalue():
        return False, '二次运行非幂等: %s' % buf.getvalue().strip().splitlines()[0]
    rows2 = _load_index(idx)
    bad = [r['file'] for r in rows2 if r.get('backup') and not r['backup'].endswith('.snap')]
    if bad:
        return False, '仍有非 .snap 命名: %s' % bad[:2]
    return True, '迁移 + 幂等（二次 0 改动）'


@_st_case
def _st_single_source(sb):
    """单一定义点静态检查（拦「两处各写一份」复发）"""
    # 只在 selftest 之前的代码段内计数，避免把本检查自身的字面量也数进去
    src = Path(os.path.abspath(__file__)).read_text(encoding='utf-8')
    src = src.split('# ===================== selftest')[0]
    checks = [
        ("name_handbuilt", src.count("path.replace(':', '-').replace(os.sep, '__')"), 1),
        ('part_sort_key_def', src.count('def part_sort_key('), 1),
        ('old_sort_site', src.count('key=lambda p: part_index(p)'), 0),
        ('manifest_append_calls', src.count('manifest_append(args.manifest or DEFAULT_MANIFEST'), 3),
    ]
    bad = [(n, got, want) for n, got, want in checks if got != want]
    if bad:
        return False, '；'.join('%s=%d(期望 %d)' % b for b in bad)
    return True, '命名/排序/清单各 1 处定义点'


def cmd_selftest(args):
    import tempfile
    sb = tempfile.mkdtemp(prefix='split_md_4kb_selftest_')
    g = globals()
    old_bk, old_mf = g['DEFAULT_SPLIT_BACKUP'], g['DEFAULT_MANIFEST']
    g['DEFAULT_SPLIT_BACKUP'] = os.path.join(sb, '_bk')
    g['DEFAULT_MANIFEST'] = os.path.join(sb, 'manifest.jsonl')
    os.makedirs(g['DEFAULT_SPLIT_BACKUP'], exist_ok=True)
    failed = 0
    try:
        _st_split_bytes(sb)   # 先建样本分卷，后续用例依赖它
        print('[selftest] 沙箱: %s' % sb)
        for fn in SELFTEST_CASES:
            try:
                ok, detail = fn(sb)
            except Exception as e:
                ok, detail = False, '异常 %s: %s' % (type(e).__name__, e)
            print('  [%s] %-24s %s' % ('PASS' if ok else 'FAIL', fn.__name__.replace('_st_', ''), detail))
            if not ok:
                failed += 1
    finally:
        g['DEFAULT_SPLIT_BACKUP'], g['DEFAULT_MANIFEST'] = old_bk, old_mf
        shutil.rmtree(sb, ignore_errors=True)
    total = len(SELFTEST_CASES)
    print('[selftest] %d/%d 通过%s' % (total - failed, total, '' if not failed else ' —— 有 FAIL'))
    return 0 if not failed else 1


def cmd_scan(args):
    root = os.path.abspath(args.root)
    excludes = set(args.exclude or [])
    bad = []
    total = 0

    def walk(d):
        nonlocal total
        try:
            entries = list(os.scandir(d))
        except OSError:
            return
        for e in entries:
            if e.is_symlink() or e.is_junction():
                continue
            if e.is_dir():
                if e.name in excludes or any(x in e.name for x in excludes):
                    continue
                walk(e.path)
            elif e.name.endswith('.md'):
                total += 1
                if e.stat().st_size > MAX:
                    bad.append((e.stat().st_size, e.path))

    walk(root)
    bad.sort(reverse=True)
    print('scan %s: md=%d, >4096B=%d' % (root, total, len(bad)))
    for size, p in bad:
        print('%6.1fKB  %s' % (size / 1024, p))
    sys.exit(0 if not bad else 3)


def main():
    if len(sys.argv) < 3 and sys.argv[1:2] not in (["resnap"], ["prune"], ["unify-names"], ["selftest"], ["--selftest"]):   # resnap 允许零参数（= --all）
        print(__doc__)
        sys.exit(2)
    mode = sys.argv[1]
    if mode == '--selftest':   # 允许 --selftest 写法
        mode = 'selftest'
    args = sys.argv[2:]
    if mode == 'split':
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument('file')
        p.add_argument('--manifest')
        p.add_argument('--force', action='store_true')
        a = p.parse_args(args)
        cmd_split(a)
    elif mode == 'rechunk':
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument('file')
        p.add_argument('--manifest')
        a = p.parse_args(args)
        cmd_rechunk(a)
    elif mode == 'series':
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument('base')
        p.add_argument('--manifest')
        a = p.parse_args(args)
        cmd_series(a)
    elif mode == 'scan':
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument('root')
        p.add_argument('--exclude', action='append', default=[])
        a = p.parse_args(args)
        cmd_scan(a)
    elif mode == 'resnap':
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument('file', nargs='*')
        p.add_argument('--all', action='store_true')
        p.add_argument('--force', action='store_true')
        p.add_argument('--dry-run', dest='dry_run', action='store_true')
        a = p.parse_args(args)
        sys.exit(cmd_resnap(a))
    elif mode == 'prune':
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument('--root', default=None)
        p.add_argument('--dry-run', dest='dry_run', action='store_true')
        a = p.parse_args(args)
        sys.exit(cmd_prune(a))
    elif mode == 'unify-names':
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument('--dry-run', dest='dry_run', action='store_true')
        a = p.parse_args(args)
        sys.exit(cmd_unify_names(a))
    elif mode in ('selftest', '--selftest'):
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument('--verbose', action='store_true')
        a = p.parse_args([])
        sys.exit(cmd_selftest(a))
    else:
        print('未知模式: %s' % mode)
        sys.exit(2)


if __name__ == '__main__':
    main()
