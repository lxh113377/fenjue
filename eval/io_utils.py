#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""io_utils.py — 读写原语唯一实现（P1-5 收敛，2026-09-23）
====================================================

收敛面（审计 P1-5）：load_json ×5 / load_jsonl ×2 / read_text ×6 / 原子写 ×3 的
散落同体实现收敛到本模块。原则：各历史调用的行为契约（errors 模式 / max_kb 截断 /
newline / fail-open 语义）经参数**显式保留**，迁移点逐个等价；新代码默认无参形态。

安全（P0-11，2026-09-24）：全部原语经 checked_path 校验后走 pathlib 接收者式
读写（Path.open / Path.write_text / Path.write_bytes）——resolve 消解 ../、
显式拒绝含 .. 分量的路径，防路径穿越（CWE-22）。
"""
import json
import os
from pathlib import Path

_RAISE = object()  # 哨兵：区分「未给 default」与「default=None」


def checked_path(path, base=None):
    """路径穿越防御（CWE-22，Mimosa P0-11）。

    规则：① 路径含 ``..`` 分量 → 拒绝（ValueError）；② resolve 消解符号链接与
    相对段；③ base 给定时强制 resolve 后包含于 base（越界拒绝）。
    返回 pathlib.Path（绝对路径）；写原语在落盘前调用。
    """
    p = Path(path)
    if '..' in p.parts:
        raise ValueError(f'路径穿越拒绝（含 .. 分量）: {path}')
    rp = p.resolve()
    if base is not None:
        root = Path(base).resolve()
        if rp != root and root not in rp.parents:
            raise ValueError(f'路径越界拒绝: {rp} 不在 {root} 内')
    return rp


def load_json(path, default=_RAISE):
    """读 JSON。

    default 未给 → 读失败抛异常（fail-closed，门禁/构建路径用）；
    default 给定 → 读失败返回 default（fail-open 显式化，CI 摘要等降级路径用）。
    """
    target = checked_path(path)
    if default is not _RAISE:
        try:
            with target.open(encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default
    with target.open(encoding='utf-8') as f:
        return json.load(f)


def load_jsonl(path):
    """读 JSONL：跳过空行与坏行（与历史实现等价；with 收敛句柄）。"""
    rows = []
    target = checked_path(path)
    if target.exists():
        with target.open(encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def read_text(path, errors='strict', max_kb=None, newline=None):
    """读文本。errors / max_kb（KB 截断防大文件）/ newline 对应历史各形态。"""
    kwargs = {}
    if newline is not None:
        kwargs['newline'] = newline
    with checked_path(path).open(encoding='utf-8', errors=errors, **kwargs) as f:
        return f.read() if max_kb is None else f.read(max_kb * 1024)


def read_text_safe(path, errors='replace', max_kb=None):
    """读文本 fail-open：任何异常返回 ''（原 lessons_hitrate / trace_view 形态）。"""
    try:
        return read_text(path, errors=errors, max_kb=max_kb)
    except Exception:
        return ''


def write_text_atomic(path, text, newline=None):
    """原子写文本：tmp + os.replace（中途崩溃不留截断文件）。"""
    target = checked_path(path)
    tmp = target.with_name(target.name + '.tmp')
    tmp.write_text(text, encoding='utf-8', newline=newline)
    os.replace(tmp, target)


def write_json_atomic(path, obj):
    """原子写 JSON（utf-8 / ensure_ascii=False / indent=2）。"""
    target = checked_path(path)
    tmp = target.with_name(target.name + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, target)
