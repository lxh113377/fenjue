#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
unified_router.py — 统一路由桥接层（组装层，R162 五层模块化）
==================================================================
管线: L0 领域分类(domain_classifier) → L0.1 直连(direct_layer)
      → L0.5 Tag(tag_layer) → L1 BGE(bge_layer) → L2 Memory(memory_layer)
      → L3 LLM(llm_layer)

用法:
  python unified_router.py "用户查询"
  python unified_router.py --json "用户查询"   # JSON输出
  python unified_router.py --eval              # 跑全量评估
"""
import os
import sys
import json
import re
import threading
import time

from bge_layer import _load_bge, tfidf_score, ensemble_rerank, bge_recall  # noqa: F401  re-export/历史兼容
from direct_layer import DIRECT_MAP, direct_route, _load_direct_map  # noqa: F401
from tag_layer import (NEGATIVE_TAG_MAP, EXPLICIT_ONLY, tag_filter,  # noqa: F401  NEGATIVE_TAG_MAP 等被 test_not_use_boundary re-export
                       negative_filter_candidates, _build_negative_index,
                       _NEGATIVE_SKILL_TAGS)
from memory_layer import memory_boost
from llm_layer import get_skill_profile, build_llm_decision_prompt, _should_llm_decide  # noqa: F401
import route_cache  # noqa: E402  7-A: 跨进程结果缓存（治 D-19 每进程重载模型）

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))


# ====== L0: 领域分类 ======
try:
    from domain_classifier import classify_domain
except ImportError:
    # R212: 收敛——不再内联复制关键词表与 classify_domain（双份权威长期并存
    # 有漂移风险）；降级为「领域判定缺失」返回 None，路由继续走 Tag/BGE 召回。
    classify_domain = None

# ====== 高频直连映射表（L0.1: 关键词→skill精确映射，短路全部路由） ======
# 来源: eval盲区分析 + 测试用例 pattern→skill 映射
# 规则: 命中后直接返回，跳过 L0→L3 全部层

SYNONYM_MAP = [
    ("屎山|烂代码|意大利面.*代码|代码.*捋顺|捋顺.*代码|理顺.*代码", "重构 代码结构优化 refactor"),
    ("幻灯片|简报|keynote", "ppt 演示文稿 slides"),
    ("灵感|点子|发散.*想|想.*创意|创意.*发散|脑洞", "头脑风暴 brainstorm 构思"),
    ("腾.*地方|腾.*空间|磁盘.*满|磁盘.*爆|C盘.*满|空间.*不够|硬盘.*满", "磁盘清理 C盘清理 释放空间"),
    ("上次.*聊|接着.*上次|继续.*上次|新窗口.*接着|上回.*说到", "项目交接 会话续接 handoff 交接"),
    ("使用习惯|你记了.*啥|关于我.*记|我的.*偏好.*记", "用户画像 个人记忆 偏好档案"),
    ("交叉复核|另一个.*模型.*复核|别的.*模型.*看看|第二.*意见", "oracle 第二模型 复审 review"),
    ("藏着.*命令行|隐藏.*cli|挖.*命令行|命令行.*挖", "electron 桌面应用 cli 发现 discover"),
    ("行业调研|市场调研|深度调研|全面.*调研", "深度研究 deep research 多源"),
    ("虚拟机.*起不来|vm.*启动.*失败|沙箱.*坏|虚拟机.*救", "虚拟机 沙箱 错误恢复 recovery"),
    ("转写", "转录 语音识别 音频转文字"),
    ("白板", "canvas 画布 json-canvas"),
    ("排版.*编辑|编辑.*排版", "布局 编辑 修改"),
    ("指令.*重写|重写.*指令|这条.*指令.*规范|提示词.*规范", "提示词优化 prompt 优化 改写"),
    ("派给|派活|外包给", "委派 分派 delegate"),
    # P1-7（2026-09-23）：口语化「记录经验」路由缺口修复 —— 实测 acceptance 用例 A09
    # 「把这次踩的坑记到经验库里」未命中 A-get-memory（top1 落到 oracle/code-review）；
    # 补口语同义词（保留原文 + 追加规范词），使语义召回可命中经验反哺技能。
    ("记.*经验|踩的坑|踩坑|沉淀.*经验|经验.*沉淀|总结.*经验|经验.*总结|经验反哺", "经验反哺 A-get-memory 记忆写入 记录踩坑"),
]
_SYNONYM_COMPILED = None

def normalize_query(query):
    """R20: 口语归一化 — 命中同义词模式则在 query 后追加规范词（保留原文）。"""
    global _SYNONYM_COMPILED
    if _SYNONYM_COMPILED is None:
        _SYNONYM_COMPILED = [(re.compile(p, re.IGNORECASE), w) for p, w in SYNONYM_MAP]
    extra = []
    for cre, words in _SYNONYM_COMPILED:
        if cre.search(query):
            extra.append(words)
    return (query + " " + " ".join(extra)) if extra else query

def route(query: str, top_k: int = 5, enable_memory: bool = True, enable_llm: bool = True, enable_tags: bool = True) -> dict:
    """
    统一路由: L0领域→L0.5Tag过滤→L1 BGE召回→L2 Memory增强→L3 LLM决策提示词
    
    层:
      L0:    领域分类 (domain_classifier)
      L0.5:  Tag精确过滤 (skill_tags.json) — 新! 精准匹配时短路BGE
      L1:    BGE-zh Full-Body 语义召回
      L2:    Memory Tree 上下文增强
      L3:    LLM 决策提示词构建

    参数:
      query: 用户查询
      top_k: BGE 召回 Top-K
      enable_memory: 是否启用 Memory 上下文增强
      enable_llm: 是否构建 LLM 决策提示词
      enable_tags: 是否启用 Tag 过滤层 (L0.5)

    返回: {
      'query': str,
      'domain': str,
      'tag_hits': list|None,  # Tag匹配的skill列表
      'candidates': [{name, score, domain, boost}, ...],
      'top1': str,
      'llm_prompt': dict,
    }
    """
    # L0.1: 高频直连映射（短路全部路由；R20: 内置 NOT USE 守卫防过度短路）
    direct = direct_route(query)
    if direct:
        result = {
            'query': query,
            'domain': None,
            'tag_hits': [direct],
            'candidates': [{'name': direct, 'score': 1.0, 'domain': 'direct', 'boost': 0.0}],
            'top1': direct,
            'llm_prompt': None,
            'direct_hit': True,
            'confidence': 'HIGH',
        }
        _trace(result)
        return result

    # R20: 口语同义词归一化（仅用于分类/编码，原 query 保留）
    norm_query = normalize_query(query)

    # L0: 领域分类（domain_classifier 不可达时降级为 None，走 Tag/BGE 召回）
    domain = classify_domain(norm_query) if classify_domain is not None else None
    tag_hits = None

    # L0.5: Tag 精确过滤（新!）
    if enable_tags:
        tag_hits = tag_filter(norm_query, domain)
    
    candidates = bge_recall(norm_query, tag_hits, domain, top_k, raw_query=query)

    # L1.7: TF-IDF 确定性检索 ensemble（BGE不确定区间时投票）
    candidates = ensemble_rerank(candidates, norm_query)

    # L1.9: R20 负标签终段守卫 — ensemble/兜底可能把 neg_hit 候选重新抬上来，
    # 终段强制: 未命中负标签的候选永远排在命中者之前；随后截断回 top_k。
    candidates = sorted(candidates, key=lambda c: (c.get('neg_hit', False), -c['score']))[:top_k]

    # L2: Memory 上下文增强
    if enable_memory:
        candidates = memory_boost(candidates, norm_query)

    # L2.5: R20 置信度三档分层（视频方法论"置信度分层"落地）
    #   HIGH   >=0.45          → 自动执行（沿用原逻辑）
    #   MEDIUM 0.32~0.45       → 不硬杀：needs_llm=True 消歧 / 生产端追问用户
    #   LOW    <0.32           → 判定 NONE（无需skill）
    # 治盲测教训: vm-error-recovery(0.3275) 被旧 0.40 一刀切硬杀。
    confidence = 'HIGH'
    if candidates and not tag_hits:
        top1_score = candidates[0]['score']
        if top1_score < 0.32:
            result = {
                'query': query,
                'domain': domain,
                'tag_hits': None,
                'candidates': candidates,
                'top1': 'NONE',
                'llm_prompt': None,
                'needs_llm_decision': False,
                'llm_reason': f"LOW置信({top1_score:.3f}<0.32)，判定为无需skill",
                'direct_hit': False,
                'confidence': 'LOW',
            }
            _trace(result)
            return result
        elif top1_score < 0.45:
            confidence = 'MEDIUM'

    # L3: LLM 决策提示词
    llm_prompt = None
    needs_llm = False
    llm_reason = ""

    if enable_llm:
        # 判断是否需要 LLM 决策（R18.2: 常态化触发条件）
        needs_llm, llm_reason = _should_llm_decide(candidates, domain, query)
        # R20: MEDIUM 档强制走 LLM 消歧（不再直接放行）
        if confidence == 'MEDIUM' and not needs_llm:
            needs_llm, llm_reason = True, f"MEDIUM置信({candidates[0]['score']:.3f}∈[0.32,0.45))强制LLM消歧"
        if needs_llm:
            llm_prompt = build_llm_decision_prompt(query, candidates)

    result = {
        'query': query,
        'domain': domain,
        'tag_hits': tag_hits,
        'candidates': candidates,
        'top1': candidates[0]['name'] if candidates else None,
        'llm_prompt': llm_prompt,
        'needs_llm_decision': needs_llm,
        'llm_reason': llm_reason,
        'direct_hit': False,
        'confidence': confidence,
    }
    _trace(result)
    return result

ROUTE_TRACE_PATH = os.path.join(EVAL_DIR, 'route_trace.jsonl')
TRACE_ENABLED = os.environ.get('FENJUE_ROUTE_TRACE', '1') == '1'
TRACE_SOURCE = os.environ.get('FENJUE_TRACE_SOURCE', 'production')  # 生产默认; 回归测试 import/环境变量改为 'regression'
_ROUTE_TRACE_MAX_BYTES = 10 * 1024 * 1024  # R162: 超 10MB 轮转
_ROUTE_TRACE_KEEP = 5                      # R162: 保留最近 5 份


def _gzip_plain(path):
    """R207 N4: 把未压缩的明文 trace 旧份压成 .gz（幂等、失败不影响路由）。

    - 目标已为 .gz（或不存在）→ 跳过
    - 明文与 .gz 并存（异常重复态）→ 删明文保留 .gz
    """
    if not path.endswith('.gz') and os.path.exists(path):
        gz = path + '.gz'
        try:
            if os.path.exists(gz):
                os.remove(path)          # 已压缩过，清重复明文
                return
            import gzip
            with open(path, 'rb') as fi, gzip.open(gz, 'wb', compresslevel=6) as fo:
                fo.write(fi.read())
            os.remove(path)
        except Exception:
            pass  # 压缩失败不影响路由


def _rotate_trace():
    """R162: trace 文件超 10MB 时滚动，保留最近数份，防无限膨胀。
    R207 N4: 轮转落位的编号 >=2 旧份压缩为 .gz（磁盘占用 ~-90%）。
    注: 轮转域为 .2~.5（i=1 时主文件直接落位 .2），.1 不参与。"""
    try:
        if not (os.path.exists(ROUTE_TRACE_PATH)
                and os.path.getsize(ROUTE_TRACE_PATH) >= _ROUTE_TRACE_MAX_BYTES):
            return
        for i in range(_ROUTE_TRACE_KEEP - 1, 0, -1):
            src = ROUTE_TRACE_PATH if i == 1 else f'{ROUTE_TRACE_PATH}.{i}'
            dst = f'{ROUTE_TRACE_PATH}.{i + 1}'
            if os.path.exists(dst):
                os.remove(dst)
            if os.path.exists(src):
                os.replace(src, dst)
        for i in range(2, _ROUTE_TRACE_KEEP + 1):
            _gzip_plain(f'{ROUTE_TRACE_PATH}.{i}')
    except Exception:
        pass  # 轮转失败不影响路由

def _trace(result):
    """每次真实路由追加一行 jsonl。src 字段区分 production/regression。
    miss 反馈: eval/route_miss_report.py 消费此文件（默认只分析 production）。"""
    if not TRACE_ENABLED:
        return
    try:
        import datetime
        rec = {
            'ts': datetime.datetime.now().isoformat(timespec='seconds'),
            'src': TRACE_SOURCE,
            'q': result['query'],
            'top1': result.get('top1'),
            'confidence': result.get('confidence'),
            'direct': result.get('direct_hit', False),
            'needs_llm': result.get('needs_llm_decision', False),
            'top3': [c['name'] for c in result.get('candidates', [])[:3]],
            'scores': [c['score'] for c in result.get('candidates', [])[:3]],
        }
        _rotate_trace()
        with open(ROUTE_TRACE_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass  # trace 失败不影响路由

def _active_skill_set():
    # 在役 skill 集（注册表为准，R263 计分口径修正用）；读不到返回 None 退回旧口径
    p = os.path.join(os.path.dirname(EVAL_DIR), 'skill', 'registry',
                     'unified-skills-index.json')
    try:
        with open(p, encoding='utf-8') as f:
            return set(json.load(f)['skills'])
    except Exception:
        return None


def run_eval(test_path=None):
    """跑全量评估 — R18.2: 四层全管线 (直连→Tag+NOT USE→BGE→Memory动态)"""
    if test_path is None:
        test_path = os.path.join(EVAL_DIR, 'test_queries.json')

    with open(test_path, 'r', encoding='utf-8') as f:
        test_data = json.load(f)

    queries = []
    negatives = []
    for tier in test_data:
        for q in tier['queries']:
            if tier.get('tier') == 'negative':
                negatives.append(q)
            elif q.get('expected_skill') and q.get('routable', True):
                queries.append(q)

    _load_bge()

    # 各层独立统计
    direct_hits = 0
    correct_top1_bge = 0
    correct_top3_bge = 0
    correct_top1_mem = 0
    correct_top3_mem = 0
    llm_recommend_count = 0

    active = _active_skill_set()
    stale = 0  # R263：期望技能不在役（退役/未登记）→ 不可达，剔除并单列
    scored = []
    for q in queries:
        exp0 = q['expected_skill']
        exp_set0 = {exp0} if isinstance(exp0, str) else set(exp0)
        if active and not (exp_set0 & active):
            stale += 1
            continue
        scored.append(q)
    raw_n = len(queries)
    queries = scored

    for q in queries:
        expected = q['expected_skill']
        expected_set = {expected} if isinstance(expected, str) else set(expected)

        # 全管线 (直连→Tag→BGE→Memory)
        result = route(q['query'], enable_memory=True, enable_llm=True)
        
        if result.get('direct_hit'):
            direct_hits += 1
        
        if result.get('needs_llm_decision'):
            llm_recommend_count += 1
        
        if result['top1'] in expected_set:
            correct_top1_mem += 1
        top3_mem = [c['name'] for c in result['candidates'][:3]]
        if any(n in expected_set for n in top3_mem):
            correct_top3_mem += 1

        # BGE-only (无直连/无Tag/无Memory)
        result_bge = route(q['query'], enable_memory=False, enable_llm=False, enable_tags=False)
        if result_bge['top1'] in expected_set:
            correct_top1_bge += 1
        top3_bge = [c['name'] for c in result_bge['candidates'][:3]]
        if any(n in expected_set for n in top3_bge):
            correct_top3_bge += 1

    n = len(queries)
    bge_mem_delta = correct_top1_mem - correct_top1_bge

    return {
        'total': n,
        'direct_hits': direct_hits,
        'direct_rate': round(direct_hits / n * 100, 1) if n > 0 else 0,
        'llm_recommend': llm_recommend_count,
        'llm_recommend_rate': round(llm_recommend_count / n * 100, 1) if n > 0 else 0,
        'bge_only': {
            'top1': round(correct_top1_bge / n * 100, 1) if n > 0 else 0,
            'top3': round(correct_top3_bge / n * 100, 1) if n > 0 else 0,
            'correct': correct_top1_bge,
        },
        'full_pipeline': {
            'top1': round(correct_top1_mem / n * 100, 1) if n > 0 else 0,
            'top3': round(correct_top3_mem / n * 100, 1) if n > 0 else 0,
            'correct': correct_top1_mem,
        },
        'pipeline_delta': round(bge_mem_delta / n * 100, 1) if n > 0 else 0,
        # R263 双披露：stale_expected = 期望技能不在役而剔除的用例数；
        # raw_top1 把剔除项计为 miss（旧口径），便于与历史数字对照。
        'stale_expected': stale,
        'raw_total': raw_n,
        'raw_top1': round(correct_top1_mem / raw_n * 100, 1) if raw_n > 0 else 0,
    }


# ====== CLI ======
def _legacy_cli():
    # R207 N1 修复: TRACE_ENABLED/TRACE_SOURCE 需 global 声明——否则函数内赋值仅
    # 是局部遮蔽，模块级常量（import 时由 env 求值）不受影响，R168"eval 不写
    # 生产 trace"意图失效（--eval 仍以 production 身份污染 route_trace.jsonl）。
    global TRACE_ENABLED, TRACE_SOURCE
    if '--eval' in sys.argv:
        # R168: eval 一律不写生产 trace（历史缺陷: scorecard 调 --eval 未关 trace，
        # 66+ 条测试查询以 production 身份污染 route_trace.jsonl，D27/miss 分析失真）
        os.environ['FENJUE_ROUTE_TRACE'] = '0'
        TRACE_ENABLED = False
        TRACE_SOURCE = 'regression'
        print("=" * 70)
        print("统一路由器评估 (R18.2: 直连→Tag+NOTUSE→BGE→Memory动态→LLM)")
        print("=" * 70)

        metrics = run_eval()
        
        bge = metrics['bge_only']
        full = metrics['full_pipeline']
        
        print(f"\n📊 直连映射层 (DIRECT_MAP {len(DIRECT_MAP)}条):")
        print(f"  命中: {metrics['direct_hits']}/{metrics['total']} = {metrics['direct_rate']}%")
        
        print("\n📊 基础管线 (BGE-only, 无直连/Tag/Memory):")
        print(f"  Top-1: {bge['top1']}% | Top-3: {bge['top3']}% ({bge['correct']}/{metrics['total']})")
        
        print("\n📊 全管线 (直连+Tag+NOTUSE+BGE+Memory动态):")
        print(f"  Top-1: {full['top1']}% | Top-3: {full['top3']}% ({full['correct']}/{metrics['total']})")
        
        delta_sign = "+" if metrics['pipeline_delta'] > 0 else ""
        print("\n📊 全管线 vs BGE-only 边际贡献:")
        print(f"  {delta_sign}{metrics['pipeline_delta']}pp {'✅ 正贡献' if metrics['pipeline_delta'] >= 0 else '❌ 负贡献'}")
        
        print("\n📊 LLM 决策推荐率:")
        print(f"  {metrics['llm_recommend']}/{metrics['total']} = {metrics['llm_recommend_rate']}% 推荐走LLM消歧")
        
        print(f"\n🎯 目标: Top-1 ≥ 95% | {'✅ 达成' if full['top1'] >= 95 else '⬜ 未达成（差' + str(round(95 - full['top1'], 1)) + 'pp）'}")

    elif '--json' in sys.argv:
        # R20 Task#3: CLI --json 即生产入口(A-memory-start Step 4.7), 默认落trace闭环。
        # 评测走 import route() 不经此分支, 不受影响; 显式 FENJUE_ROUTE_TRACE=0 可关。
        if os.environ.get('FENJUE_ROUTE_TRACE') != '0':
            TRACE_ENABLED = True
        args = [a for a in sys.argv[1:] if a != '--json']
        llm_choice = None
        if '--llm-choice' in args:
            i = args.index('--llm-choice')
            if i + 1 < len(args):
                llm_choice = args[i + 1]
                del args[i:i + 2]
        query = ' '.join(args) if args else '检查路由有没有毛病'
        cache_key = None
        if llm_choice is None and route_cache.enabled():
            # --llm-choice 是消歧结果回写调用，非一次新决策，不入缓存面
            cache_key = route_cache.make_key(query, {"cli": "json"})
            cached = route_cache.lookup(cache_key)
            if cached is not None:
                cached.setdefault('query', query)
                print(json.dumps(cached, ensure_ascii=False, indent=2))
                return
        result = route(query)
        out = {
            'query': result['query'],
            'domain': result['domain'],
            'top1': result['top1'],
            'direct_hit': result.get('direct_hit', False),
            'needs_llm': result.get('needs_llm_decision', False),
            'llm_reason': result.get('llm_reason', ''),
            'candidates': result['candidates'],
            'llm_prompt_full': result['llm_prompt']['full'] if result['llm_prompt'] else None,
        }
        if llm_choice:
            # R120: LLM 消歧结果回写 trace（agent 读 llm_prompt 后传最终选择）
            bge_top1 = result['top1']
            out['llm_choice'] = llm_choice
            out['llm_agree'] = (llm_choice == bge_top1)
            out['llm_corrected'] = (llm_choice != bge_top1)
            if TRACE_ENABLED:
                try:
                    import datetime
                    rec = {
                        'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                        'src': 'llm_decision',
                        'q': result['query'],
                        'bge_top1': bge_top1,
                        'llm_choice': llm_choice,
                        'agree': out['llm_agree'],
                        'corrected': out['llm_corrected'],
                        'needs_llm': result.get('needs_llm_decision', False),
                        'reason': result.get('llm_reason', ''),
                    }
                    with open(ROUTE_TRACE_PATH, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                except Exception:
                    pass  # llm_choice 回写 trace 失败不影响本次输出（R207 P2-1 留痕）
        if cache_key is not None:
            route_cache.store(cache_key, {k: out[k] for k in out})
        print(json.dumps({
            k: out[k] for k in out
        }, ensure_ascii=False, indent=2))

    else:
        query = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else '检查路由有没有毛病'
        result = route(query)

        print(f"查询: {result['query']}")
        print(f"L0 领域: {result['domain']}")
        if result.get('direct_hit'):
            print(f"⚡ 直连命中: {result['top1']} (跳过全部路由)")
        elif result.get('needs_llm_decision'):
            print(f"⚠️  建议LLM消歧: {result.get('llm_reason', '')}")
        
        print("\nL1 BGE 召回 Top-5:")
        print(f"{'排名':<6} {'Skill':<45} {'相似度':>6} {'增强':>6}")
        print("-" * 68)
        for i, c in enumerate(result['candidates'], 1):
            boost_str = f"+{c['boost']:.3f}" if c.get('boost', 0) > 0 else "-"
            print(f"{i:<6} {c['name']:<45} {c['score']:>6.4f} {boost_str:>6}")

        print(f"\nL1 默认选择: {result['top1']}")

        if result['llm_prompt']:
            print(f"\n{'='*65}")
            print("L3 LLM 决策提示词 (not_for边界→消歧):")
            print(f"{'='*65}")
            print(result['llm_prompt']['full'])


class RouteTimeout(RuntimeError):
    """--timeout 内部超时（R192）：外部 15s 护栏降级为兜底。"""


class TimeoutGuard:
    """单调时钟 deadline，可在关键路径点主动抛 RouteTimeout。"""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.deadline = time.monotonic() + seconds

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise RouteTimeout(f"route timeout after {self.seconds}s (R192 内部保障)")


def _start_watchdog(guard):
    """看门狗：BGE/encode 等不可中断调用挂起时，由进程级退出兜底（124）。

    R198.11 修复（2026-08-16）：watchdog 线程须可取消——否则 cli_main 正常返回后
    线程残留，daemon 线程在 guard.deadline 到达时无条件 os._exit(124) 强杀宿主进程
    （pytest 整目录跑被 test_router_timeout 的 5s watchdog 残留杀死，rc=124，15.8s）。
    返回 (thread, stop_event)；调用方返回前必须 stop_event.set()。
    """
    if guard is None:
        return None, None

    stop_event = threading.Event()

    def _watch():
        while not stop_event.is_set():
            left = guard.deadline - time.monotonic()
            if left <= 0:
                sys.stderr.write(
                    f"[unified_router] TIMEOUT: 超过 {guard.seconds}s（watchdog 强制终止）\n"
                )
                sys.stderr.flush()
                os._exit(124)
            time.sleep(min(left, 0.05))

    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    return t, stop_event


def _parse_timeout(argv):
    """解析 --timeout N（秒）。返回 (timeout, cleaned) 或 (None, None) 表示参数错误。"""
    cleaned = []
    timeout = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--timeout':
            if i + 1 >= len(argv):
                print('--timeout 需要秒数参数', file=sys.stderr)
                return None, None
            try:
                timeout = float(argv[i + 1])
            except ValueError:
                print('--timeout 参数必须是数字（秒）', file=sys.stderr)
                return None, None
            if timeout <= 0:
                print('--timeout 必须为正数', file=sys.stderr)
                return None, None
            i += 2
            continue
        cleaned.append(a)
        i += 1
    return timeout, cleaned


def cli_main(argv):
    """CLI 入口（可测）：解析 --timeout 后复用 _legacy_cli，RouteTimeout → 退出码 124。"""
    timeout, args = _parse_timeout(argv)
    if args is None:
        return 2
    old_argv = sys.argv
    sys.argv = [old_argv[0]] + args
    guard = TimeoutGuard(timeout) if timeout is not None else None
    wd_thread, wd_stop = _start_watchdog(guard)
    try:
        try:
            _legacy_cli()
        except RouteTimeout as e:
            if '--json' in args:
                print(json.dumps({
                    'schema': 'fenjue-router-v1',
                    'error': 'timeout',
                    'timeout_seconds': guard.seconds if guard else None,
                    'degraded': True,
                    # P1-7: 超时必须可操作 —— 给出两条已验证的降级/自检路径
                    'hint': '① 首查为 BGE 冷加载慢 → 复跑一次通常恢复；'
                            '② 持续超时 → 设 FENJUE_BGE_DISABLE=1 走 TF-IDF 确定性降级后排查 onnx 模型/缓存',
                }, ensure_ascii=False))
            else:
                print(f"[unified_router] TIMEOUT: {e}", file=sys.stderr)
            return 124
        return 0
    finally:
        # P0-6: finally 兜底 —— 任何异常路径也必取消 watchdog 并 join，
        # 防残留线程 os._exit 强杀宿主（R198.11 pytest rc=124 复发根因）
        sys.argv = old_argv
        if wd_stop is not None:
            wd_stop.set()
        if wd_thread is not None:
            wd_thread.join(timeout=1.0)


if __name__ == '__main__':
    sys.exit(cli_main(sys.argv[1:]))
