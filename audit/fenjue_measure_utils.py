#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fenjue_measure_utils.py — fenjue_measure 纯函数抽取（R193 阶段2）

把 fenjue_measure.py 中无盘依赖的辅助函数抽出，供 pytest 参数化测试；
fenjue_measure.py 改为 import 本模块（脚本本身不可 import——顶层即执行）。
"""

import re


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def extract_links(txt):
    """提取 markdown 链接 / 反引号文件引用 / <MEMORY_ROOT> 路径。"""
    links = set()
    for m in re.finditer(r"\[[^\]]*?\]\(([^)]+)\)", txt):
        links.add(m.group(1))
    for m in re.finditer(r"`([^`]+\.(?:md|json))`", txt):
        links.add(m.group(1))
    for m in re.finditer(r"<MEMORY_ROOT>\\[^\s`)]+", txt):
        links.add(m.group(0))
    return links


def read_split_text(read_fn, base):
    """壳 + 全部分卷合并读取（R161 4KB 拆分后正文在 partN，禁只读根壳）。
    read_fn(path) -> str，注入便于测试。"""
    import os

    base_dir = os.path.dirname(base)
    stem = os.path.basename(base)[:-3]  # 去掉 .md
    pattern = re.compile(r"^" + re.escape(stem) + r"\.part\d+\.md$")
    parts = sorted(f for f in os.listdir(base_dir) if pattern.match(f))
    txt = read_fn(base)
    for p in parts:
        txt += "\n" + read_fn(os.path.join(base_dir, p))
    return txt
