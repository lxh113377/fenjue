# -*- coding: utf-8 -*-
"""
save_direct_map.py — DIRECT_MAP 外置 JSON 同步工具（R162；P0-11 修解析目标）
==========================================================
从 direct_map_fallback_data.py 的 _DIRECT_MAP_FALLBACK 提取直连映射表，
生成 eval/direct_map.json（权威数据源）。

解析目标口径（2026-09-24 修）：P1-8 数据/逻辑分离后，字面量唯一源 =
direct_map_fallback_data.py；direct_layer.py 只剩 import/调用形态，
literal_eval 必炸（malformed node: ast.Call）——本工具此前一直解析旧锚，
属拆分漏改的既有坏损（C24 对账不做 literal_eval 故未暴露）。

用法:
  python eval/save_direct_map.py            # dry-run，只打印计数
  python eval/save_direct_map.py --force    # 写入 direct_map.json（原子替换）

防线（lessons-p0 #7 四道防线精神）:
  ① 白名单校验: 元素必须是 (pattern:str, skill:str) 二元组
  ② 写前校验: 列表非空且条数一致
  ③ 原子替换: 先写 .tmp 再 rename
  ④ 写后守恒: 重读校验 count == 源 count
"""
import ast
import json
import os
import sys
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
FALLBACK_DATA = os.path.join(EVAL_DIR, 'direct_map_fallback_data.py')
OUT = os.path.join(EVAL_DIR, 'direct_map.json')


def extract_fallback(path):
    """用 ast 提取 direct_map_fallback_data.py 中的 _DIRECT_MAP_FALLBACK（或旧名 DIRECT_MAP）。"""
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if '_DIRECT_MAP_FALLBACK' in names or 'DIRECT_MAP' in names:
                data = ast.literal_eval(node.value)
                if isinstance(data, list) and data:
                    return data
    raise SystemExit('ERROR: direct_map_fallback_data.py 中未找到 _DIRECT_MAP_FALLBACK/DIRECT_MAP 列表')


def validate(entries):
    """白名单校验: 每条必须是 (str, str) 二元组。"""
    bad = [e for e in entries if not (isinstance(e, (list, tuple)) and len(e) == 2
                                      and isinstance(e[0], str) and isinstance(e[1], str))]
    if bad:
        raise SystemExit(f'ERROR: {len(bad)} 条非法条目: {bad[:3]}')
    if not entries:
        raise SystemExit('ERROR: 空列表，拒绝写入')
    return True


def main():
    force = '--force' in sys.argv
    entries = extract_fallback(FALLBACK_DATA)
    validate(entries)
    print(f'源列表: {len(entries)} 条 ({FALLBACK_DATA})')
    if not force:
        print(f'DRY-RUN: 目标 {OUT} 未写入（--force 才写）')
        return
    tmp = Path(OUT + '.tmp')
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, OUT)  # 原子替换
    reloaded = json.loads(Path(OUT).read_text(encoding='utf-8'))
    if len(reloaded) != len(entries):
        raise SystemExit('ERROR: 写后守恒校验失败')
    print(f'已写入: {OUT} ({len(reloaded)} 条，守恒校验通过)')


if __name__ == '__main__':
    main()
