#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_layer.py — L3 LLM 决策层（提示词构建 + needs_llm 触发判定）
==============================================================
R162: 从 unified_router.py 拆出（五层模块化: direct/tag/BGE/memory/LLM）。
R162.1: 并轨 llm_decision_layer.py — 迁移 analyze_failure_patterns（生产 route 版）。
对外 API: get_skill_profile / build_llm_decision_prompt / _should_llm_decide /
          analyze_failure_patterns
"""
import os
import json
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = r'<SKILLS_ROOT>'

# ====== Skill 描述提取（用于 LLM 决策） ======
def _extract_frontmatter_description(body):
    """从 YAML frontmatter 提取 description（支持 | 多行块），无则返回 ''。"""
    if not body.startswith('---'):
        return ''
    end = body.find('\n---', 3)
    if end < 0:
        return ''
    lines = body[3:end].split('\n')
    collect = False
    parts = []
    for ln in lines:
        s = ln.strip()
        if s.startswith('description:'):
            collect = True
            rest = s[len('description:'):].strip()
            if rest and rest not in ('|', '>-', '>', '|-'):
                parts.append(rest)
            continue
        if collect:
            if ln[:1] in (' ', '\t'):
                parts.append(s)
            else:
                break
    return ' '.join(p for p in parts if p)


def get_skill_profile(name, max_chars=300):
    """提取 skill 的结构化描述"""
    profile = {
        'name': name, 'domain': 'unknown', 'sub_domain': '',
        'description': '', 'triggers': [], 'not_for': [],
    }

    # 从 BGE index 获取 domain
    # 延迟 import 破循环（bge_layer → tag_layer；此处运行时 bge_layer 已加载完毕）
    # R163 降级兼容: BGE 未加载(禁用/加载失败)时直接读索引 JSON, 不依赖模型状态
    import bge_layer
    if not bge_layer._bge_skills:
        try:
            bge_layer._bge_skills = json.loads(Path(os.path.join(EVAL_DIR, 'bge_fullbody_skills.json')).read_text(encoding='utf-8'))
        except Exception:
            bge_layer._bge_skills = []
    for s in bge_layer._bge_skills:
        if s['name'] == name:
            profile['domain'] = s.get('domain', 'unknown')
            profile['sub_domain'] = s.get('sub_domain', '')
            break

    # 从 SKILL.md 提取描述
    md_path = os.path.join(SKILLS_DIR, name, 'SKILL.md')
    if os.path.exists(md_path):
        body = Path(md_path).read_text(encoding='utf-8')
        desc = _extract_frontmatter_description(body)
        if not desc:
            # 回退：正文扫描（跳过 frontmatter 与 ROUTER 分支表）
            if body.startswith('---'):
                end = body.find('---', 3)
                if end > 0:
                    body = body[end + 3:].strip()
            lines = body.split('\n')
            desc_lines = []
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                if stripped.startswith('## 🧭'):
                    break
                desc_lines.append(stripped)
                if len(' '.join(desc_lines)) > max_chars:
                    break
            desc = ' '.join(desc_lines)
        profile['description'] = desc[:max_chars].strip()

        # 提取 NOT USE / 不适用
        for line in body.split('\n'):
            lower = line.lower()
            if any(kw in lower for kw in ['not use', '不适用', 'when not', 'do not use', 'not for']):
                profile['not_for'].append(line.strip())

        # 提取触发词（从 frontmatter 或正文）
        for line in body.split('\n'):
            if '触发词' in line or 'trigger' in line.lower():
                profile['triggers'].append(line.strip())

    return profile


DISAMBIG_PATH = os.path.join(EVAL_DIR, 'disambiguation_pairs.json')


def _load_disambiguation_pairs():
    """加载自动生成的消歧规则（eval/disambiguation_pairs.json）。"""
    try:
        data = json.loads(Path(DISAMBIG_PATH).read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _disambiguation_hints(names):
    """候选名单命中消歧表时返回可读提示行（降低 LLM 冷推理依赖，提高可审计性）。"""
    name_set = set(names)
    hints = []
    for pair in _load_disambiguation_pairs():
        a, b = pair.get('a', ''), pair.get('b', '')
        if a in name_set and b in name_set:
            use_a = (pair.get('use_a_when') or '').strip()
            use_b = (pair.get('use_b_when') or '').strip()
            hints.append(f"- {a} vs {b}: 用 {a} 当 {use_a}；用 {b} 当 {use_b}")
    return hints


def build_llm_decision_prompt(query, candidates):
    """构建 LLM 决策提示词"""
    profiles = []
    for c in candidates[:5]:
        profile = get_skill_profile(c['name'])
        profiles.append((c, profile))

    candidate_lines = []
    for i, (c, p) in enumerate(profiles, 1):
        desc = p['description'][:200] if p['description'] else '(无描述)'
        not_for = '; '.join(p['not_for'][:2]) if p['not_for'] else '(无)'
        boost_info = f" (+{c['boost']:.3f} 上下文)" if c.get('boost', 0) > 0 else ""

        candidate_lines.append(
            f"{i}. **{p['name']}** (领域:{p['domain']}, 相似度:{c['score']:.3f}{boost_info})\n"
            f"   描述: {desc}\n"
            f"   不适用: {not_for}"
        )

    hints = _disambiguation_hints([prof['name'] for _, prof in profiles])
    hints_section = ''
    if hints:
        hints_section = (
            "\n\n已知消歧规则（自动生成，来源 eval/disambiguation_pairs.json）:\n"
            + '\n'.join(hints)
        )

    system_prompt = """你是 Skill 路由决策器。根据用户查询，从候选 Skill 中选择最匹配的一个。

