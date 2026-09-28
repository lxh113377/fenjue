#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feedback 自动分类契约测试（R196，覆盖-4 / 八.1）。"""

import os
import sys

FEEDBACK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "feedback")
sys.path.insert(0, os.path.abspath(FEEDBACK_DIR))

import app as fb  # noqa: E402


def test_classify_direction():
    assert fb.classify_feedback("完全理解错了方向，跑偏了") == "方向理解"


def test_classify_tool():
    assert fb.classify_feedback("skill 没加载，工具不存在") == "工具调用"


def test_classify_memory():
    assert fb.classify_feedback("记忆断片了，续接不上上下文") == "记忆续接"


def test_classify_code():
    assert fb.classify_feedback("代码运行报错，traceback 异常") == "代码结果"


def test_classify_eval():
    assert fb.classify_feedback("这个评分误判了，分给低了") == "评测判定"


def test_classify_other():
    assert fb.classify_feedback("今天天气不错") == "其他"


def test_route_suggestions_all_categories():
    for cat in fb.CATEGORIES:
        assert fb.route_feedback(cat)
