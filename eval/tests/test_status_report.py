#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""status_report 冒烟测试（R209-2③ 补测簇：315 stmts 0% → 冒烟覆盖）。

覆盖: _is_overdue 边界 / compute_tracking_stats 统计口径 / split_status 指针壳契约。
"""
import datetime
import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import status_report as sr


def test_is_overdue_past_true():
    past = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    assert sr._is_overdue(past) is True


def test_is_overdue_future_false():
    future = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    assert sr._is_overdue(future) is False


def test_is_overdue_garbage_false():
    # 解析失败视为未超期（不误伤）
    assert sr._is_overdue('') is False
    assert sr._is_overdue('not-a-date') is False
    assert sr._is_overdue(None) is False


def test_compute_tracking_stats_empty():
    stats = sr.compute_tracking_stats([])
    assert stats == {'total': 0, 'unclosed': 0, 'overdue': 0,
                     'escape_overdue': 0, 'no_owner': 0, 'refuted': 0}


def test_compute_tracking_stats_mixed():
    past = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    future = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
    defects = [
        {'status': 'open', 'deadline': past, 'owner': '未指派'},   # 未闭环+超期+无负责人
        {'status': 'open', 'deadline': future, 'owner': '张三'},   # 仅未闭环
        {'status': 'open', 'escape_hatch_deadline': past, 'owner': '李四'},  # 逃生门超期
        {'status': 'closed', 'resolution': 'refuted'},             # 已证伪
        {'status': 'closed', 'resolution': 'fixed'},               # 正常闭环
    ]
    stats = sr.compute_tracking_stats(defects)
    assert stats['total'] == 5
    assert stats['unclosed'] == 3
    assert stats['overdue'] == 1
    assert stats['escape_overdue'] == 1
    assert stats['no_owner'] == 1
    assert stats['refuted'] == 1


def test_split_status_shell_contract():
    content = (
        '# 正文标题\n'
        '当前轮次: R210\n'
        '机器实测综合: 120/150\n'
        '普通正文行不应进入摘要\n'
        '门禁总判定: PASS\n'
    )
    shell, part = sr.split_status(content, '2026-09-04T02:00:00')
    assert '指针壳' in shell
    assert '机器实测综合: 120/150' in shell          # 摘要行必须保留（cross_layer_audit 依赖）
    assert '当前轮次: R210' in shell
    assert '门禁总判定: PASS' in shell
    assert '普通正文行不应进入摘要' not in shell      # 非摘要行不进壳
    assert part == content                            # 正文完整保留给 part1
