#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tag_layer.py — L0.5 Tag 过滤层 + NOT USE 负标签体系
====================================================
R162: 从 unified_router.py 拆出（五层模块化: direct/tag/BGE/memory/LLM）。
对外 API: _load_tags / tag_filter / NEGATIVE_TAG_MAP / _neg_pattern_fires /
          EXPLICIT_ONLY / negative_filter_candidates / _build_negative_index
"""
import os
import json
import re
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))

# ====== Tag 索引（懒加载） ======
_tag_index = None

def _load_tags():
    global _tag_index
    if _tag_index is not None:
        return
    tag_path = os.path.join(EVAL_DIR, 'skill_tags.json')
    if os.path.exists(tag_path):
        try:
            with open(tag_path, 'r', encoding='utf-8') as f:
                _tag_index = json.load(f).get('index', {})
        except (OSError, json.JSONDecodeError) as e:
            # 派生件半截写入/损坏时降级为空索引：Tag 层跳过，BGE 全量召回不受影响
            # （与 direct_map 损坏回退、BGE 失败回退 TF-IDF 的分层降级哲学一致）
            print(f"[tag_layer] skill_tags.json 读取失败，Tag 层降级跳过: {e}", file=sys.stderr)
            _tag_index = {}
    else:
        _tag_index = {}


# ====== Tag 过滤层（L0.5: 领域分类后、BGE召回前） ======
def tag_filter(query, domain=None):
    """
    Tag预过滤: 从query中提取标签，找到精确匹配的skill子集。
    如果匹配到≥2个skill，返回候选集供BGE进一步排序；
    如果匹配到恰好1个，直接返回名单（短路BGE）；
    如果无匹配，返回None，走BGE全量召回。
    
    R18.2: +权重分层(P0/P1/P2) + NOT USE负标签过滤
    """
    _load_tags()
    if not _tag_index:
        return None
    
    # 收集匹配的 skill 及其权重
    matched_skills = {}  # skill_name → total_weight
    
    # P0 标签精确匹配
    for tag in TAG_WEIGHT_TIERS.get('P0', []):
        if re.search(tag, query, re.IGNORECASE):
            for sk in _tag_index.get(tag, []):
                matched_skills[sk] = matched_skills.get(sk, 0) + 1.0
    
    # P1 标签匹配（半权重）
    for tag in TAG_WEIGHT_TIERS.get('P1', []):
        if re.search(tag, query, re.IGNORECASE):
            for sk in _tag_index.get(tag, []):
                matched_skills[sk] = matched_skills.get(sk, 0) + 0.5
    
    # P2 标签匹配（弱权重，仅当已有 P0/P1 命中时激活）
    if matched_skills:
        for tag in TAG_WEIGHT_TIERS.get('P2', []):
            if re.search(tag, query, re.IGNORECASE):
                for sk in _tag_index.get(tag, []):
                    matched_skills[sk] = matched_skills.get(sk, 0) + 0.2
    
    if not matched_skills:
        return None
    
    # R18.2: NOT USE 负标签过滤——从候选池移除不匹配的 skill
    _build_negative_index()
    for skill_name in list(matched_skills.keys()):
        if skill_name in _NEGATIVE_SKILL_TAGS:
            for pattern in _NEGATIVE_SKILL_TAGS[skill_name]:
                if pattern.search(query):
                    del matched_skills[skill_name]
                    break
    
    if not matched_skills:
        return None
    
    # 如果指定了domain，过滤domain内的skill
    # 延迟 import 破循环（bge_layer → tag_layer；此处运行时 bge_layer 已加载完毕）
    from bge_layer import _bge_skills
    if domain and _bge_skills:
        domain_skill_names = {s['name'] for s in _bge_skills if s.get('domain') == domain}
        matched_skills = {k: v for k, v in matched_skills.items() if k in domain_skill_names}
        if not matched_skills:
            return None
    
    # 按权重降序排序
    return [sk for sk, _ in sorted(matched_skills.items(), key=lambda x: -x[1])]

# ====== R18.2 NOT USE 负标签系统 ======
# 负标签: 当 query 匹配标签但上下文指向 NOT USE → 从候选池移除该 skill
# 权重分层: P0(核心)=1.0  P1(相关)=0.5  P2(远亲)=0.2
NEGATIVE_TAG_MAP = {
    # R20: 已自动合并重复 key（原 90 处定义 → 65 唯一 key），铁律：同 key 禁止二次定义
    # R164: 收窄过宽负标签——裸"安装技能"属于 skill-install, 但"安装技能缺依赖"属本技能
    # R169: dogfood 泛规则守卫——含路由/技能/审计/系统语境时禁止被 dogfood 抢跑
    "dogfood": ["路由", "技能.*(?:路由|系统|问题)", "审计", "评分", "系统.*问题", "记忆.*系统"],
    "install-skill-dependency": ["安装.*技能.*(?:市场|仓库|github)", "GitHub安装", "安装.*skill", "CodeBuddy"],
    "skill-install": ["依赖.*修复", "二进制.*修复", "npm.*install", "pip.*install", "依赖", "二进制", "npm", "pip", "运行环境"],
    "obsidian-cli": [
        "笔记.*管理", "写.*笔记", "编辑.*笔记", "markdown.*写作", "笔记.*管理|管理.*笔记|写.*笔记|编辑.*笔记|markdown.*写作", "notion",
        "word", "pdf", "canvas", "白板",
    ],
    "obsidian-markdown": ["cli.*操作", "打开.*obsidian", "搜索.*vault", "notion", "word", "docx", "canvas", "白板",
                          "上次.*聊|接着.*上次|新窗口.*接着|会话.*续接|项目.*交接"],
    "obsidian-bases": ["canvas", "白板", "上次.*聊|新窗口.*接着"],
    "test-driven-development": ["自动化.*测试", "写.*测试.*用例", "跑.*测试", "重构", "报错", "bug", "issue", "看看.*issue"],
    "testing": ["先写.*测试", "tdd", "测试驱动", "重构", "debug", "报错"],
    "canvas-design": ["代码.*画", "生成.*艺术", "p5", "算法.*艺术", "前端", "UI组件", "落地页"],
    "algorithmic-art": ["poster", "logo", "海报", "静态.*设计", "落地页", "UI设计", "shadcn"],
    "byted-seedream-image-generate": [
        # R-fix(2026-08-16): 移除全部本地/离线类负标签——local-txt2img 不可达(无 SKILL.md)，
        # '本地生成图片/不用云端生成图' 等 query 经本地守卫回落 byted-seedream-image-generate
        # (唯一文生图技能)。原负标签命中且无否定前缀时拦截回落，direct_route 返回 None。
        # 本地守卫(is_local + cloud_skills)仍在 direct_route 生效，仅回落不再被负标签挡。
    ],
    # R164: 收窄过宽负标签——"写个页面/做个页面" 正是 frontend-skill 的语义, 不应自挡
    # R203: 补头脑风暴/创意模式（归 brainstorming）；"设计.*界面" 收窄为 "设计.*界面风格"
    #       避免误杀"设计一个落地页的UI界面"（真设计任务，frontend-skill 应保留）
    # 2026-09-09 审查专项: 补「审查/排查/快照集/代码库」类负样本——裸子串"前端页面"
    #       曾把"重点排查前端页面快照集跳转异常"的代码审查任务 direct_hit 到本设计类
    #       技能（score 1.0 短路 BGE/LLM）。负标签在 direct_route(R20) 与 BGE 阶段双重
    #       生效：命中即放弃 frontend-skill 回落全管线；真设计任务（做页面/落地页/UI）
    #       不受影响。实测回归三例见当日日志。
    "frontend-skill": ["设计.*风格|设计.*规范|visual.*design|设计.*界面风格|ui.*设计",
                       "头脑风暴", "创意点子|想.*创意|灵感|点子",
                       "代码.*审查|全面审查|审查.*报告|性能瓶颈|安全漏洞|可维护性|重复代码",
                       "快照集|代码库|跳转.*异常|排查.*异常|代码.*缺陷"],
    # 2026-09-09 审查专项: github 直连负样本——宽 pattern "代码.*审查|审查.*项目"
    #       本意覆盖 gh PR/issue 审查场景，但会把"代码库全面审查/排查性能瓶颈/
    #       安全漏洞"这类本地代码审查任务也劫走（frontend-skill 负样本生效后
    #       暴露为第二跳误命中）。命中本地审查语境即放弃直连回落全管线；
    #       PR/issue/gh 工作流查询（创建issue/gh pr 等）不受影响。
    "github": ["性能瓶颈|安全漏洞|可维护性|重复代码|代码.*缺陷",
               "快照|深度优化|优化报告|排查.*异常|跳转.*异常|全面审查"],
    # R203: 补 ui-ux-pro-max 实现类负标签（实现归 frontend-skill）
    "ui-ux-pro-max": ["实现.*响应式|响应式.*页面|写.*组件|实现.*页面|前端.*实现"],
    "brainstorming": ["设计稿|figma|UI.*实现|落地.*页面|写.*前端"],
    "prompt-consolidation": ["优化.*提示词", "改进.*提示词", "better.*prompt"],
    "knowledge-capture": ["研究.*报告", "论文.*写作", "文献.*综述", "学术.*研究"],
    "research-documentation": ["会议.*纪要", "对话.*记录", "聊天.*整理|整理.*聊天|聊天.*记录", "知识.*捕获"],
    "slides": ["商务.*演示|商务.*汇报|商务.*报告", "企业.*汇报|企业.*演示", "季度.*报告", "年度.*汇报|年度.*总结", "工作.*汇报"],
    "pptx": ["创意.*演示|创意.*提案", "动画.*演示|动画.*提案|互动.*动画", "互动.*slide", "hype.*slide", "word", "docx", "pdf",
             "排版.*编辑|编辑.*排版|幻灯片.*排版"],
    "writing-plans": ["执行.*计划", "实现.*规格", "代码.*实现", "开发.*计划", "gh.*pr", "gh.*issue", "gh.*run"],
    "spec-to-implementation": ["写作.*大纲", "文档.*结构", "计划.*大纲", "规划.*结构"],
    "skill-creator": ["安装", "依赖", "GitHub"],
    "skill-manager": ["创建.*skill", "写.*skill", "安装.*skill"],
    "cross-platform-skill-sync": ["安装", "创建", "删除.*skill"],
    "figma": ["截图", "算法艺术", "p5", "海报"],
    "shadcn": ["figma", "算法艺术", "海报", "canvas"],
    "docx": ["ppt", "幻灯片", "pdf"],
    "pdf": [
        # R-fix(2026-08-16): 移除 "解析.*pdf|pdf.*解析|pdf.*转.*markdown|pdf.*转.*md"——
        # 这些是 pdf 技能的核心功能(提取文本/转markdown)，误放负标签导致
        # 'PDF 扫描件本地解析成结构化数据' 被自挡。负标签只保留与 nano-pdf(编辑)/docx 的区分。
        "word", "ppt", "演示", "pdf.*改.*字", "pdf.*编辑", "pdf.*里.*改", "pdf.*水印",
    ],
    "deep-research-pro": ["天眼查", "企业.*查", "公司.*背景"],
    "天眼一下": ["深度.*研究", "论文", "学术", "市场.*分析"],
    "consulting-analysis": ["天眼查", "企业.*查", "代码", "视频.*分析", "钩子", "前三秒"],
    "A-ask-questions": [
        "头脑风暴", "brainstorm", "你好", "谢谢", "笑话", "天气", "你能做什么", "解释.*闭包", "算.*乘", "读.*文件", "dialog",
        "shadcn", "合并.*技能", "技能.*合并", "合到一起",
    ],
    "hyperframes": ["生成.*视频.*配音", "做.*完整.*视频", "视频.*流水线"],
    "chart-visualization": ["plotly", "seaborn", "热力图", "交互式", "python.*画"],
    "skill-trigger-diagnosis": ["重新生成", "重生.*json", "scan_skills", "触发词.*生成"],
    "fenjue-routing-health-check": ["重生.*json", "触发词.*重新", "路由.*json", "质量.*审计", "全链路", "命中率.*诊断"],
    "chaoshi-web-deploy": ["订单.*没反应", "下单.*没效果", "订单.*提交"],
    "chaoshi-admin-inline-edit": ["订单", "下单", "提交.*没"],
    "shell-encoding-pitfalls": ["聚合.*脚本", "runner.*判定", "全绿.*fail"],
    "workflow-preflight-check": ["skill.*过时", "定义.*过时", "工作流.*不匹配"],
    "xlsx": ["sync_health", "数据层", "死链"],
    "c-cleanup": ["死链.*清理", "数据层"],
    "report-generator-skill": ["市场.*分析", "研究.*报告", "咨询"],
    # ===== R20 新增边界（盲测暴露的真实能力边界，非对题补丁）=====
    # mcporter=MCP服务器配置，不做"桌面应用隐藏CLI发现"（那是 discover-agent-cli）
    "mcporter": ["桌面.*软件", "桌面.*应用.*cli", "藏着.*命令行", "隐藏.*cli", "electron.*cli", "挖.*命令行"],
    # oc-dispatch-exec-guard=OpenClaw派发0产出护栏；全程监工/重试验证=supervision；派给Codex=coding-agent
    "oc-dispatch-exec-guard": ["监工", "全程.*监督", "重试.*验证", "codex", "claude.*写", "派给.*codex"],
    "audit-runner-safe-aggregate": ["codex", "派给", "模块.*写"],
    # A-memory-start=启动门禁；A-get-memory=任务后反哺；用户画像/使用习惯查询=A-get-memory
    # R22 修复: 负标签误抄正触发词（使用习惯/用户画像/记了.*啥 是 A-get-memory 正触发词，
    # 误放负标签导致记忆类查询被守卫否决 → 直连失效）。改为真正互斥的语境。
    "A-memory-start": ["会话.*续接", "接着.*上次", "继续.*上次", "上次.*聊到", "handoff", "交接"],
    "A-get-memory": ["拆分.*大文件", "bigfile", "超大.*md", "4kb", "分卷", "part.*合并"],
    "fenjue-memory-audit": ["拆分.*大文件", "bigfile", "超大.*md", "分卷"],
    # bigfile-split=拆分超大md文件；与记忆查询互斥（用户画像/习惯查询归 A-get-memory）
    "bigfile-split": ["使用习惯", "用户画像", "偏好.*记", "复盘", "经验.*总结", "教训"],
    # skill-hitrate-full-audit=全链路批量诊断；单个技能"为什么没触发"=skill-trigger-diagnosis
    "skill-hitrate-full-audit": ["这个.*技能.*没.*触发|这个.*skill.*没.*触发", "为什么.*没.*自动.*触发", "单个.*技能"],
    # ===== R198.6 新增 32 skill 负样本护栏补全（2026-08-16，T11 提升）=====
    # brand-guidelines=品牌规范；与生成/设计稿互斥
    "brand-guidelines": ["生成.*图片", "画.*图", "设计.*稿", "UI.*实现", "写.*前端", "生成.*海报"],
    # defuddle=网页转 markdown 清洗；与"保存/下载网页文件"互斥（"批量下载网页内容"=提取内容应放行）
    "defuddle": ["保存.*网页", "网页.*另存", "下载.*网页.*文件", "离线.*保存.*网页", "抓取.*数据", "爬虫", "搜索.*结果", "PDF.*提取"],
    # executing-plans=执行已有实现计划；与制定/规划互斥
    # R-fix(2026-08-16): "写.*计划" 加负向先行断言 (?!.*执行)——'把已写好的实施计划一步步落地执行完'
    # 含"写好的实施计划...执行"，原模式误拦截导致 executing-plans 被 writing-plans 抢跑。
    "executing-plans": ["制定.*计划", "规划.*方案", "写.*计划(?!.*执行)", "设计.*架构", "头脑风暴", "目标.*拆解"],
    # frontend-design=前端界面设计；与后端/数据/测试互斥
    "frontend-design": ["后端.*接口", "数据库.*设计", "API.*开发", "写.*测试", "部署.*服务", "函数.*实现"],
    # internal-comms=内部通讯写作；与营销/对外文案互斥
    "internal-comms": ["营销.*文案", "广告.*文案", "推广.*文案", "小红书", "公众号.*推文", "短视频.*脚本"],
    # json-canvas=JSON Canvas 文件编辑；与画布绘图/白板/可视化互斥
    "json-canvas": ["画.*白板", "流程图.*生成", "可视化.*图表", "画布.*绘图", "excalidraw", "思维导图.*绘制"],
    # local-asr=本地语音识别；与 TTS/合成/翻译互斥
    "local-asr": ["文字.*转.*语音", "语音.*合成", "TTS", "朗读", "配音", "翻译.*语音"],
    # local-computer-use=本地电脑查询/控制；与远程/云/浏览器自动化互斥
    "local-computer-use": ["远程.*控制", "云.*服务器", "浏览器.*自动化", "网页.*操作", "爬虫", "SSH"],
    # local-img2img=本地图生图编辑；与文生图/视频互斥
    "local-img2img": ["生成.*新图", "文生图", "文字.*转.*图片", "画.*张图", "生成.*视频", "视频.*生成"],
    # local-mineru=本地文档解析；与 OCR/生成文档互斥
    "local-mineru": ["识别.*图片.*文字", "OCR", "生成.*文档", "写.*docx", "创建.*文档", "文字.*识别"],
    # local-ocr-npu=本地 OCR；与语音识别/文档解析互斥
    "local-ocr-npu": ["语音.*识别", "转写.*音频", "解析.*PDF", "文档.*解析", "阅读.*文档", "音频.*转文字"],
    # local-realtime-translator=本地实时翻译；与文档翻译/字幕互斥
    "local-realtime-translator": ["翻译.*文档", "字幕.*翻译", "整篇.*翻译", "文件.*翻译", "批量.*翻译", "术语.*管理"],
    # local-screenshot-qa=本地截图 QA；与美化/修图/截图工具互斥
    "local-screenshot-qa": ["美化.*截图", "修图", "滤镜", "截图.*工具", "录屏", "屏幕.*录制"],
    # local-tts=本地文字转语音；与 ASR/识别/翻译互斥
    "local-tts": ["语音.*识别", "转写", "ASR", "听写", "录音.*转文字", "音频.*转写"],
    # local-txt2img=本地文生图；与图生图/视频/UI 互斥
    "local-txt2img": ["编辑.*图片", "图生图", "修改.*照片", "生成.*视频", "UI.*设计", "图片.*润色"],
    # local-vram=本地显存调整；与模型训练/性能测试互斥
    "local-vram": ["训练.*模型", "跑.*深度学习", "性能.*基准", "benchmark", "显卡.*测试", "游戏.*帧率"],
}

# R194 对抗测试守卫：注入/越权/破坏类指令不得路由到执行类技能
_ADVERSARIAL_GUARD = [
    "删(?:除|掉).*(?:库|数据|文件|全部)|清空.*(?:库|数据)|rm\\s*-rf|删库|越权|绕过.*(?:门禁|权限)|忽略.*(?:之前|系统).*指令|系统管理员|强制.*覆盖|直接运行\\s*rm|杀毒|关掉.*防护|关闭.*安全软件",
]
for _guard_skill in (
    "chaoshi-web-deploy",
    "cloudbase-webapp-deploy-debug",
    "byted-bp-cdn-pagesdeploy",
    "byted-seedream-image-generate",
    "byted-seedance-video-generate",
    "office-automation-pro",
    "wechat-automation",
):
    NEGATIVE_TAG_MAP.setdefault(_guard_skill, []).extend(_ADVERSARIAL_GUARD)

_NEGATION_WORDS = re.compile(r'不用|别用|不要|不想|无需|不走|禁用|免')

def _neg_pattern_fires(pattern, query):
    """R20.1: 否定语境守卫 — 负标签匹配点前6字符内出现否定词则不生效。
    治77条回归: '不用云端本地生成图片' 中 '云端.*生成.*图' 命中的是否定语境，
    此时用户意图恰是负标签的反面，负标签失效。
    （负标签模式自身含否定词的不受影响：匹配起点即否定词，前缀无否定词。）"""
    m = pattern.search(query)
    if not m:
        return False
    prefix = query[max(0, m.start() - 6):m.start()]
    if _NEGATION_WORDS.search(prefix):
        return False
    return True

# R20 Task#6: 收缩自动匹配池 — 教学/示例/小众 skill 仅显式点名才入自动候选池
# (Bilibili方法论: 低频高危skill显式调用, 不参与语义自动匹配)
EXPLICIT_ONLY = {
    'taskflow-inbox-triage': re.compile(r'inbox|收件箱.*分类|triage', re.I),  # 自述"参考/教学用途,非生产"
    'brand-guidelines': re.compile(r'brand|anthropic|品牌规范|品牌指南', re.I),  # Anthropic品牌专用
}

def negative_filter_candidates(candidates, query):
    """R20: BGE/ensemble 候选层的 NOT USE 过滤。
    命中负标签的 skill 从候选中降级（移到队尾并打折），而非硬删——
    防止全部候选被负标签清空后无兜底。原 query（非归一化）匹配负标签。
    R20 Task#6: EXPLICIT_ONLY skill 未被点名直接移出池（硬删，非降权）。"""
    if not candidates:
        return candidates
    _build_negative_index()
    candidates = [c for c in candidates
                  if c['name'] not in EXPLICIT_ONLY or EXPLICIT_ONLY[c['name']].search(query)]
    kept, demoted = [], []
    for c in candidates:
        pats = _NEGATIVE_SKILL_TAGS.get(c['name'])
        if pats and any(_neg_pattern_fires(p, query) for p in pats):
            c = dict(c)
            c['score'] = round(c['score'] * 0.6, 4)  # 降权而非删除
            c['neg_hit'] = True
            demoted.append(c)
        else:
            kept.append(c)
    return kept + demoted if kept else candidates  # 全被降级则保持原样

