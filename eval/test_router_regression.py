#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_router_regression.py — unified_router 基础回归测试
=====================================================
用法: python test_router_regression.py [--verbose]

分层验证:
  T1: 模块导入
  T2: DIRECT_MAP 直连层 (纯正则, 无ML依赖)
  T3: route() 全管线 (需 sentence_transformers, 不可用时 SKIP)
  T4: easy 层命中率 (需 BGE)
  T5: medium 层命中率 (需 BGE)

退出码: 0=通过(含SKIP), 1=有FAIL
"""
import importlib.util
import os
import sys
import json
import time

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EVAL_DIR)

VERBOSE = '--verbose' in sys.argv or '-v' in sys.argv

def log(msg):
    if VERBOSE:
        print(f"  {msg}")

def has_bge():
    """检查 BGE 依赖是否可用（R209: find_spec 探测，免 import 副作用）"""
    return importlib.util.find_spec("sentence_transformers") is not None

def main():
    print("=" * 60)
    print("unified_router 回归测试")
    print("=" * 60)
    failures = []
    skips = []
    t0 = time.time()

    # --- T1: 导入 ---
    print("\n[T1] 导入 unified_router ...")
    try:
        import unified_router
        unified_router.TRACE_SOURCE = 'regression'  # 防测试数据污染生产 trace
        print("  PASS")
    except Exception as e:
        print(f"  FAIL: {e}")
        sys.exit(1)

    # --- T2: DIRECT_MAP 直连层 (无ML依赖) ---
    print("\n[T2] DIRECT_MAP 直连层 ...")
    # 校准: 每条 case 必须匹配 unified_router.py DIRECT_MAP 中的实际正则
    direct_cases = [
        # R193: 直连缺口补回（盲测漂移，2026-08-12）
        ("苹果和香蕉哪个热量高", "NONE"),
        ("同步一下", "A-skill-manager"),
        ("写邮件", "internal-comms"),
        ("换主题", "theme-factory"),
        ("报错了", "debugging-fixing"),
        ("生成Word", "docx"),
        ("sqlite 打开数据库文件", "data-analysis"),
        ("帮我一键部署静态网站到 CDN", "byted-bp-cdn-pagesdeploy"),
        ("Obsidian 白板 canvas 文件编辑", "json-canvas"),
        ("MCP 服务器配置和认证管理", "mcporter"),
        ("帮我在 Obsidian 里搜索笔记", "obsidian-cli"),
        ("obsidian CLI 搜索 vault 笔记", "obsidian-cli"),
        ("OpenClaw 派活全程监工含重试验证", "openclaw-task-supervision"),
        ("帮我在 Notion 里做综合调研文档", "research-documentation"),
        ("用 gh 创建 issue", "github"),
        ("ntn 创建 Notion 页面", "notion-cli"),
        ("PPT 提取文字做演讲稿", "pptx"),
        # 超市部署 (多条 pattern 覆盖)
        ("超市部署", "chaoshi-web-deploy"),
        ("超市上线", "chaoshi-web-deploy"),
        ("咋部署", "chaoshi-web-deploy"),
        ("deploy一下", "chaoshi-web-deploy"),
        # debug 口语化
        ("页面白屏", "debugging-fixing"),
        ("网站打不开", "debugging-fixing"),
        ("程序闪退了", "debugging-fixing"),
        ("功能坏掉了", "debugging-fixing"),
        ("应用卡死了", "debugging-fixing"),
        # 存储
        ("存储不够了", "c-cleanup"),
        ("空间不够了", "c-cleanup"),
        # 文档
        ("合并PDF", "pdf"),
        ("PDF拆分", "pdf"),
        ("写个PPT", "pptx"),
        ("写个word文档", "docx"),
        # 数据
        ("excel数据分析", "xlsx"),
        ("画个柱状图", "chart-visualization"),
        # 研究
        ("深度研究", "consulting-analysis"),  # R-fix(2026-09-22): deep-research-pro 已退役 → 研究报告类落 consulting-analysis
        ("天眼查一下", "天眼一下"),
        # 本地（R201 local-* 已删，转替代技能）
        ("做个网页", "frontend-skill"),
        ("识别图片文字", "windows-native-ocr"),
        # 系统
        ("路由健康检查", "A-skill-manager"),
        ("大文件拆分", "bigfile-split"),
        ("跨平台skill同步", "A-skill-manager"),
        # 记忆
        ("经验反哺", "A-get-memory"),
        # 媒体
        ("ffmpeg抽帧", "video-frames"),
        ("视频加字幕", "video-whisper-transcribe"),
        # Web
        ("github创建PR", "github"),
        # 闲聊 → NONE
        ("你好", "NONE"),
        ("讲个笑话", "NONE"),
    ]
    direct_hits = 0
    for query, expected in direct_cases:
        try:
            result = unified_router.direct_route(query)
            if result == expected:
                direct_hits += 1
                log(f"  OK: '{query}' -> {result}")
            else:
                log(f"  MISS: '{query}' expected={expected} got={result}")
                failures.append(f"T2: '{query}' expected={expected} got={result}")
        except Exception as e:
            failures.append(f"T2: '{query}' 异常 - {e}")
            log(f"  ERR: '{query}' - {e}")
    rate = direct_hits / len(direct_cases) * 100
    if rate >= 90:
        print(f"  PASS: {direct_hits}/{len(direct_cases)} ({rate:.0f}%)")
    else:
        print(f"  FAIL: {direct_hits}/{len(direct_cases)} ({rate:.0f}%), 要求>=90%")
        if not any(f.startswith("T2") for f in failures):
            failures.append(f"T2: 直连命中率 {rate:.0f}% < 90%")

    # --- T3-T5: 需要 BGE ---
    bge_available = has_bge()
    if not bge_available:
        print("\n[T3-T5] BGE 全管线测试 ...")
        print("  SKIP: sentence_transformers 未安装, 跳过 BGE 层测试")
        print("  提示: pip install sentence-transformers 后可运行全量测试")
        skips.append("T3-T5: BGE 依赖不可用")
    else:
        # T3: route() 结构完整性
        print("\n[T3] route() 返回结构 ...")
        try:
            result = unified_router.route("帮我装个 skill")
            required_keys = ['query', 'top1', 'candidates']
            missing = [k for k in required_keys if k not in result]
            if missing:
                failures.append(f"T3: 缺少字段 {missing}")
                print(f"  FAIL: 缺少字段 {missing}")
            else:
                print(f"  PASS: top1={result['top1']}")
        except Exception as e:
            failures.append(f"T3: {e}")
            print(f"  FAIL: {e}")

        # T4: easy 层
        print("\n[T4] test_queries.json easy 层 ...")
        test_file = os.path.join(EVAL_DIR, 'test_queries.json')
        if not os.path.exists(test_file):
            print("  SKIP: test_queries.json 不存在")
            skips.append("T4: 测试集不存在")
        else:
            with open(test_file, 'r', encoding='utf-8') as f:
                test_data = json.load(f)
            easy_tier = next((t for t in test_data if t.get('tier') == 'easy'), None)
            if not easy_tier:
                print("  SKIP: 无 easy 层")
                skips.append("T4: 无 easy 层数据")
            else:
                queries = easy_tier.get('queries', [])
                hits = 0
                for item in queries:
                    q, expected = item.get('query', ''), item.get('expected_skill', '')
                    try:
                        r = unified_router.route(q)
                        if r.get('top1', '') == expected:
                            hits += 1
                            log(f"  OK: '{q}' -> {r['top1']}")
                        else:
                            log(f"  MISS: '{q}' expected={expected} got={r.get('top1','')}")
                    except Exception as e:
                        log(f"  ERR: '{q}' - {e}")
                rate = hits / len(queries) * 100 if queries else 0
                if rate < 90:
                    failures.append(f"T4: easy {rate:.1f}% < 90%")
                print(f"  {'PASS' if rate >= 90 else 'FAIL'}: {hits}/{len(queries)} ({rate:.1f}%)")

        # T5: medium 层
        print("\n[T5] test_queries.json medium 层 ...")
        if os.path.exists(test_file):
            medium_tier = next((t for t in test_data if t.get('tier') == 'medium'), None)
            if not medium_tier:
                print("  SKIP: 无 medium 层")
                skips.append("T5: 无 medium 层数据")
            else:
                queries = medium_tier.get('queries', [])
                hits = 0
                for item in queries:
                    q, expected = item.get('query', ''), item.get('expected_skill', '')
                    try:
                        r = unified_router.route(q)
                        if r.get('top1', '') == expected:
                            hits += 1
                            log(f"  OK: '{q}' -> {r['top1']}")
                        else:
                            log(f"  MISS: '{q}' expected={expected} got={r.get('top1','')}")
                    except Exception as e:
                        log(f"  ERR: '{q}' - {e}")
                rate = hits / len(queries) * 100 if queries else 0
                if rate < 80:
                    failures.append(f"T5: medium {rate:.1f}% < 80%")
                print(f"  {'PASS' if rate >= 80 else 'FAIL'}: {hits}/{len(queries)} ({rate:.1f}%)")

    # --- Summary ---
    elapsed = time.time() - t0
    print("\n" + "=" * 60)
    if failures:
        print(f"RESULT: FAIL ({len(failures)} failures, {len(skips)} skips, {elapsed:.1f}s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        skip_note = f", {len(skips)} skips" if skips else ""
        print(f"RESULT: ALL PASS{skip_note} ({elapsed:.1f}s)")
        sys.exit(0)

if __name__ == '__main__':
    main()
