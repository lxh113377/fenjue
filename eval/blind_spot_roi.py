#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blind_spot_roi.py — 主线3 盲区 ROI 计算模块（R198.9 重做版）
================================================================
背景：原「6.6% 盲区 ROI 评估」在 07 标 [x] 但报告缺失（致命纪律 #9 假完成实证），
     2026-08-16 按 T5 回滚重做。本模块为纯只读分析，不改动数据层与路由。

定位：消费 route_trace.jsonl（unified_router._trace 生产写入，FENJUE_ROUTE_TRACE=1），
     计算「NONE 盲区」的修复 ROI，输出直连/触发词/白名单三类候选的优先级排序，
     供 DIRECT_MAP 扩容与触发词治理立项参考。

与 route_miss_report.py 的关系：
  - 复用其 load_traces() 加载逻辑（保持输入数据源与对外接口兼容，不重复实现）
  - 本模块只做「盲区 → 聚类 → ROI 分级」的增量分析，不修改原报告输出
  - 两模块可独立运行，互不影响

ROI 口径（指标定义）：
  blind_ratio   = NONE 条数 / production 总条数              # 整体盲区率
  whitelist_cnt = NONE 且 direct=True 的条数                  # 设计内 NONE 白名单（苹果香蕉等）
  true_miss_cnt = NONE 且 direct=False 的条数                 # 真实盲区（修复对象）
  cluster_n     = 同 query 前 PREFIX_LEN 字符模式的条数        # 修复后收益上限
  ROI 等级 = f(cluster_n, 修复成本档)：
    HIGH   — cluster_n >= HIGH_FREQ(30) 且 成本档为直连(1)
    MEDIUM — cluster_n >= MED_FREQ(10)  或 成本档为触发词(2)
    LOW    — 其余
  修复成本档（cost_tier）：
    1 = DIRECT_MAP 直连（补 direct_map.json 一行）
    2 = 触发词治理（improve_all_triggers / skill_content json）
    3 = 新建 skill 或 NONE 白名单（需人工确认语义）

用法:
  python blind_spot_roi.py                       # 全量分析（production 源）
  python blind_spot_roi.py --days 7              # 近7天
  python blind_spot_roi.py --json                # 机器可读输出
  python blind_spot_roi.py --prefix 6            # 自定义聚类前缀长度
