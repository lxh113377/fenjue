#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对抗路由测试（R194）：注入/越权/恶意路径 query 不触发执行类 skill，路由不崩。"""

import json
import os
import sys

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import unified_router as ur  # noqa: E402

ur.TRACE_SOURCE = "adversarial"  # 防测试数据污染生产 trace

ADV_JSON = os.path.join(EVAL_DIR, "adversarial_queries.json")

# 执行类 skill：路由命中即可能触发外部动作/写操作
EXECUTION_SKILLS = {
    "chaoshi-web-deploy",
    "cloudbase-webapp-deploy-debug",
    "byted-bp-cdn-pagesdeploy",
    "byted-seedream-image-generate",
    "byted-seedance-video-generate",
    "byted-mediakit-shared",
    "office-automation-pro",
    "wechat-automation",
    "imagegen",
}


def load_queries():
    with open(ADV_JSON, encoding="utf-8") as fh:
        data = json.load(fh)
    return data


def test_at_least_8_entries():
    assert len(load_queries()) >= 8


@pytest.mark.parametrize("entry", load_queries(), ids=lambda e: e.get("id", "?"))
def test_adversarial_query_never_routes_execution_skill(entry):
    query = entry["query"]
    assert ur.direct_route(query) not in EXECUTION_SKILLS
    result = ur.route(query, enable_llm=False)
    assert result["top1"] not in EXECUTION_SKILLS


def test_runner_queries_min_15():
    import sys
    EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, EVAL_DIR)
    import adversarial_test as at
    assert len(at.load_adversarial_queries()) >= at.MIN_ADV_ENTRIES


def test_runner_edge_robustness():
    import sys
    EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, EVAL_DIR)
    import adversarial_test as at
    out = at.check_edge_robustness()
    assert out["pass"] is True
