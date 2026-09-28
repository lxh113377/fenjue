#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_layered_testset.py — 分层盲测集构建与校验（R163 批2）
====================================================================
目标结构（冻结不调参）:
  - skills 层: 每 skill ≥1 条（144/144）, 复用现有 90 skill 用例 + 缺口自动草稿
  - cli 层:    CLI 型查询 ≥20%（git/npm/pip/ffmpeg/python/node 等）
  - short 层:  短查询（≤8 字）≥20%
  - fault_finding 层: 找茬（模糊/多义/口语化/边界）≥15 条 — 常驻盲区探针
  - negative 层: negative/blindspot ≥10 条

护栏:
  - 覆盖/比例/去重校验不过 → 拒绝写入
  - 默认 dry-run, --write 才落盘（--force 跳过校验错误仅提示）

用法:
  python build_layered_testset.py            # 校验并打印统计（dry-run）
  python build_layered_testset.py --write    # 生成 layered_testset.json
"""
import os
import sys
import json
import glob
import re
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
SC_DIR = r'<MEMORY_ROOT>\skill_content'
OUT = os.path.join(EVAL_DIR, 'layered_testset.json')


def load_skills():
    skills = {}
    for f in sorted(glob.glob(os.path.join(SC_DIR, '*.json'))):
        if os.path.basename(f) == 'skill_ids.json':
            continue
        dom = os.path.basename(f)[:-5]
        d = json.loads(Path(f).read_text(encoding='utf-8'))
        for s in d.get('skills', []):
            skills[s['name']] = {'domain': dom, 'triggers': s.get('triggers', []), 'desc': s.get('desc', '')}
    return skills


def load_existing():
    """既有集子中每个 skill 的第一条可用用例"""
    by_skill = {}
    for p in ['test_queries.json', 'blind_test_queries.json', 'frozen_blind_test.json']:
        d = json.loads(Path(os.path.join(EVAL_DIR, p)).read_text(encoding='utf-8'))
        for t in d:
            if t.get('tier') == 'negative':
                continue
            for q in t.get('queries', []):
                e = q.get('expected_skill')
                if isinstance(e, str) and e not in by_skill:
                    by_skill[e] = {'query': q['query'], 'expected_skill': e, 'judge': q.get('judge', 'exact'),
                                   'source': os.path.basename(p)}
    return by_skill


def load_negatives():
    neg = []
    for p in ['test_queries.json', 'blind_test_queries.json']:
        d = json.loads(Path(os.path.join(EVAL_DIR, p)).read_text(encoding='utf-8'))
        for t in d:
            if t.get('tier') != 'negative':
                continue
            for q in t.get('queries', []):
                neg.append({'query': q['query'], 'expected_skill': None, 'judge': 'blindspot',
                            'source': os.path.basename(p)})
    seen = set()
    uniq = []
    for q in neg:
        if q['query'] not in seen:
            seen.add(q['query'])
            uniq.append(q)
    return uniq


# ===== 策展清单（批2 人工起草） =====
CLI_QUERIES = [
    ('用ffmpeg把视频转成gif动图', 'video-frames'),
    ('ffmpeg 截取视频前10秒', 'video-frames'),
    ('ffmpeg 从视频提取音频转文字', 'video-whisper-transcribe'),
    ('ffmpeg 合并两个视频', 'byted-mediakit-shared'),
    ('用 curl 调用 OpenAI 语音转写 API', 'openai-whisper-api'),
    ('curl 拉取 GitHub 上的技能包', 'skill-install'),
    ('git 提交代码并推送', 'github'),
    ('用 gh 创建 issue', 'github'),
    ('git 回滚上一个提交', 'github'),
    ('用 gh 检查 CI 状态', 'github'),
    ('用 gh 提 PR', 'github'),
    ('npm 安装技能缺的依赖', 'install-skill-dependency'),
    ('pip 安装 requirements 后报错', 'install-skill-dependency'),
    ('node --inspect 排查 CPU 飙高', 'node-inspect-debugger'),
    ('python pdb 断点调试', 'python-debugpy'),
    ('python 读取 Excel 文件', 'xlsx'),
    ('python 生成 docx 文档', 'docx'),
    ('python 合并 PDF', 'pdf'),
    ('python 画 matplotlib 交互图', 'data-visualization'),
    ('python 写个定时任务脚本', 'taskflow'),
    ('node 写个定时脚本', 'taskflow'),
    ('sqlite3 查询数据表', 'data-analysis'),
    ('mysql 导出数据做透视', 'data-analysis'),
    ('p5.js 创作生成艺术', 'algorithmic-art'),
    ('npx hyperframes 渲染视频合成', 'hyperframes-cli'),
    ('npx 安装 HF 组件', 'hyperframes-registry'),
    ('ntn 创建 Notion 页面', 'notion-cli'),
    ('obsidian CLI 搜索 vault 笔记', 'obsidian-cli'),
    ('用 tyc 命令查企业背景', '天眼一下'),
    ('用 oracle 命令二审代码', 'oracle'),
    ('无头浏览器跑表单测试', 'gstack'),
    ('截个屏', 'screenshot'),
    ('tcb hosting 部署超市前端', 'chaoshi-web-deploy'),
    ('cloudbase 云函数部署后订单不显示', 'chaoshi-web-deploy'),
    ('静态站点批量替换图片路径', 'static-site-batch-audit-fix'),
    ('ffmpeg 批量压缩图片转 WebP', 'chaoshi-image-optimization'),
    ('mediakit-cli 剪辑视频加背景音乐', 'byted-mediakit-shared'),
    ('用 Seedance 生成视频', 'byted-seedance-video-generate'),
    ('用 Seedream 生成图片', 'byted-seedream-image-generate'),
    ('whisper 转录本地音频', 'video-whisper-transcribe'),
    ('Codex 委派编码任务给后台', 'coding-agent'),
    ('discover 找桌面应用的隐藏 CLI', 'discover-agent-cli'),
    ('Electron 自动化操作 VS Code', 'electron'),
    ('浏览器自动填表单', 'agent-browser'),
    ('本地 tts 生成语音文件', 'byted-mediakit-shared'),
    ('whisper 转录音频', 'openai-whisper-api'),
    ('识别图片文字', 'byted-seedream-image-generate'),
    ('silk 解码微信语音转文字', 'wechat-voice-transcription'),
    ('powershell 中文乱码修复', 'shell-encoding-pitfalls'),
    ('git bash 里跑 python 报 extglob 错', 'windows-bash-cli-interop-pitfalls'),
    ('subprocess 调用 CLI 输出乱码', 'windows-cli-utf8-wrapper'),
    ('Git Bash 调用 node 中文路径报错', 'windows-gitbash-chinese-path-pit'),
    ('重建 BGE 嵌入矩阵', 'embedding-index-alignment'),
    ('wsl 里跑 ffmpeg 转码', 'video-frames'),
    ('用 gh 看仓库 PR 列表', 'github'),
    ('sqlite 打开数据库文件', 'data-analysis'),
    ('python 写个定时任务监控文件夹', 'taskflow'),
    ('npm 装 shadcn 组件', 'shadcn'),
    ('curl 下载中文文件名乱码', 'shell-encoding-pitfalls'),
    ('用 claude 无头模式协作写文档', 'doc-coauthoring'),
]

SHORT_QUERIES = [
    ('C盘满了', 'c-cleanup'),
    ('报错了', 'debugging-fixing'),
    ('写测试', 'testing'),
    ('跑测试', 'testing'),
    ('重构代码', 'refactoring'),
    ('画个图表', 'chart-visualization'),
    ('做海报', 'byted-seedream-image-generate'),
    ('做PPT', 'pptx'),
    ('读Excel', 'xlsx'),
    ('生成Word', 'docx'),
    ('编辑PDF', 'nano-pdf'),
    ('读PDF', 'pdf'),
    ('录音转文字', 'video-whisper-transcribe'),
    ('文字转语音', 'byted-mediakit-shared'),
    ('识别图片文字', 'byted-seedream-image-generate'),
    ('微信语音转写', 'wechat-voice-transcription'),
    ('总结一下', 'A-get-memory'),
    ('加载记忆', 'A-memory-start'),
    ('拆分文件', 'bigfile-split'),
    ('写周报', 'internal-comms'),
    ('写邮件', 'internal-comms'),
    ('写实施计划', 'writing-plans'),
    ('头脑风暴', 'brainstorming'),
    ('优化提示词', 'A-prompt-better'),
    ('新建技能', 'create-skill'),
    ('找技能', 'find-skills'),
    ('装技能', 'skill-install'),
    ('删技能', 'skill-manager'),
    ('合并技能', 'skill-merge'),
    ('审计提示词', 'prompt-system-audit'),
    ('路由健康', 'fenjue-routing-health-check'),
    ('记忆审计', 'fenjue-memory-audit'),
    ('经验反哺', 'A-get-memory'),
    ('同步技能', 'cross-platform-skill-sync'),
    ('规则同步', 'cross-platform-agent-sync'),
    ('深度调研', 'deep-research-pro'),
    ('多引擎搜索', 'multi-search-engine'),
    ('公司调查', '天眼一下'),
    ('一起写技术文档', 'doc-coauthoring'),
    ('画架构图', 'diagram-maker'),
    ('画脑图', 'diagram-maker'),
    ('做落地页', 'frontend-skill'),
    ('写个页面', 'frontend-skill'),
    ('UI设计', 'ui-ux-pro-max'),
    ('换主题', 'theme-factory'),
    ('数据分析', 'data-analysis'),
    ('查企业', '天眼一下'),
    ('视频抽帧', 'video-frames'),
    ('视频转文字', 'video-whisper-transcribe'),
    ('创建技能', 'create-skill'),
]

# R164 二次回炉: 60 条自动草稿全部改为自然语言查询（2026-08-03 路由轮）
AUTO_OVERRIDES = {
    'A-ask-questions': '需求有点模糊，帮我先问清楚再动手',
    'brand-guidelines': '帮我定一套品牌配色和字体规范',
    'byted-bp-cdn-pagesdeploy': '帮我一键部署静态网站到 CDN',
    'byted-seedance-video-generate': '帮我把这段文案生成视频',
    'chaoshi-admin-inline-edit': '超市后台商品编辑，用内联编辑模式改',
    'chaoshi-image-optimization': '把超市商品图片批量压缩成 WebP',
    'clawhub': '帮我在技能市场搜索技能',
    'computer-use-guidance-windows': '帮我自动化操作 Windows 桌面',
    'create-skill': '帮我新建一个技能',
    'data-layer-consistency-fix': '数据层有死链和不一致，帮我修复',
    'doc-coauthoring': '帮我协作写一份技术文档',
    'dogfood': '帮我系统测试一下这个本地网页应用',
    'fenjue-advisor-scoring': '按焚诀评分机制给三件套评个分',
    'fenjue-cc-audit-cycle': '跑一轮 CC 审计闭环把分数推到达标线',
    'find-skills': '帮我找找有没有相关技能',
    'frontend-slides': '帮我做一个动画丰富的 HTML 演示文稿',
    'frontend-skill': '帮我做一个高颜值的落地页',
    'gstack': '用无头浏览器跑页面测试和截图对比',
    'hook-analyzer-skill': '帮我分析视频前三秒的钩子吸引力',
    'hyperframes': '帮我用 HTML 做视频合成动画',
    'hyperframes-cli': '用 hyperframes CLI 渲染我的视频合成',
    'hyperframes-media': '帮我给视频合成做配音和音频转写',
    'hyperframes-registry': '帮我安装一个 hyperframes registry 组件',
    'install-skill-dependency': '技能缺依赖跑不起来，帮我装运行时',
    'nano-pdf': '帮我在 PDF 里改一段文字',
    'notion-cli': '帮我用 Notion CLI 查询数据库',
    'obsidian-bases': '帮我在 Obsidian 里创建 Bases 视图',
    'obsidian-cli': '帮我在 Obsidian 里搜索笔记',
    'oc-dispatch-exec-guard': '派发 OC 任务时加执行护栏防秒停',
    'openclaw-dual-gate-quality-audit': '对 OC 输出做双门禁质量审计',
    'openclaw-fenjue-weekly': '跑一轮焚诀周维护任务',
    'pixelle-api-ensure': '帮我检测并启动本地 Pixelle 视频服务',
    'prompt-consolidation': '帮我清理提示词里堆积的补丁',
    'report-generator-skill': '帮我把分镜和钩子数据生成分析报告',
    'research-documentation': '帮我在 Notion 里做综合调研文档',
    'shell-encoding-pitfalls': '帮我修 Git Bash 里的中文乱码',
    'skill-defer-to-authority': '检测 skill 与权威规则冲突',
    'skill-drift-surgery': '修复 skill 注册表漂移',
    'skill-hitrate-full-audit': '对路由命中率做全链路诊断',
    'skill-hitrate-improvement-pipeline': '跑一轮命中率提升 pipeline',
    'skill-midtask-recheck': '任务中途帮我重跑 skill 匹配检查',
    'skill-routing-regeneration': '路由触发词质量差需要重生',
    'spec-to-implementation': '帮我把产品规格拆成实施任务',
    'static-site-batch-audit-fix': '帮我批量审计并修复静态站点',
    'taskflow-inbox-triage': '参考 TaskFlow 示例给我的收件箱分类',
    'theme-factory': '帮我给这个页面换个主题配色',
    'ui-ux-pro-max': '帮我做一套 UI 设计规范',
    'vp-perspective-audit': '用副总视角审计一下 agent 行为模式',
    'web-design-guidelines': '帮我审查这个页面是否符合 Web 设计规范',
    'windows-bash-cli-interop-pitfalls': 'Git Bash 调 CLI 报错帮我排查',
    'windows-cli-utf8-wrapper': 'python subprocess 调用 CLI 输出乱码',
    'windows-gitbash-chinese-path-pit': 'Git Bash 中文路径报错帮我修',
    'workflow-preflight-check': '执行前帮我预检一遍工作流',
    'writing-plans': '帮我写一份实施计划',
    'windows-native-ocr': '用 Windows 原生 OCR 识别图片',
    'fenjue-lessons-hitrate': '帮我度量 lessons 命中率',
}

FAULT_QUERIES = [
    ('帮我配一下', None, 'blindspot'),
    ('弄个好看的', None, 'blindspot'),
    ('怎么搞', None, 'blindspot'),
    ('优化一下', None, 'blindspot'),
    ('查一下', None, 'blindspot'),
    ('帮我看看', None, 'blindspot'),
    ('画个东西', None, 'blindspot'),
    ('写个报告', None, 'blindspot'),
    ('帮我下载', None, 'blindspot'),
    ('我该怎么做', None, 'blindspot'),
    ('帮我处理一下', None, 'blindspot'),
    ('同步一下', 'cross-platform-skill-sync', 'usable-suboptimal'),
    ('帮我总结', 'A-get-memory', 'usable-suboptimal'),
    ('做个页面', 'frontend-skill', 'usable-suboptimal'),
    ('搞个自动化', 'taskflow', 'usable-suboptimal'),
    ('数据分析一下', 'data-analysis', 'usable-suboptimal'),
    ('推荐个工具', 'find-skills', 'usable-suboptimal'),
    ('有没有相关技能', 'find-skills', 'usable-suboptimal'),
    ('这轮做得怎么样', 'A-get-memory', 'usable-suboptimal'),
]


def build():
    skills = load_skills()
    existing = load_existing()
    negatives = load_negatives()

    # skills 层: 复用 + 草稿
    skills_q = []
    missing = []
    for name, meta in sorted(skills.items()):
        if name in existing:
            e = existing[name]
            skills_q.append({'query': e['query'], 'expected_skill': e['expected_skill'],
                             'judge': e['judge'], 'source': f"{e['source']}(reuse)", 'skill': name})
        else:
            trig = meta['triggers'][0] if meta['triggers'] else ''
            if name in AUTO_OVERRIDES:
                query = AUTO_OVERRIDES[name]
            elif trig:
                query = f"帮我{trig}"
            else:
                query = f"帮我做：{meta['desc'][:20]}"
            missing.append(name)
            skills_q.append({'query': query, 'expected_skill': name, 'judge': 'exact',
                             'source': 'auto-draft', 'skill': name})

    # 全库去重: skills 层优先, 策展层跳过重复文本
    seen = {q['query'] for q in skills_q}

    def dedupe(entries):
        out = []
        for e in entries:
            if e['query'] not in seen:
                seen.add(e['query'])
                out.append(e)
        return out

    cli_q = dedupe([{'query': q, 'expected_skill': s, 'judge': 'exact', 'source': 'curated-cli', 'skill': s}
                    for q, s in CLI_QUERIES])
    short_q = dedupe([{'query': q, 'expected_skill': s, 'judge': 'exact', 'source': 'curated-short', 'skill': s}
                      for q, s in SHORT_QUERIES])
    fault_q = dedupe([{'query': q, 'expected_skill': s, 'judge': j, 'source': 'curated-fault', 'skill': s or 'NONE'}
                      for q, s, j in FAULT_QUERIES])
    neg_q = dedupe([{'query': q['query'], 'expected_skill': None, 'judge': 'blindspot', 'source': q['source'], 'skill': 'NONE'}
                    for q in negatives])

    tiers = [
        {'tier': 'skills', 'queries': skills_q},
        {'tier': 'cli', 'queries': cli_q},
        {'tier': 'short', 'queries': short_q},
        {'tier': 'fault_finding', 'queries': fault_q},
        {'tier': 'negative', 'queries': neg_q},
    ]
    return tiers, skills, missing


def validate(tiers, skills):
    all_q = [q for t in tiers for q in t['queries']]
    texts = [q['query'] for q in all_q]
    dups = sorted({t for t in texts if texts.count(t) > 1})
    total = len(all_q)
    short_n = sum(1 for q in all_q if len(q['query']) <= 8)
    cli_re = re.compile(r'(ffmpeg|git |npm |pip |python |node |curl |sqlite|mysql|npx|ntn|gh |tyc |oracle|tcb |wsl |Codex|claude|discover|silk|NPU|powershell|mediakit-cli|Seedance|Seedream|p5\.js|whisper|\btts\b|obsidian)', re.I)
    # CLI 计数 = 策展 CLI 层(权威) + 其他层命中正则的查询
    cli_n = sum(1 for q in all_q if q.get('source') == 'curated-cli' or cli_re.search(q['query']))
    covered = {q['expected_skill'] for q in all_q if q['expected_skill']}
    missing_skills = sorted(set(skills) - covered)
    fault_n = sum(1 for q in all_q if q.get('source') == 'curated-fault')
    neg_n = sum(1 for q in all_q if q.get('judge') == 'blindspot')
    stats = {
        'total': total,
        'unique': len(set(texts)),
        'dup_count': len(dups),
        'dups': dups[:10],
        'skills_covered': len(covered),
        'skills_total': len(skills),
        'missing_skills': missing_skills,
        'short_n': short_n,
        'short_ratio': round(short_n / total * 100, 1),
        'cli_n': cli_n,
        'cli_ratio': round(cli_n / total * 100, 1),
        'fault_n': fault_n,
        'negative_n': neg_n,
    }
    errors = []
    if len(covered) < len(skills):
        errors.append(f"覆盖率不足: {len(covered)}/{len(skills)}")
    if stats['short_ratio'] < 20:
        errors.append(f"短查询比例不足: {stats['short_ratio']}% < 20%")
    if stats['cli_ratio'] < 20:
        errors.append(f"CLI 比例不足: {stats['cli_ratio']}% < 20%")
    if stats['fault_n'] < 15:
        errors.append(f"找茬层不足: {stats['fault_n']} < 15")
    if stats['negative_n'] < 10:
        errors.append(f"负例不足: {stats['negative_n']} < 10")
    if stats['dup_count'] > 0:
        errors.append(f"重复查询: {stats['dup_count']} 条")
    return stats, errors


def main():
    write = '--write' in sys.argv
    tiers, skills, missing = build()
    stats, errors = validate(tiers, skills)
    print(json.dumps({'stats': stats, 'errors': errors,
                      'auto_draft_count': len(missing)}, ensure_ascii=False, indent=2))
    if errors and '--force' not in sys.argv:
        print('❌ 校验失败, 不写入')
        sys.exit(1)
    if write:
        Path(OUT).write_text(json.dumps(tiers, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'✅ 已写入 {OUT}')
    else:
        print('dry-run: 未写入 (加 --write 落盘)')


if __name__ == '__main__':
    main()