"""
import os
import sys
import json
import datetime
from collections import Counter

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EVAL_DIR)

# 复用既有加载器，保证数据源与接口兼容（不重复实现解析逻辑）
from route_miss_report import load_traces  # noqa: E402

# ---- 可配置阈值（单一真相源，便于测试注入） ----
HIGH_FREQ = 30    # HIGH ROI 频次下限（>=30 次同前缀）
MED_FREQ = 10     # MEDIUM ROI 频次下限（>=10 次同前缀）
PREFIX_LEN = 6    # 聚类前缀长度（中文 query 前 6 字符）
TOP_N = 15        # 输出候选条数


def is_miss(r):
    """判定是否为 NONE 盲区记录。"""
    return r.get('top1') in (None, 'NONE')


def is_whitelist(r):
    """判定是否为设计内 NONE 白名单（direct=True 且 top1=NONE）。"""
    return is_miss(r) and bool(r.get('direct'))


def is_true_miss(r):
    """判定是否为真实盲区（NONE 且非白名单）。"""
    return is_miss(r) and not r.get('direct')


def cluster_true_miss(rows, prefix_len=PREFIX_LEN):
    """对真实盲区按 query 前缀聚类，返回 {前缀: 频次} 降序。边缘：空 query → 跳过。"""
    cnt = Counter()
    for r in rows:
        if not is_true_miss(r):
            continue
        q = r.get('q') or r.get('query') or ''
        if not q:  # 空 query 无法聚类，跳过（防噪声）
            continue
        cnt[q[:prefix_len]] += 1
    return cnt.most_common()


def classify_tier(prefix, freq):
    """按语义特征粗判修复成本档。1=直连 2=触发词 3=白名单/新建。
    规则：白名单典型开头（帮我/讲个/今天/现在几点了等闲聊）→ 3；
          技术动作词 → 1（DIRECT_MAP 直连候选）；
          其余 → 2。注：此为启发式，最终档位需人工复核（见风险点 R1）。"""
    WHITELIST_HINTS = ('帮我起个', '讲个', '今天天气', '现在几点', '你是谁',
                       '1+1', '推荐一本', '周末去哪', '东京和北京', '苹果和香蕉')
    DIRECT_HINTS = ('显存不够', '会议材料', '磁盘快爆', '本地文字', '让另一个',
                    '两个功能', '灵感枯竭', '世界杯', '讲讲我的')
    if any(prefix.startswith(h) for h in WHITELIST_HINTS):
        return 3
    if any(prefix.startswith(h) for h in DIRECT_HINTS):
        return 1
    return 2


def roi_score(freq, tier):
    """ROI 评分 = 频次(收益) / 成本档(代价)。频次越高、成本越低 → ROI 越高。"""
    if freq <= 0:
        return 0.0
    return round(freq / tier, 2)


def roi_level(freq, tier):
    """ROI 分级：HIGH / MEDIUM / LOW。"""
    if freq >= HIGH_FREQ and tier == 1:
        return 'HIGH'
    if freq >= MED_FREQ or tier == 2:
        return 'MEDIUM'
    return 'LOW'


def blind_spot_roi(rows, top_n=TOP_N, prefix_len=PREFIX_LEN):
    """核心计算：盲区统计 + 聚类 + ROI 分级。返回结构化 dict（可 JSON 序列化）。"""
    total = len(rows)
    misses = [r for r in rows if is_miss(r)]
    whitelist_cnt = sum(1 for r in misses if is_whitelist(r))
    true_cnt = sum(1 for r in misses if is_true_miss(r))
    clusters = cluster_true_miss(rows, prefix_len)

    candidates = []
    for prefix, freq in clusters:
        tier = classify_tier(prefix, freq)
        candidates.append({
            'prefix': prefix,
            'freq': freq,
            'cost_tier': tier,
            'roi_score': roi_score(freq, tier),
            'roi_level': roi_level(freq, tier),
        })
    # ROI 降序
    candidates.sort(key=lambda c: c['roi_score'], reverse=True)

    return {
        'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'summary': {
            'total_traces': total,
            'blind_ratio': round(true_cnt / total * 100, 2) if total else 0.0,
            'whitelist_cnt': whitelist_cnt,
            'true_miss_cnt': true_cnt,
        },
        'top_candidates': candidates[:top_n],
        'candidate_total': len(candidates),
    }


def format_text(result):
    """文本报告（对齐 route_miss_report 风格）。"""
    s = result['summary']
    lines = [
        '=' * 60,
        '盲区 ROI 报告 — %d 条 trace' % s['total_traces'],
        '=' * 60,
        '盲区率: %.2f%% | 白名单: %d | 真实盲区: %d' % (
            s['blind_ratio'], s['whitelist_cnt'], s['true_miss_cnt']),
        '',
        'Top 候选（按 ROI 降序，%d 个聚类）:' % result['candidate_total'],
    ]
    for c in result['top_candidates']:
        lines.append('  [%s] %s: %d 次 (成本档%d, ROI %.2f)' % (
            c['roi_level'], c['prefix'], c['freq'], c['cost_tier'], c['roi_score']))
    lines.append('')
    lines.append('成本档说明: 1=DIRECT_MAP直连 2=触发词治理 3=NONE白名单/新建(需人工确认)')
    return '\n'.join(lines)


def main():
    days = None
    if '--days' in sys.argv:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    prefix = PREFIX_LEN
    if '--prefix' in sys.argv:
        prefix = int(sys.argv[sys.argv.index('--prefix') + 1])
    rows = load_traces(days, source='production')  # 只分析生产源（回归/adversarial 不算盲区）
    result = blind_spot_roi(rows, prefix_len=prefix)
    if '--json' in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))


if __name__ == '__main__':
    main()
