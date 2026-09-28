#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
split_direct_map.py — DIRECT_MAP 分卷拆分工具（R165 预案，按需使用）
====================================================================
direct_map.json 超过维护阈值（建议 400 条 / 64KB）时，把单文件拆为
direct_map.d/partNN.json（保持原全局顺序 = 保持路由优先级语义）。
direct_layer.py 已支持 direct_map.d/ 目录加载（文件名升序拼接）。

四道防线（lessons-p0 #7）:
  ① 白名单: 只写 OUT_DIR 内的 partNN.json
  ② 写前校验: 每个分卷非空
  ③ 原子替换: 先写 .tmp 再 os.replace
  ④ 写后守恒: 重读验证分卷全量 == 源文件全量（含顺序）

用法:
  python split_direct_map.py --dry-run            # 只预览拆分统计
  python split_direct_map.py --per-file 120       # 每卷 ≤120 条（默认）
  python split_direct_map.py --parts 3            # 按 3 卷拆分
  python split_direct_map.py --force              # 目标目录已存在且非空时重建
"""
import os
import sys
import json
import io

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(EVAL_DIR, 'direct_map.json')
OUT_DIR = os.environ.get('FENJUE_DIRECT_MAP_OUT') or os.path.join(EVAL_DIR, 'direct_map.d')


def load_src():
    if not os.path.exists(SRC):
        raise SystemExit(f'ERROR: {SRC} 不存在')
    with open(SRC, encoding='utf-8') as f:
        data = json.load(f)
    if not (isinstance(data, list) and data and all(
            isinstance(i, list) and len(i) == 2
            and isinstance(i[0], str) and isinstance(i[1], str)
            for i in data)):
        raise SystemExit(f'ERROR: {SRC} 结构非法')
    return data


def chunks(entries, per_file=None, parts=None):
    n = len(entries)
    size = -(-n // parts) if parts else (per_file or 120)
    return [entries[i:i + size] for i in range(0, n, size)]


def main():
    dry = '--dry-run' in sys.argv
    force = '--force' in sys.argv
    per_file = None
    parts = None
    if '--per-file' in sys.argv:
        per_file = int(sys.argv[sys.argv.index('--per-file') + 1])
    if '--parts' in sys.argv:
        parts = int(sys.argv[sys.argv.index('--parts') + 1])
    entries = load_src()
    groups = chunks(entries, per_file, parts)
    total = sum(len(g) for g in groups)
    ok = total == len(entries)
    print(f'源: {SRC} | 总条目 {len(entries)} | 分卷 {len(groups)} | 守恒 {ok}')
    if not ok:
        raise SystemExit('ERROR: 分卷条目数不守恒, 中止')
    if dry:
        for i, g in enumerate(groups, 1):
            print(f'  part{i:02d}.json: {len(g)} 条 ({len(json.dumps(g, ensure_ascii=False))} B)')
        return
    if os.path.isdir(OUT_DIR) and os.listdir(OUT_DIR) and not force:
        raise SystemExit(f'ERROR: {OUT_DIR} 已存在非空, 加 --force 重建')
    os.makedirs(OUT_DIR, exist_ok=True)
    for i, g in enumerate(groups, 1):
        name = f'part{i:02d}.json'
        path = os.path.join(OUT_DIR, name)
        if not g:
            raise SystemExit(f'ERROR: {name} 为空, 中止')
        tmp = path + '.tmp'
        with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(g, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp, path)
    loaded = []
    for fn in sorted(f for f in os.listdir(OUT_DIR) if f.endswith('.json')):
        with open(os.path.join(OUT_DIR, fn), encoding='utf-8') as f:
            loaded.extend(json.load(f))
    if len(loaded) != len(entries) or loaded != entries:
        raise SystemExit(f'ERROR: 写后守恒校验失败 {len(loaded)} != {len(entries)}')
    print(f'✅ 已拆分: {OUT_DIR} ({len(groups)} 卷 / {len(loaded)} 条, 顺序保持)')


if __name__ == '__main__':
    main()
