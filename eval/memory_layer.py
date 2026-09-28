#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_layer.py — L2 Memory Tree 上下文增强
===========================================
R162: 从 unified_router.py 拆出（五层模块化: direct/tag/BGE/memory/LLM）。
对外 API: memory_boost / extract_context_tags / _load_session_frequency
"""
import os
import json
import re
import datetime as _dt
from pathlib import Path
# （glob 已无引用，R208 O-8 ruff F401 清理）

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))

# 上下文标签→skill 映射（R14 收紧：去误触发关联 + 降低权重）
# R168: 删除了硬编码 USER_FAVORITES —— 用户偏好只采真实统计（生产 trace 优先/日志回退），
#       防止写死的元技能权重在每轮路由中静默放大（A-memory-start 0.95 / A-get-memory 0.85 等）。
#       实测危害: "分析评分/记忆/经验系统优劣" 因 A-get-memory 静态偏好 +0.051 被顶上 top1 且 needs_llm=false 静默放行。
# 原则：仅当标签语义直接对应skill功能时才映射，不含"可能相关"的混搭
# 2026-09-24 GitHub 对标轮清死目标：本表原有 7 个映射指向**已退役且磁盘/注册表均不存在**的
# skill（skill-install / skill-creator / cross-platform-skill-sync / fenjue-advisor-scoring /
# fenjue-routing-health-check / skill-hitrate-full-audit / skill-routing-test-driven-fix）。
# 语义澄清（防误判为"给不存在的技能加权"）：boost 只对**已在候选集内**的 skill 生效
# （见下方 `boost_map.get(c['name'])`），死目标从不进候选 ⇒ 从不加分，**删除属行为中性**。
# 真正的危害是**覆盖空洞**：这些意图标签事实上没有任何映射可用，只能裸靠 BGE 召回。
# 有同名现役技能可接替的（安装/创建/同步/评分/命中率）改指现役；无现役对位的（路由/提升）
# 显式留空并注明空洞，禁止用"语义相近"的技能凑数（凑数=静默误触发，比空洞更坏）。
CONTEXT_SKILL_MAP = {
    "报错": ["debugging-fixing"],
    "部署": ["chaoshi-web-deploy"],
    "记忆": ["A-get-memory", "A-memory-start", "fenjue-memory-audit"],
    "路由": [],            # 空洞：路由类技能已全部退役，暂无现役对位（见 07-next-steps P1-17）
    "编码": ["utf8-encoding-fix"],
    "乱码": ["utf8-encoding-fix", "shell-encoding-pitfalls"],
    "拆分": ["bigfile-split"],
    "拆小": ["bigfile-split"],
    "安装": ["A-skill-manager"],
    "装个": ["A-skill-manager"],
    "创建skill": ["A-skill-manager"],
    "写.*skill": ["A-skill-manager"],
    "同步": ["cross-platform-agent-sync"],
    "审计": ["fenjue-memory-audit", "prompt-system-audit"],
    "评分": ["fenjue-memory-audit"],
    "超市": ["chaoshi-web-deploy", "chaoshi-admin-inline-edit", "chaoshi-image-optimization"],
    "命中率": ["fenjue-lessons-hitrate"],   # 仅 lessons 域有现役对位；技能命中率域仍空洞
    "提升": [],            # 空洞：同「路由」
    "重构": ["refactoring"],   # R14: 去debugging-fixing（重构≠修bug）
    "测试": ["testing", "test-driven-development"],
    "debug": ["debugging-fixing"],
    "修复": ["debugging-fixing"],
    "分析": ["data-analysis", "consulting-analysis"],
    "报告": ["report-generator-skill", "consulting-analysis", "internal-comms"],
    "视频": ["video-frames", "video-whisper-transcribe"],
    "生成.*视频": ["byted-seedance-video-generate"],
    # R14: "图片"改为精确匹配（不含OCR相关query中的"图片"二字）
    # R201: local-* AIPC 系列已删，生图/图生图统一走 byted-seedream
    "生成.*图片": ["byted-seedream-image-generate"],
    "文生图": ["byted-seedream-image-generate"],
    "图生图": ["byted-seedream-image-generate"],
    "优化": ["A-prompt-better"],
    "画图": ["chart-visualization", "diagram-maker", "canvas-design"],
    "图表": ["chart-visualization", "data-visualization"],
    "表格": ["xlsx", "data-analysis"],
    "项目": ["A-project-handoff"],
    "交接": ["A-project-handoff"],
    "prompt": ["A-prompt-better"],
    "提示词": ["A-prompt-better"],
}

# 空值标签 = 已知覆盖空洞（有意保留键以维持 extract_context_tags 的匹配语义稳定，
# 但必须可被机器发现：verify C30 对本表所有非空目标做「必须存在于注册表活跃集」校验，
# 并统计空洞数与登记基线比对（只许减少，不许增加）。

def extract_context_tags(query: str) -> list[str]:
    """从 query 提取上下文标签（支持正则模式匹配，如 '生成.*视频'）"""
    tags = []
    for tag in CONTEXT_SKILL_MAP:
        try:
            if re.search(tag, query, re.IGNORECASE):
                tags.append(tag)
        except re.error:
            # 非正则模式→简单子串匹配
            if tag.lower() in query.lower():
                tags.append(tag)
    return tags

def memory_boost(candidates: list, query: str) -> list:
    """
    Memory Tree 上下文增强 — R18.2 动态版
    
    核心改进（R18.2 vs R14）:
    1. + 动态会话频率: 从 .workbuddy/memory/ 日志提取近7天 skill 使用频率
    2. + 时效衰减: 每过1天权重衰减 15%（8天后归零）
    3. 标签boost: 0.08（保持R14保守值）
    4. 偏好boost: weight*0.06（保持R14保守值）
    5. 保守守护: 若新Top-1 boost<0.10，恢复BGE原Top-1（保持R14）
    6. + 动态权重与静态偏好合并: max(静态, 动态频率*0.10)
    """
    # R168 守卫: 空候选直接返回（BGE/TF-IDF 全空时，旧代码在 bge_top1=candidates[0] 处 IndexError；
    # 动态频率非空后该路径被真实暴露——负例在 BGE 降级模式下崩溃）
    if not candidates:
        return candidates

    tags = extract_context_tags(query)
    
    # R18.2: 加载动态会话频率
    dynamic_freq = _load_session_frequency()

    if not tags and not dynamic_freq:
        return candidates

    # 收集需要 boost 的 skill（多标签交叉累加）
    boost_map: dict[str, float] = {}
    for tag in tags:
        for sk in CONTEXT_SKILL_MAP.get(tag, []):
            current = boost_map.get(sk, 0)
            boost_map[sk] = current + 0.08  # R14 保守值

    # R168: 动态频率 boost — 只采真实使用统计（生产 trace 优先/日志回退），删硬编码 USER_FAVORITES
    for sk, freq_weight in dynamic_freq.items():
        if sk in {c['name'] for c in candidates[:5]}:
            boost_map[sk] = boost_map.get(sk, 0) + freq_weight * 0.10

    # 应用 boost — 只在候选 skill 在 Top-3 时才提升（防误触发）
    top3_names = {c['name'] for c in candidates[:3]}
    boosted = []
    for c in candidates:
        b = boost_map.get(c['name'], 0)
        if b > 0 and c['name'] not in top3_names:
            b = b * 0.2  # 非Top-3降权
        new_score = min(c['score'] + b, 1.0)
        boosted.append({**c, 'score': round(new_score, 4), 'boost': round(b, 4)})

    boosted.sort(key=lambda x: -x['score'])

    # 保守原则: 若Memory Boost改变了Top-1且新Top-1 boost<=0.10
    # 则恢复BGE的Top-1（弱boost不该推翻语义正确的结果）
    # R21: < 改 <= — 单skill归一化boost恰=0.10可擦线翻盘（off-by-boundary实锤）
    bge_top1 = candidates[0]
    if boosted and boosted[0]['name'] != bge_top1['name']:
        top1_boost = boosted[0].get('boost', 0)
        if top1_boost <= 0.10:
            # 检查 bge_top1 是否还在 boosted 中
            if any(c['name'] == bge_top1['name'] for c in boosted):
                boosted.remove(next(c for c in boosted if c['name'] == bge_top1['name']))
            boosted.insert(0, bge_top1)

    return boosted


# ====== R18.2/R168: 动态会话频率 ======
# （R206-01: 删除此处重复的 import datetime as _dt / import glob as _glob_module——
#   L10-11 已有同名别名，重复 import 无运行时收益仅噪声）

_TRACE_FREQ_CACHE = {'ts': None, 'freq': None}
_EVAL_QUERY_CACHE = None
# R208 O-6 治本（P1-4）: eval 查询集指纹缓存——mtime 派生件而非每轮重读 4 个 eval json
_EVAL_QUERY_SOURCES = ('test_queries.json', 'layered_testset.json',
                       'blind_test_queries.json', 'frozen_blind_test.json')


def _eval_query_meta_path():
    return os.path.join(EVAL_DIR, '_cache', 'eval_queries.txt')


def _eval_source_mtimes():
    """4 个 eval 源文件的 mtime 指纹（缺失记 0，源变更即重算）。"""
    mtimes = {}
    for fn in _EVAL_QUERY_SOURCES:
        p = os.path.join(EVAL_DIR, fn)
        try:
            mtimes[fn] = os.path.getmtime(p)
        except OSError:
            mtimes[fn] = 0.0
    return mtimes


def _eval_fingerprint(mtimes):
    """指纹串: fn:mtime;fn:mtime（float repr 稳定性保证 roundtrip 相等）。"""
    return ";".join(f"{fn}:{mt}" for fn, mt in mtimes.items())


def _collect_eval_queries():
    """从 eval 源文件收集全部查询（仅在指纹失效时调用）。"""
    qset = set()
    for fn in _EVAL_QUERY_SOURCES:
        p = os.path.join(EVAL_DIR, fn)
        if not os.path.exists(p):
            continue
        try:
            data = json.loads(Path(p).read_text(encoding='utf-8'))
        except Exception:
            continue

        def collect(node):
            if isinstance(node, dict):
                q = node.get('query')
                if isinstance(q, str):
                    qset.add(q)
                for v in node.values():
                    collect(v)
            elif isinstance(node, list):
                for v in node:
                    collect(v)
        collect(data)
    return qset


def _known_eval_queries():
    """已知评估集 query 集合（去污染：历史 eval 曾以 production 身份写入 trace）。

    R208 O-6 治本: 查询集派生件 eval/_cache/eval_queries.txt（gitignore），
    首行是指纹（4 源 mtime），正常轮 = 4 次 getmtime + 一次纯文本读取（~0.4ms），
    源文件变更才重读 4 个 eval json + collect。原实现每子进程重读+递归收集。"""
    global _EVAL_QUERY_CACHE
    if _EVAL_QUERY_CACHE is not None:
        return _EVAL_QUERY_CACHE
    current = _eval_source_mtimes()
    fp = _eval_fingerprint(current)
    qset = None
    meta_path = _eval_query_meta_path()
    try:
        lines = Path(meta_path).read_text(encoding='utf-8').splitlines()
        if lines and lines[0] == '#E1 ' + fp:
            qset = set(lines[1:])
    except Exception:
        qset = None
    if qset is None:
        qset = _collect_eval_queries()
        try:
            os.makedirs(os.path.dirname(meta_path), exist_ok=True)
            Path(meta_path).write_text('#E1 ' + fp + '\n' + '\n'.join(sorted(qset)), encoding='utf-8')
        except Exception:
            pass  # 缓存写入失败降级为每次重建（功能不受损）
    _EVAL_QUERY_CACHE = qset
    return qset


def _normalize_freq(freq):
    """归一化到 0.0~1.0 + R21 证据压缩: 原始最高频<3次提及时按比例压缩，
    防止「单次提及→归一化1.0→满额boost」的弱证据强信号问题。"""
    if not freq:
        return {}
    max_freq = max(freq.values())
    damp = min(1.0, max_freq / 3.0)
    return {k: (v / max_freq) * damp for k, v in freq.items()}


def _load_trace_frequency(days=7):
    """R168 主源: 从 route_trace.jsonl 统计近 N 天 production 命中频率。
    - 只认 src=='production'（eval 已被隔离为不写入或 regression）
    - 排除已知评估集 query（清洗历史污染行，不删数据）
    - 时效衰减: 每天 15%，8 天后归零
    - 10 分钟缓存，避免每轮路由解析大 trace 文件"""
    global _TRACE_FREQ_CACHE
    now = _dt.datetime.now()
    if _TRACE_FREQ_CACHE['ts'] and (now - _TRACE_FREQ_CACHE['ts']).total_seconds() < 600:
        return _TRACE_FREQ_CACHE['freq']
    trace_path = os.path.join(EVAL_DIR, 'route_trace.jsonl')
    freq = {}
    if os.path.exists(trace_path):
        eval_qs = _known_eval_queries()
        try:
            # R206-01: 尾读替代全量扫——trace 按时间追加、文件尾部即近期记录；
            # 1MB 窗口覆盖近几天 production 量级，更早条目日衰减 15%（第 8 天归零）
            # 对 boost 贡献可忽略。冷启动省最大 10MB 全文件逐行 json.loads
            # （该成本随 trace 增长线性恶化）。
            tail_bytes = 1024 * 1024
            fsize = os.path.getsize(trace_path)
            with Path(trace_path).open('rb') as f:
                if fsize > tail_bytes:
                    f.seek(-tail_bytes, os.SEEK_END)
                    f.readline()  # 丢弃被截断的半行
                raw = f.read()
            for line in raw.decode('utf-8', errors='replace').splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get('src', 'production') != 'production':
                        continue
                    q = r.get('q') or ''
                    if q in eval_qs:
                        continue
                    name = r.get('top1')
                    if not name or name == 'NONE':
                        continue
                    ts = r.get('ts', '')
                    try:
                        day = _dt.datetime.fromisoformat(ts).date()
                    except Exception:
                        day = None
                    if day is not None:
                        age = (now.date() - day).days
                        if age < 0 or age > days:
                            continue
                    decay = max(0.15, 1.0 - age * 0.15) if day is not None else 1.0
                    freq[name] = freq.get(name, 0) + decay
        except Exception:
            freq = {}
    freq = _normalize_freq(freq)
    _TRACE_FREQ_CACHE['ts'] = now
    _TRACE_FREQ_CACHE['freq'] = freq
    return freq


# 日志扫描用 skill 名正则（模块级预编译：原实现在 7 天回退循环体内逐日重编译同一模式）
_SKILL_LOG_PATTERN = re.compile(
    r'`([a-zA-Z][a-zA-Z0-9_-]*skill[a-zA-Z0-9_-]*|'
    r'[a-zA-Z][a-zA-Z0-9_-]*Skill[a-zA-Z0-9_-]*|'
    r'fenjue-[a-z0-9-]+|A-[a-z0-9-]+|chaoshi-[a-z0-9-]+|byted-[a-z0-9-]+)`',
    re.IGNORECASE)


def _load_log_frequency(days=7):
    r"""R168 回退源: 日志中的 skill 使用行（动态路径修正 —— 旧代码硬编码
    `焚诀\.workbuddy\memory` 不存在，导致动态频率恒为空）。
    候选路径按优先级: 项目级 → 用户级真实 WB 日志 → <MEMORY_ROOT>\memory 权威源。"""
    candidates = [
        os.path.join(os.path.dirname(EVAL_DIR), '.workbuddy', 'memory'),
        os.path.join(os.path.expanduser('~'), '.workbuddy', 'memory'),
        os.path.join('D:', os.sep, 'global_memory', 'memory'),
    ]
    memory_dir = next((p for p in candidates if os.path.isdir(p)), None)
    if not memory_dir:
        return {}
    freq = {}
    now = _dt.datetime.now()
    for i in range(days):
        day = now - _dt.timedelta(days=i)
        log_file = os.path.join(memory_dir, day.strftime('%Y-%m-%d') + '.md')
        if not os.path.exists(log_file):
            continue
        try:
            content = Path(log_file).read_text(encoding='utf-8')
        except Exception:
            continue
        decay = max(0.15, 1.0 - i * 0.15)
        usage_lines = [ln for ln in content.split('\n')
                       if ('加载' in ln or '实跑' in ln or '使用审计' in ln or 'Skill(' in ln)]
        scan_text = '\n'.join(usage_lines)
        for match in _SKILL_LOG_PATTERN.finditer(scan_text):
            name = match.group(1)
            freq[name] = freq.get(name, 0) + decay
    return _normalize_freq(freq)


def _load_session_frequency():
    """动态频率: 生产 trace 为主源，trace 为空时回退日志扫描（R168）。"""
    freq = _load_trace_frequency()
    if not freq:
        freq = _load_log_frequency()
    return freq