# 反向索引: skill → NOT USE 标签列表（预计算，查询时直接使用）
_NEGATIVE_SKILL_TAGS = None
def _build_negative_index():
    global _NEGATIVE_SKILL_TAGS
    if _NEGATIVE_SKILL_TAGS is not None:
        return
    _NEGATIVE_SKILL_TAGS = {}
    for skill_name, patterns in NEGATIVE_TAG_MAP.items():
        _NEGATIVE_SKILL_TAGS[skill_name] = [re.compile(p, re.IGNORECASE) for p in patterns]


# R162: 模块加载即构建（from-import 拿到同一对象；懒加载守卫保证只建一次）
_build_negative_index()

# Tag 权重分层 (P0/P1/P2)
TAG_WEIGHT_TIERS = {
    # P0: 核心功能标签，精确匹配=权重1.0（完全信任）
    'P0': [
        r'\bexcel\b', r'\bpdf\b', r'\bppt\b', r'\bcsv\b', r'\bdocx\b',
        r'\bobsidian\b', r'\bnotion\b', r'\bfigma\b', r'\bgithub\b',
        r'\bgsap\b', r'\bshadcn\b', r'\btdd\b', r'\bp5\b',
        '部署上线', '天眼查', '微信自动化', '本地ocr', '本地tts',
        '经验反哺', '项目交接', '大文件拆分', '文生图', '图生图',
        '文生视频', '提示词优化', '全局记忆', '路由健康',
    ],
    # P1: 相关功能标签，权重0.5（辅助信号）
    'P1': [
        '自动化', '测试', '调试', '重构', '编码', '修复',
        '设计', '前端', '图表', '数据分析', '搜索', '研究',
        '视频', '音频', '字幕', '动画', '报告', '审计',
        '同步', '拆分', '管理', '安装', '创建', '生成',
    ],
    # P2: 远亲标签，权重0.2（弱信号，仅做微调）
    'P2': [
        '优化', '提升', '改进', '简化', '整理',
        '检查', '查看', '分析', '评估', '对比',
    ],
}
# 用户常用 skill（从实际使用频率推断）
