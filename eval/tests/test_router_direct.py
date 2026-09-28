#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_router_direct.py — 路由直连层(DIRECT_MAP) 回归（CI 可跑，无 ML 依赖）

迁移自 eval/test_router_regression.py 的 T2 直连层，改为 pytest 参数化。
语义层(BGE/LLM)仍由 CI 带 sentence_transformers 的 job 或 mock 契约测试覆盖。
"""
import pytest

try:
    import unified_router
except ImportError as e:
    # unified_router 顶层 import 会拉起 bge_layer(sklearn/numpy)。
    # 无 ML 依赖的 CI job 应跳过直连层，而非中断收集（与项目"无 BGE 则 SKIP"一致）。
    pytest.skip(f"ML 依赖缺失，跳过路由直连层测试: {e}", allow_module_level=True)

unified_router.TRACE_SOURCE = 'regression'  # 防测试数据污染生产 trace

# (query, expected_skill) — 直连映射层纯正则，零 ML 依赖
DIRECT_CASES = [
    ("超市部署", "chaoshi-web-deploy"),
    ("超市上线", "chaoshi-web-deploy"),
    ("页面白屏", "debugging-fixing"),
    ("网站打不开", "debugging-fixing"),
    ("程序闪退了", "debugging-fixing"),
    ("存储不够了", "c-cleanup"),
    ("合并PDF", "pdf"),
    ("PDF拆分", "pdf"),
    ("写个PPT", "pptx"),
    ("写个word文档", "docx"),
    ("excel数据分析", "xlsx"),
    ("画个柱状图", "chart-visualization"),
    # R278（2026-09-22）：deep-research-pro 已退役（在 truth_constants.retired_skills 内、
    # 磁盘与注册表均无、tag_layer 已转为负标签）→ 研究报告类落 consulting-analysis。
    # 本行原为 ("深度研究", "deep-research-pro")，属**退役未回扫**：同目录
    # test_router_regression.py:99 当日已改为 consulting-analysis（带注释），本文件漏改，
    # 导致 test_router_direct 恒 FAIL。实测 direct_route('深度研究') == 'consulting-analysis'。
    ("深度研究", "consulting-analysis"),
    ("做个网页", "frontend-skill"),
    ("设计网站前端", "frontend-skill"),
    ("路由健康检查", "A-skill-manager"),
    ("跨平台skill同步", "A-skill-manager"),
    ("经验反哺", "A-get-memory"),
    ("github创建PR", "github"),
]


@pytest.mark.parametrize("query,expected", DIRECT_CASES)
def test_direct_route_known(query, expected):
    assert unified_router.direct_route(query) == expected


@pytest.mark.parametrize("query", ["你好", "讲个笑话", "今天天气怎么样"])
def test_direct_route_chitchat_returns_none(query):
    assert unified_router.direct_route(query) == 'NONE'


# R194: 规划/方案/补漏计划类消息不得路由到 A-prompt-better（提示词类触发已收窄）
PLANNING_CASES = [
    "帮我优化一下这个项目方案，列出补漏执行计划",
    "把我列的26条问题逐一对照我已有的自建skill:A-project-handoff已有机制,输出覆盖/部分/缺口/结论+补漏执行计划,把5个skill的串联固化",
    "帮我想个方案，优化一下流程",
]


@pytest.mark.parametrize("query", PLANNING_CASES)
def test_planning_queries_never_route_prompt_better(query):
    assert unified_router.direct_route(query) != "A-prompt-better"


def test_original_planning_message_routes_to_ask_questions():
    """R194 回归：26 条问题对照消息 → A-ask-questions（不得是 A-prompt-better）。"""
    q = "把我列的26条问题逐一对照我已有的自建skill:A-project-handoff已有机制,输出覆盖/部分/缺口/结论+补漏执行计划"
    assert unified_router.direct_route(q) == "A-ask-questions"
    result = unified_router.route(q, enable_llm=False)
    assert result["top1"] == "A-ask-questions"


def test_full_route_planning_not_prompt_better():
    result = unified_router.route("帮我优化一下这个项目方案，列出补漏执行计划", enable_llm=False)
    assert result["top1"] != "A-prompt-better"