决策规则（按优先级）:
1. 触发词优先 — 查询中包含某skill的触发词，权重最高
2. 意图理解 — "报错怎么修"→debugging, "项目交接"→handoff, "咋装"→install
3. 注意不适用场景 — 候选标注了"不适用/别用我"且查询匹配 → 排除
4. 口语化理解 — "拆小"=拆分, "上线"=部署, "画个图"=图表
5. 上下文加分 — 标注了"+上下文"的候选表示与用户偏好/历史相关，可适当提升
6. 消歧规则优先 — 已知消歧规则命中的对子，按规则选，不要凭相似度反复横跳
7. 输出格式: **只输出 skill 名称，不要解释。**"""

    user_prompt = f"""用户查询: "{query}"

候选 Skill (按语义相似度排序):
{chr(10).join(candidate_lines)}{hints_section}

请选择最匹配用户意图的 Skill。只输出名称。"""

    return {
        'system': system_prompt,
        'user': user_prompt,
        'full': f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}"
    }



def _should_llm_decide(candidates, domain, query):
    """
    R18.2: LLM 决策层常态化触发判定。
    当一个或多个条件满足时，标记需要 LLM 参与消歧。
    
    条件（满足任一即触发）:
    1. Top-3 差分 < 0.03（几乎并列，BGE 无力区分）
    2. Top-1 分数 < 0.45（所有候选置信度都低）
    3. 查询含明确"修复/修理/修"但 Top-1 是诊断类 skill（意图错位）
    4. 查询字数 ≤4 且同时命中 ≥2 个领域（口语化模糊表达）
    7. (R168) top1 是出口/元技能(A-get-memory/A-memory-start 等)但查询含审计类动作词 → 意图错位
    """
    if not candidates or len(candidates) < 2:
        return False, ""

    scores = [c['score'] for c in candidates[:3]]
    
    # 条件1: Top-3 分数接近（差分<0.03）
    if len(scores) >= 2 and (scores[0] - scores[1]) < 0.03:
        return True, f"Top-3几乎并列 (diff={scores[0]-scores[1]:.4f})"
    
    # 条件2: Top-1 置信度过低
    if scores[0] < 0.45:
        return True, f"Top-1置信度过低 ({scores[0]:.3f})"
    
    # 条件3: 查询含"修复/修"但 Top-1 是诊断/审计类 skill
    fix_kw = ['修复', '修理', '修一下', '修好', 'fix']
    diagnose_patterns = ['diagnos', 'audit', 'health-check', '审计']
    if any(kw in query for kw in fix_kw):
        top1_name = candidates[0]['name']
        if any(p in top1_name for p in diagnose_patterns):
            return True, f"查询含修复意图但Top-1是诊断类skill ({top1_name})"
    
    # 条件5 (R18.2): 中长查询(≥8字)且 Top-3 全部低置信度
    # R163: 候选不足 3 条时按实际条数格式化, 防 IndexError（降级路径实测抓到的崩溃）
    if len(query) >= 8 and len(scores) >= 2 and all(s < 0.50 for s in scores):
        shown = '/'.join(f'{s:.3f}' for s in scores)
        return True, f"Top-{len(scores)}全低置信度 ({shown})"
    
    # 条件6 (R18.2): 含"画图/画个图"但 Top-1 不是 chart/algorithmic → 可能偏
    drawing_kw = ['画个图', '画图', '画一张', '画什么']
    if any(kw in query for kw in drawing_kw):
        top1_name = candidates[0]['name']
        if any(p in top1_name for p in ['diagram', 'frontend', 'canvas']):
            return True, f"画图类模糊查询，Top-1={top1_name}可能偏"

    # 条件7 (R168): 意图错位 — top1 是出口/元技能但查询含审计类动作词，强制 LLM 消歧。
    # 根因实证: "分析我的系统的优劣性（包括评分系统，记忆技能检索系统，经验lesson指导系统）"
    # 被路由到 A-get-memory(出口反哺技能) 且 needs_llm=false 静默放行，
    # 正确目标 fenjue-memory-audit/fenjue-advisor-scoring 在候选池却未被消歧。
    meta_exit_skills = {
        'A-get-memory', 'A-memory-start', 'A-project-handoff',
        'A-ask-questions', 'A-prompt-better', 'find-skills',
    }
    audit_action_kw = ['审计', '评分', '分析', '评估', '检查', '复盘',
                       '优化', '优劣', '机制', '健康', '审查', 'review']
    top1_name = candidates[0]['name']
    if top1_name in meta_exit_skills and any(kw in query for kw in audit_action_kw):
        return True, f"意图错位: top1为出口/元技能({top1_name})但查询含审计类动作词"

    return False, ""


def analyze_failure_patterns(test_queries_path, output_path=None):
    """
    分析生产管线失败 case 的模式，生成 LLM 决策示例。

    R162.1: 由 llm_decision_layer.py 迁移并升级——改跑生产 unified_router.route()
    （含直连/Tag/负标签/Memory/置信度分层），替代旧版简化管线
    （route_with_llm: 仅域分类+BGE召回）。
    """
    # 延迟 import 破循环（unified_router → llm_layer）；分析走 regression 防污染生产 trace
    import unified_router as _ur
    _ur.TRACE_SOURCE = 'regression'
    route = _ur.route

    test_data = json.loads(Path(test_queries_path).read_text(encoding='utf-8'))

    queries = []
    for tier in test_data:
        for q in tier['queries']:
            if q.get('expected_skill') and q.get('routable', True):
                queries.append(q)

    failures = []
    for q in queries:
        expected = q['expected_skill']
        expected_set = {expected} if isinstance(expected, str) else set(expected)
        query_text = q['query']

        result = route(query_text)
        top1 = result['top1']
        candidates = result.get('candidates', [])[:5]
        names = [c['name'] for c in candidates]
        scores = {c['name']: c['score'] for c in candidates}

        if top1 not in expected_set:
            # 检查Oracle: 预期 skill 是否在候选池内
            oracle = any(n in expected_set for n in names)

            # 构建 LLM 提示词（llm_layer 新 API: dict {system, user, full}）
            prompt = build_llm_decision_prompt(query_text, candidates)

            failures.append({
                'query': query_text,
                'expected': expected,
                'bge_top1': top1,
                'bge_top5': [(n, scores.get(n, 0.0)) for n in names],
                'oracle': oracle,
                'domain': result.get('domain'),
                'llm_prompt': prompt['full'] if prompt else None,
            })

    # 输出分析
    print('=' * 70)
    print('失败Case分析 — 供LLM决策层参考（生产管线 route()）')
    print('=' * 70)
    print(f'总失败: {len(failures)}/{len(queries)}')
    print(f'其中Oracle可达: {sum(1 for f in failures if f["oracle"])}/{len(failures)}')
    print()

    # 按失败类型分组
    patterns = {}
    for f in failures:
        bge_top1 = f['bge_top1']
        expected = f['expected']

        if not f['oracle']:
            pattern = '召回失败: 预期skill不在Top-5中'
        elif bge_top1.startswith('skill-') and expected.startswith('skill-'):
            pattern = '同名前缀混淆: 多个skill-*难以区分'
        elif bge_top1.startswith('fenjue-') or expected.startswith('fenjue-'):
            pattern = '焚诀内部skill混淆'
        elif 'local-' in bge_top1 and 'local-' in expected:
            pattern = 'local系列混淆'
        else:
            pattern = '语义相近但功能不同'

        patterns.setdefault(pattern, []).append(f)

    for pattern, cases in sorted(patterns.items(), key=lambda x: -len(x[1])):
        print(f'\n📌 {pattern} ({len(cases)}条)')
        for c in cases[:3]:
            print(f'  查询: "{c["query"]}" → 预期:{c["expected"]}, BGE选:{c["bge_top1"]}, '
                  f'Oracle:{"✓" if c["oracle"] else "✗"}')

    # 输出LLM提示词示例（前3条）
    print('\n' + '=' * 70)
    print('🤖 LLM决策提示词示例（可直接喂给LLM测试）')
    print('=' * 70)
    for i, f in enumerate(failures[:3], 1):
        print(f'\n--- Case {i}: "{f["query"]}" ---')
        print(f'预期: {f["expected"]} | BGE选了: {f["bge_top1"]}')
        print(f'\n[USER]\n{(f["llm_prompt"] or "")[:800]}...')

    if output_path:
        Path(output_path).write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\n✅ 失败Case已导出: {output_path}')

    return failures


if __name__ == '__main__':
    import sys

    if '--analyze' in sys.argv:
        test_path = os.path.join(EVAL_DIR, 'test_queries.json')
        out_path = os.path.join(EVAL_DIR, 'llm_failure_cases.json')
        analyze_failure_patterns(test_path, out_path)
    else:
        print('用法:')
        print('  python llm_layer.py --analyze    # 分析生产管线失败Case')
