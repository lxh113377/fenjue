#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
direct_layer.py — L0.1 高频直连层
=================================
R162: 从 unified_router.py 拆出（五层模块化: direct/tag/BGE/memory/LLM）。
权威数据源: eval/direct_map.json（eval/save_direct_map.py --force 同步 fallback）。
对外 API: DIRECT_MAP / direct_route / _load_direct_map
"""
import os
import json
import re
import sys  # P0-4: 降级可观测需 stderr 输出

from tag_layer import NEGATIVE_TAG_MAP, _neg_pattern_fires

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))

#       本列表仅作离线 fallback，改动后跑 eval/save_direct_map.py --force 同步。
from direct_map_fallback_data import _DIRECT_MAP_FALLBACK  # P1-8: 数据字面量外置（双写语义/C24 不变）


# R209 P1-性能: DIRECT_MAP ~290 条正则此前每查询在 direct_route 循环内实时
# re.compile（re.search(str)），预编译缓存后每 pattern 全生命周期只编译一次。
_CREGEX_CACHE = {}


def _cregex(pattern: str):
    """re.IGNORECASE 预编译缓存：direct_layer 全部正则调用统一入口。

    按 pattern 文本键控 → 语义与来源文件无关，免疫 direct_map.json reload
    与 FENJUE_DIRECT_MAP_DIR 测试目录覆盖；坏 pattern 首次编译抛 re.error，
    与原 re.search 行为一致（调用方 except re.error: continue 兜底不变）。"""
    pat = _CREGEX_CACHE.get(pattern)
    if pat is None:
        pat = re.compile(pattern, re.IGNORECASE)
        _CREGEX_CACHE[pattern] = pat
    return pat


def direct_route(query: str) -> str | None:
    """L0.1 高频直连: 正则匹配→直接返回skill名，短路全部路由。
    DIRECT_MAP 为 (pattern, skill_name) 元组列表，按优先级排序，
    第一个命中即返回（短路）。
    
    R18.2: +本地守卫 — 含"本地/离线/不用云端"关键词时，跳过云端 service
    的直接映射（如 seedream/seedance），让 Tag+NOT USE 系统重新路由到本地 skill。
    R20:   +NOT USE 守卫 — 直连命中后过该 skill 的负标签；query 命中负标签则
    放弃本条直连（回落到下一 pattern / 全管线），治"直连过度短路"（盲测教训:
    'whisper API 转写'被'转写'短路到 video-whisper-transcribe）。
    配对时序（2026-09-09 审查专项）: 新增正样本必须排在「将被 NEGATIVE_TAG_MAP
    拦截的宽 pattern」之前——负样本只产生"让位"（旧 skill 被拦回落下一 pattern），
    排在宽 pattern 之后则新 skill 不会被命中（无"接管"），意图落到 BGE 语义摇摆
    （实证：审查类查询 frontend-skill→github→code-review 三跳修复链）。
    """
    # R18.2: 本地守卫 — 跳过云端 service 的直连
    local_kw = ['本地', '离线', '不用.*云端', '不想.*联网', '不上传', '隐私']
    is_local = any(_cregex(kw).search(query) for kw in local_kw)
    # R166: byted-mediakit-shared 是本地 CLI 工具（mediakit-cli），非云端 service，移出守卫名单
    cloud_skills = {'byted-seedream-image-generate', 'byted-seedance-video-generate',
                    'openai-whisper-api', 'tencent-docs', 'tencent-saas-docs'}
    skipped_cloud = []  # R166: 被本地守卫跳过的云端直连（无本地替代时回落为次优解）

    for pattern, skill_name in DIRECT_MAP:
        try:
            if _cregex(pattern).search(query):
                # 本地守卫: 如果用户明确要本地执行，跳过云端 skill
                if is_local and skill_name in cloud_skills:
                    skipped_cloud.append(skill_name)  # 记录，供无本地替代时回落
                    continue  # 跳到下一个 pattern
                # R20 NOT USE 守卫: 直连结果与负标签冲突 → 放弃本条直连
                # (否定语境守卫: _neg_pattern_fires=True=负标签生效(拦截), False=前缀有否定词→放行)
                #  如 '不用云端本地生成图片' 的 '云端.*生成.*图' 命中但前缀有'不用'→负标签失效→放行
                neg = NEGATIVE_TAG_MAP.get(skill_name)
                # 负标签生效(命中且无否定前缀) → 放弃直连; 有否定前缀 → 负标签不生效,放行
                if neg and _neg_active(neg, query):
                    continue
                return skill_name
        except re.error:
            continue
    # R166 本地守卫回落: 用户明确要本地执行，但路由系统无本地替代技能（local-* TRAE 内置不可达），
    # 回落到第一个被跳过的云端直连作为次优解（如"不用云端本地生成图片"→ byted-seedream-image-generate）
    for skill_name in skipped_cloud:
        neg = NEGATIVE_TAG_MAP.get(skill_name)
        if neg and _neg_active(neg, query):
            continue
        return skill_name
    return None


def _neg_active(neg_patterns, query):
    """R20 NOT USE 守卫（单次求值）：任一负标签命中且无否定前缀 → True（拦截直连）。
    原实现外层 any(search) 开关判断与内层 any(search and fires) 对同一批正则重复求值。"""
    for np_ in neg_patterns:
        rx = _cregex(np_)
        if rx.search(query) and _neg_pattern_fires(rx, query):
            return True
    return False

# ====== DIRECT_MAP 加载（R162: 外置 JSON 为权威源，缺失/损坏回退内置 fallback） ======
DIRECT_MAP_JSON = os.path.join(EVAL_DIR, 'direct_map.json')
# R165 预案: 超过维护阈值后可拆分为 direct_map.d/partNN.json（文件名升序拼接 = 保持全局优先级）。
# 目录不存在时仍读单文件 direct_map.json；FENJUE_DIRECT_MAP_DIR 仅供测试/预览覆盖。
DIRECT_MAP_DIR = os.environ.get('FENJUE_DIRECT_MAP_DIR') or os.path.join(EVAL_DIR, 'direct_map.d')


def _valid_entries(data):
    """结构校验: [pattern, skill] 二元组列表, 非法返回空列表"""
    if isinstance(data, list) and data and all(
            isinstance(item, (list, tuple)) and len(item) == 2
            and isinstance(item[0], str) and isinstance(item[1], str)
            for item in data):
        return [tuple(item) for item in data]
    return []


def _load_direct_map():
    """加载直连映射: 优先 direct_map.d/*.json（按文件名升序拼接，保持全局优先级），
    其次 direct_map.json；均不可用/损坏时回退内置 fallback。
    P0-4: 降级可观测 —— 损坏分卷逐个报数到 stderr；分卷全损/全量失败时打 FAIL 级告警
    （模块 import 期不 exit，告警计数挂 DIRECT_MAP_LOAD_WARNINGS 供门禁/测试断言）。"""
    global DIRECT_MAP_LOAD_WARNINGS
    DIRECT_MAP_LOAD_WARNINGS = []
    parts = []
    if os.path.isdir(DIRECT_MAP_DIR):
        for fn in sorted(f for f in os.listdir(DIRECT_MAP_DIR) if f.endswith('.json')):
            try:
                with open(os.path.join(DIRECT_MAP_DIR, fn), 'r', encoding='utf-8') as f:
                    parts.extend(_valid_entries(json.load(f)))
            except Exception as e:
                DIRECT_MAP_LOAD_WARNINGS.append(fn)
                print(f'[direct_layer] WARN 分卷损坏已跳过: {fn} ({type(e).__name__}: {e})',
                      file=sys.stderr)
        if parts:
            if DIRECT_MAP_LOAD_WARNINGS:
                print(f'[direct_layer] WARN {len(DIRECT_MAP_LOAD_WARNINGS)} 个分卷损坏，'
                      f'其余分卷仍生效: {DIRECT_MAP_LOAD_WARNINGS}', file=sys.stderr)
            return parts
        if any(f.endswith('.json') for f in os.listdir(DIRECT_MAP_DIR)):
            print('[direct_layer] FAIL 全部分卷损坏，无有效条目 → 回退内置 fallback',
                  file=sys.stderr)
    try:
        with open(DIRECT_MAP_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
        valid = _valid_entries(data)
        if valid:
            return valid
    except Exception as e:
        print(f'[direct_layer] FAIL 全量读取失败 → 回退内置 _DIRECT_MAP_FALLBACK '
              f'({type(e).__name__}: {e})（降级可路由，R207 P2-1 留痕）', file=sys.stderr)
    return _DIRECT_MAP_FALLBACK


DIRECT_MAP_LOAD_WARNINGS: list = []


DIRECT_MAP = _load_direct_map()
