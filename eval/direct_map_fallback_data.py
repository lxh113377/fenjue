#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""direct_map_fallback_data.py — 直连兜底表数据（P1-8 数据/逻辑分离，2026-09-23）。

内容与 direct_map.json 双写一致（verify C24 门禁比对对象）；本文件由 direct_layer.py
L20-L333 原位平移而来，条目字节级同源、逻辑零变化。修改本表后必须同步 direct_map.json
（build_indexes --force），否则 C24 FAIL。
"""

_DIRECT_MAP_FALLBACK = [
    ("苹果.*香蕉|香蕉.*苹果|水果.*热量|哪个热量高", "NONE"),
    ("^同步一下$|^帮我同步一下$|^同步下$", "A-skill-manager"),
    ("^写邮件$|^帮我写.*邮件$|^写封邮件$|^写个邮件$", "internal-comms"),
    ("^换主题$|^帮我换主题$|^换下主题$|^换个主题$", "theme-factory"),
    ("^报错了$|^报错了[！!]?$|^出错了$", "debugging-fixing"),
    ("生成.*word|word.*生成|^生成Word$", "docx"),
    ("sqlite|sqlite3|打开.*db文件|打开.*数据库.*文件", "data-analysis"),
    ("一键部署.*静态|静态网站.*CDN|部署.*CDN|CDN.*部署|静态.*部署.*网站", "byted-bp-cdn-pagesdeploy"),
    ("obsidian.*白板|白板.*canvas|canvas.*文件编辑|obsidian.*canvas", "json-canvas"),
    ("MCP.*服务器|MCP.*配置|MCP.*认证|服务器.*MCP|配置.*MCP", "mcporter"),
    ("obsidian.*搜索|搜索.*obsidian|obsidian.*查|obsidian.*vault|vault.*笔记", "obsidian-cli"),
    ("obsidian.*cli|cli.*obsidian|^obsidian cli", "obsidian-cli"),
    ("openclaw.*派活|派活.*openclaw|全程监工|监工.*重试|openclaw.*监工|openclaw.*重试", "openclaw-task-supervision"),
    ("notion.*调研|调研.*notion|notion.*研究|notion.*综合.*文档|综合.*notion", "research-documentation"),
    ("创建.*issue|issue.*创建|gh.*issue|用.*gh.*创建", "github"),
    ("ntn.*notion|ntn.*创建|创建.*notion.*页面|notion.*页面|^ntn", "notion-cli"),
    ("PPT.*提取|提取.*PPT|PPT.*演讲稿|演讲稿.*PPT|PPT.*讲稿|做演讲稿", "pptx"),
    ("^你好$|^谢谢$|^感谢$|^再见$|^晚安$|^早安$|^嗯$|^好的$|^哦$", "NONE"),
    ("心情.*不好|今天.*心情|给我讲.*笑话|讲个笑话|明天.*天气|天气怎么样", "NONE"),
    ("你能做什么|你会什么|你是谁$|你能干嘛", "NONE"),
    ("解释一下什么是|这个函数是干嘛|帮我算一下|帮我读一下这个文件", "NONE"),
    # R-fix(2026-09-22) 死目标清理: 原目标 `tencent-cos-skill__skillhub` 已不在注册表/磁盘
    #   （市场件未在册）→ 直连会短路到不存在的 skill。删除该直连，让查询回落常规管线。
    # ("备份.*数据库|数据库.*备份|定期.*备份|定时.*备份|备份.*脚本|写.*脚本.*备份|备份.*数据|备份.*文件|备份.*资料", "tencent-cos-skill__skillhub"),
    # ("备份.*(?:cos|腾讯云|对象存储|云存储)|cos.*备份|腾讯云.*备份|上传.*备份", "tencent-cos-skill__skillhub"),
    ("时差|北京时间|几点.*小时|起个英文名|帮我起个.*名|取个英文名|英文名叫什么", "NONE"),
    ("写.*小说|小说.*章节|创作.*小说|开始写.*小说|写.*故事", "doc-coauthoring"),
    ("手机.*笔记|笔记.*同步|同步.*笔记", "NONE"),
    ("^帮我配一下$|^配一下$|^帮我配下$|^配置一下$", "NONE"),
    ("^弄个好看的$|^弄好看点$|^做点好看的$|^弄个好点的$", "NONE"),
    ("^怎么搞$|^怎么搞一下$|^咋搞$|^怎么弄$", "NONE"),
    ("^优化一下$|^帮我优化下$|^优化下$|^帮我优化一下$", "NONE"),
    ("^查一下$|^查查$|^帮我查下$|^帮我查查$", "NONE"),
    ("^帮我看看$|^帮我瞅瞅$|^看看$|^帮忙看看$", "NONE"),
    ("^画个东西$|^画点东西$|^画个啥$|^画一下$", "NONE"),
    ("^写个报告$|^写份报告$|^帮我写个报告$|^写个报告看看$", "NONE"),
    ("^帮我下载$|^下载个东西$|^下载点东西$|^帮我下载个$", "NONE"),
    ("^我该怎么做$|^我该咋办$|^我该怎么办$|^怎么办$", "NONE"),
    ("^帮我处理一下$|^处理一下$|^帮我搞一下$|^搞一下$", "NONE"),
    (r"^1\+1等于几$|^1加1等于几$|^算术题$|^数学题$|^算一下$", "NONE"),
    ("现在几点了|几点钟了|现在几点|几点了|现在.*时间$", "NONE"),
    ("^推荐一本好书$|^推荐书$|推荐.*书单|有什么好书|好书推荐", "NONE"),
    ("^周末去哪玩$|周末.*去哪玩|去哪玩|有什么好玩的|周末.*好玩", "NONE"),
    ("部署.*超市.*截图|超市.*部署.*截图|部署完.*超市", "chaoshi-web-deploy"),
    ("分析.*excel.*图|excel.*分析.*图|分析.*表格.*图", "data-analysis"),
    ("lessons.*命中率|命中率.*lessons|lesson.*hitrate|hitrate.*lesson", "fenjue-lessons-hitrate"),
    ("白屏|页面.*白屏|白屏.*打不开", "debugging-fixing"),
    ("打不开|启动不了|无法打开|打不开.*软件", "debugging-fixing"),
    ("闪退|自动退出|频繁.*闪退", "debugging-fixing"),
    ("接口.*500|返回.*500|500.*错误|服务器.*500", "debugging-fixing"),
    ("点了.*没.*反应|按钮.*没.*反应|没任何反应|点击.*没效果", "debugging-fixing"),
    ("功能.*坏掉|坏掉了|这个.*坏了|不工作了", "debugging-fixing"),
    ("应用.*卡死|卡死了|程序.*卡死|界面.*卡死|app.*卡死", "debugging-fixing"),
    ("存储.*不够|空间.*不够了|磁盘.*不够|硬盘.*不够|存储.*怎么办", "c-cleanup"),

    ("windows.*ocr|原生ocr|win.*ocr|系统.*ocr|电脑.*ocr", "windows-native-ocr"),
    ("notion.*数据库|查.*notion|notion.*查|notion.*query", "notion-cli"),
    ("skill.*缺.*依赖|skill.*依赖.*跑不了|skill.*缺.*跑不了", "A-skill-manager"),
    ("下载.*claude|安装.*claude|装.*claude.*code|claude.*安装|claude.*下载", "A-skill-manager"),
    ("obsidian.*base|base.*文件|obsidian.*视图|bases", "obsidian-bases"),
    ("沉淀到.*notion|对话.*沉淀|记录到.*notion|知识归档", "knowledge-capture"),
    ("obsidian.*写.*笔记|obsidian.*编辑.*笔记|obsidian.*管理", "obsidian-markdown"),
    ("notion.*会议|notion.*准备|notion.*meeting", "NONE"),  # meeting-intelligence 已退役(R201) → NONE 白名单
    ("项目管理.*写.*交接|项目交接|写.*交接文档|交接.*文档", "A-project-handoff"),
    ("继续.*未完成|接着.*未完成|继续.*上次.*任务|上次.*没做完|没做完.*继续|接着.*上次.*任务", "A-project-handoff"),
    # 2026-09-26 实测漏命中补录：本轮「CI 全绿契约 / greencheck / 通知静音」任务的 router
    # top-3 全不相关（top1 A-ask-questions 0.582 与**已弃用**的 executing-plans 仅差 0.005），
    # 真实载体 A-project-handoff 根本没进候选。刻意不收裸「静音」与裸「邮件」，
    # 以免抢走 internal-comms / dingtalk-mail / 音频类技能的既有直连。
    ("greencheck|全绿契约|CI ?全绿|通知静音|静音通知|裸静音|红点邮件", "A-project-handoff"),
    ("电子杂志|杂志风|电子墨水|翻页网页", "html-ppt"),
    ("做.*ppt|写.*ppt|生成.*ppt|做.*演示|写.*演示|创建.*ppt", "pptx"),
    ("html.*演示文稿|演示文稿.*动画|动画.*演示文稿", "frontend-slides"),
    ("html.*幻灯片|html.*ppt|网页.*演示|网页.*幻灯片|网页.*ppt", "html-ppt"),
    ("第一性原理|根本原理|从零拆解|原子化拆解|打破假设.*问题", "first-principles-decomposer"),
    ("pdf.*合并|pdf.*拆分|合并.*pdf|拆分.*pdf|处理.*pdf", "pdf"),
    ("word.*文档|docx|写.*word|做.*word|创建.*word", "docx"),
    ("excel.*数据|excel.*分析", "xlsx"),
    ("读.*excel|excel.*读|编辑.*excel|excel.*表格", "xlsx"),
    ("csv.*文件|csv.*分析", "data-analysis"),
    ("柱状图|饼图|折线图|^(?!.*plotly)(?!.*seaborn)(?!.*交互)(?!.*热力).*画.*图表|数据.*图表|图表.*展示|可视化.*图表|图表.*数据", "chart-visualization"),
    ("画个图.*不知道|画什么图|不知道.*画什么|画图.*不知道|图.*不知道.*画", "chart-visualization"),
    ("交互.*可视化.*仪表|数据.*仪表盘", "data-visualization"),
    ("pip.*安装|pip.*requirements|requirements.*报错|安装.*requirements", "A-skill-manager"),
    ("技能.*缺.*依赖|安装.*技能.*依赖|缺.*依赖|运行时.*缺失", "A-skill-manager"),
    ("python.*定时|node.*定时|定时.*脚本|写.*定时", "taskflow"),
    ("subprocess.*乱码|调用.*cli.*乱码|python.*调用.*乱码", "windows-cli-utf8-wrapper"),
    ("bash.*调.*cli|git.*bash.*cli|extglob|msys2", "windows-bash-cli-interop-pitfalls"),
    ("git.*bash.*路径|中文路径.*(?:报错|问题)|路径.*乱码", "windows-gitbash-chinese-path-pit"),
    ("git.*bash.*乱码|bash.*中文.*乱码|powershell.*乱码|curl.*乱码|下载.*乱码", "shell-encoding-pitfalls"),
    ("自动化.*测试|写.*自动化.*测试", "testing"),
    ("tdd|测试驱动.*开发", "test-driven-development"),
    ("写.*脚本.*处理|写.*(?:python|py).*脚本|处理.*csv|csv.*处理", "coding-agent"),
    ("实施计划.*落地|把.*计划.*执行|计划.*落地执行|执行.*已写好的.*计划|落地.*实施计划", "executing-plans"),
    ("报错.*怎么修|怎么修.*报错|修.*bug|bug.*修复|debug.*修|debug.*报错", "debugging-fixing"),
    ("代码.*重构|重构.*代码|重构.*项目", "refactoring"),
    ("ffmpeg.*合并|合并.*视频|视频.*合并", "byted-mediakit-shared"),
    ("wsl.*ffmpeg|wsl.*转码", "video-frames"),
    ("本地.*whisper|whisper.*本地|本地.*转录|本地.*转写|本地.*语音识别", "video-whisper-transcribe"),
    ("whisper.*转录|whisper.*转写|openai.*转录|openai.*语音|语音转写.*api|openai.*api|用.*whisper", "openai-whisper-api"),
    ("微信.*语音|语音.*消息|微信.*转写|微信.*语音.*转|silk", "wechat-voice-transcription"),
    ("视频.*总结|总结.*视频|视频.*太长|太长.*视频|视频.*内容.*总结|视频.*讲了什么", "video-whisper-transcribe"),
    ("视频.*加.*字幕|字幕.*生成|语音.*转.*文字|视频.*转.*文字|视频.*字幕", "video-whisper-transcribe"),
    ("视频.*背景音乐.*动画|视频.*加.*bgm|视频.*bgm", "byted-mediakit-shared"),
    ("视频.*gif|gif.*动图|视频.*转.*gif|视频.*动图", "video-frames"),
    ("幻灯片.*排版|排版.*幻灯片|编辑.*幻灯片|幻灯片.*编辑|改.*幻灯片", "slides"),
    ("不用云端.*画|离线.*生成.*图|本地.*画.*图|本地.*生成", "byted-seedream-image-generate"),
    ("帮我.*画.*图|画.*一张.*图|ai.*画.*头像|画个.*头像", "byted-seedream-image-generate"),
    ("本地.*壁纸|离线.*壁纸|本地.*画.*壁纸|不用云端.*壁纸|本地.*生成.*壁纸|本机.*壁纸", "byted-seedream-image-generate"),
    ("博客.*插画|文章.*配图|插画.*风格|博客.*配图|文章.*插画|配.*插画|插画.*配", "byted-seedream-image-generate"),
    ("生成.*图片|画.*图.*片|生.*图|文生图|ai.*画图", "byted-seedream-image-generate"),
    ("海报|poster|宣传海报|活动海报|招聘海报", "byted-seedream-image-generate"),
    ("生成.*视频(?!分析|报告)|视频.*生成|文生视频", "byted-seedance-video-generate"),
    ("品牌.*配色|品牌.*字体|品牌.*规范|视觉规范|brand.*guideline", "brand-guidelines"),
    ("换个主题|主题配色|应用配色方案|主题样式", "theme-factory"),
    ("ui.*设计规范|设计系统|交互规范|做一套.*规范", "ui-ux-pro-max"),
    ("审查.*规范|是否符合.*规范|web.*设计规范|界面规范", "web-design-guidelines"),
    ("logo|设计.*logo|画.*logo", "canvas-design"),
    ("小说.*(?:标签|简介)|作品.*(?:标签|简介)|(?:标签|简介).*封面|创作.*(?:标签|简介)", "doc-coauthoring"),
    ("书.*封面|小说.*封面|创作.*封面|制作.*封面|设计.*封面|书籍.*封面", "canvas-design"),
    ("视频.*封面|封面.*视频", "video-frames"),
    ("设计稿.*代码|figma|设计稿.*转|转.*前端.*代码", "figma"),
    ("代码.*画.*动画|代码.*做.*动画|代码.*动图|画.*代码.*动画|代码.*生成.*动画", "algorithmic-art"),
    ("代码.*画.*艺术|算法.*艺术|p5.*艺术|生成.*艺术|代码.*生成.*艺术", "algorithmic-art"),
    ("画.*架构图|画.*流程|架构图|流程图|结构图", "diagram-maker"),
    # R-fix(2026-09-22) 死目标重指: `skill-install` 已退役(2026-09-14) → 技能增删改总管 A-skill-manager
    ("装个技能|装技能|安装技能", "A-skill-manager"),
    ("创建.*技能|新建.*技能|用户级.*技能", "A-skill-manager"),
    ("skill.*安装.*删除|管理.*skill.*安装|skill.*管理|管理.*skill", "A-skill-manager"),
    ("skill.*路由.*问题|skill.*路由.*修复|修复.*skill.*路由", "A-skill-manager"),
    ("审计.*记忆|记忆.*审计|审计.*记忆.*系统|记忆.*系统.*审计|执行得怎么样|任务执行.*怎么样|模拟执行.*效果|看看效果|效果怎么样|复盘.*效果", "fenjue-memory-audit"),
    ("记忆系统.*哪里.*优化|优化.*记忆系统|记忆系统.*优化.*建议|记忆.*还有哪里.*优化|记忆系统.*可优化|优化.*记忆.*哪里", "fenjue-memory-audit"),
    ("写.*计划|计划.*写|制定.*计划|做.*计划", "writing-plans"),
    ("路由.*健康.*检查|路由.*检查|路由.*有.*毛病|检查.*路由|路由.*健康|路由.*有.*问题|路由.*有没有.*问题|路由.*问题.*吗", "A-skill-manager"),
    ("路由.*命中率.*修|路由.*命中率.*提高|修.*命中率|命中率.*修复", "A-skill-manager"),
    ("skill.*同步|同步.*skill|cross.*platform.*skill|跨平台.*skill", "A-skill-manager"),
    ("大文件.*拆分|拆分.*大文件|md.*拆分|markdown.*拆|大.*md.*拆", "bigfile-split"),
    ("多.*agent.*工作流|agent.*编排|多.*agent.*编排", "taskflow"),
    ("自动化.*脚本.*监控|写.*脚本.*监控|监控.*文件夹|文件夹.*变化|监控.*文件.*变化|文件.*变化.*监控", "taskflow"),
    ("^搞个自动化$|^搞自动化$|^自动化一下$", "taskflow"),
    ("静态站点.*批量|批量替换.*图片路径|全站.*替换|静态.*站点.*修复", "static-site-batch-audit-fix"),
    ("webp|压缩.*图片|图片.*压缩|批量.*压缩", "chaoshi-image-optimization"),
    ("规格.*拆|产品规格|需求.*拆解|规格转任务|spec.*task", "spec-to-implementation"),
    # R-fix(2026-09-22) 死目标重指: `deep-research-pro` 已退役 → 研究报告类落 consulting-analysis
    ("搜索.*写.*研究|深度.*研究|写.*研究报告|深度.*搜索", "consulting-analysis"),
    ("天眼查|查.*企业.*背景|企业.*查|天眼.*查|查.*公司", "天眼一下"),
    ("批量.*下载.*网页|网页.*提取|批量.*提取", "defuddle"),
    ("经验.*反哺|整理.*经验|任务.*复盘|经验.*总结|学.*经验|记忆.*经验.*(?:反哺|写入|总结|沉淀)|(?:反哺|写入|沉淀).*经验.*记忆", "A-get-memory"),
    ("这轮做得怎么样|做得怎么样|这轮.*怎么样|这轮.*如何", "A-get-memory"),
    ("全局记忆.*加载|加载.*全局记忆|记忆.*启动", "A-memory-start"),
    ("自动化.*操作.*桌面|操作.*windows|windows.*桌面", "computer-use-guidance-windows"),

    ("让别人.*(?:打开|访问).*网站|别人.*(?:访问|打开).*网站|对外开放|公网.*访问|外网.*访问|网站.*公网|部署.*公网|上线.*(?:别人|大家)|外网.*打开.*网站", "byted-bp-cdn-pagesdeploy"),
    # 2026-09-11 iCAN 部署专项（项目级部署技能）：须先于下方 chaoshi「部署上线」宽 pattern，
    # 双侧项目标识约束（须同时含 项目词 + 部署词），通用部署查询不受影响。
    ("(?:ican|门店 ?ai ?管理智能体|门店 ?管理助手)[^，。；]{0,24}(?:部署|上线|重部|重新部署|pythonanywhere|服务器|域名)|(?:部署|上线|重部|pythonanywhere)[^，。；]{0,24}(?:ican|门店 ?ai ?管理智能体|门店 ?管理助手)", "ican-deploy"),
    ("发布上线|网站.*上线|怎么.*上线|部署上线|部署.*上线|部署到.*线上|搞到.*线上", "chaoshi-web-deploy"),
    ("修复.*中文.*乱码|utf.*乱码|编码.*乱码|乱码.*修复", "utf8-encoding-fix"),
    ("优化.*提示词|提示词.*优化|prompt.*优化|prompt.*better|提示词.*better", "A-prompt-better"),
    ("问题.*逐一.*对照|对照.*已有.*机制|覆盖.*缺口|补漏.*执行计划|条问题.*对照.*机制", "A-ask-questions"),
    # R-fix(2026-09-22) 死目标重指: `fenjue-cc-audit-cycle` 已退役 → 焚诀记忆/评分审计落 fenjue-memory-audit
    ("审计闭环|达标.*修复|审计.*达标|fenjue.*审计", "fenjue-memory-audit"),
    # R-fix(2026-09-22) 死目标重指: `fenjue-advisor-scoring` 已退役（用户裁定不再使用）
    ("fenjue.*scoring|advisor.*scoring|焚訣.*评分|四门.*评分|fenjue.*评分|优化记忆.*评分|skill tree.*评分", "fenjue-memory-audit"),
    ("cloudstudio|CloudStudio|云开发.*部署|部署.*云开发|部署到.*cloud", "chaoshi-web-deploy"),
    ("咋.*部署|怎么.*部署|部署.*咋弄|部署.*怎么搞|部署.*咋整", "chaoshi-web-deploy"),
    ("deploy一下|deploy.*一下|build.*然后.*上线|build.*上线", "chaoshi-web-deploy"),
    ("搞.*上线|弄.*上线|整.*上线|赶紧.*上线|快点.*上线", "chaoshi-web-deploy"),
    ("超市.*部署|超市.*上线|超市.*deploy", "chaoshi-web-deploy"),
    ("hermes.*安装|hermes.*下载|下载.*hermes|安装.*hermes|hermes.*桌面|hermes.*setup|hermes.*install|装.*hermes", "hermes-installer"),
    ("bug.*咋修|bug.*怎么搞|有bug了|有个bug|出.*bug了|bug.*弄一下|有.*bug.*要修", "debugging-fixing"),
    ("哪里.*出毛病|出毛病了|看看.*毛病|哪里.*毛病", "debugging-fixing"),
    ("代码.*太乱|太乱了|帮我理理|代码.*整理一下|乱.*理一理", "refactoring"),
    ("测测.*bug|测测.*有没有bug|功能.*有没有bug", "testing"),
    ("跑个test|跑.*test|test.*跑一下|run.*test", "testing"),
    ("python.*报错|python.*挂了|python.*跑不了|pytest.*失败", "python-debugpy"),
    ("试试.*能不能用|测一下|试一下|跑一下看看|能不能跑", "dogfood"),
    ("skill.*不加载|skill.*没触发|为什么没用.*skill|skill.*不生效", "A-skill-manager"),
    ("技能.*为什么.*没.*触发|技能.*没.*自动.*触发|为什么.*没.*自动.*触发", "A-skill-manager"),
    ("cloudbase.*报错|cloudbase.*排查|云函数.*报错|云函数.*部署.*错|云函数.*调试", "chaoshi-web-deploy"),
    (r"c\s*盘.*红|磁盘.*满|空间不够|存储.*爆|c\s*盘.*爆|磁盘.*红|清理.*c\s*盘|清理.*c\s*盘.*空间|c\s*盘.*空间|清理.*磁盘|清.*c\s*盘|c\s*盘.*清理", "c-cleanup"),
    ("^ui.*设计|ui设计|交互设计|设计系统|ui.*系统", "ui-ux-pro-max"),
    # 2026-09-10 iCAN 前端专项（项目级设计体系技能）：须先于下方 frontend-skill 宽 pattern
    # 「前端.*界面」——负样本配对时序铁律（R V10.13.0）：排在宽 pattern 之后只会「让位」不会「接管」。
    # 双侧项目标识约束（须同时含 项目词 + 前端词，双向各允许 24 字间隔），通用前端查询不受影响。
    ("(ican|门店 ?ai ?管理智能体|门店 ?管理助手)[^，。；]{0,24}(前端|界面|样式|ui|css|模板|配色|令牌|设计体系|快照)|(前端|界面|样式|ui|css|模板|配色|令牌|设计体系)[^，。；]{0,24}(ican|门店 ?ai ?管理智能体|门店 ?管理助手)", "ican-frontend-design-system"),
    ("设计.*网站|网站.*前端|前端.*界面|网站.*界面|前端.*设计|设计.*前端|界面.*设计", "frontend-skill"),
    ("太丑了|界面.*丑|前端.*难看|页面.*难看|样式.*丑|ui.*丑", "frontend-skill"),
    ("好看点|美化一下|优化.*界面|界面.*优化|页面.*美化", "frontend-skill"),
    ("可视化.*html|html.*可视化|可视化.*页面|页面.*可视化|可视化.*展示|可视化.*项目", "chart-visualization"),
    ("落地页.*动画|动画.*落地页|科技.*落地页|落地页.*科技|科技感.*落地页|落地页.*科技感", "hyperframes"),
    ("^写个页面$|^做个页面$|^写个网页$|^做个网页$", "frontend-skill"),
    ("搞个.*落地页|弄个.*页面|整.*landing.*page|做个.*官网|做.*前端.*页面|做.*前端|写.*前端页面|前端页面", "frontend-skill"),
    ("文件.*太长|这个.*太大了|拆成.*几个|分.*小文件", "bigfile-split"),

    ("截个图|截屏|截图.*保存|屏幕.*截|抓个图", "screenshot"),

    ("画.*壁纸|生成.*壁纸|做个壁纸|换.*壁纸|来张.*壁纸", "byted-seedream-image-generate"),
    ("图.*改.*风格|换.*风格|改成.*水彩|改成.*油画|图.*编辑|改一下.*图", "byted-seedream-image-generate"),
    ("优化.*prompt|prompt.*改一下|提示词.*改改|prompt.*调一下", "A-prompt-better"),
    ("搞个.*视频|弄个.*视频|做个.*视频(?!片段|前三秒|钩子|分析)|整个.*视频", "byted-seedance-video-generate"),
    ("视频.*带.*配音|视频.*加.*旁白|视频.*配个音", "byted-seedance-video-generate"),
    ("截.*帧|截几帧|视频.*截.*图|抽帧|视频.*取.*帧", "video-frames"),
    ("ppt.*咋做|ppt.*怎么搞|演示.*怎么弄|slides.*搞一个", "pptx"),
    ("word.*写个|弄个.*word|搞个.*文档|写.*docx", "docx"),
    # R-fix(2026-09-22) 死目标清理: 原目标 `deep-research-pro` 已退役，且该 pattern 过泛
    #   （「搜一下/帮我搜」属任意查询）→ 删除直连，回落常规管线（BGE+LLM）。
    # ("搜一下|帮我搜|网上.*查查|查一下.*资料", "deep-research-pro"),
    ("微信.*监听|微信.*消息|监听.*微信|微信.*自动", "wechat-automation"),
    ("历史对话.*习惯|分析.*对话.*总结|总结.*习惯|分析.*历史.*习惯", "A-get-memory"),
    # R-fix(2026-09-22) 死目标重指: `skill-install` 已退役 → A-skill-manager
    ("装个.*skill|安装.*skill|skill.*装一下|github.*装.*skill|这玩意儿.*咋装|咋装|怎么装", "A-skill-manager"),
    # R-fix(2026-09-22) 死目标重指: `skill-creator` 不在注册表/磁盘 → A-skill-manager（技能增删改总管）
    ("创建.*skill|写个.*skill|搞个.*skill|新建.*skill", "A-skill-manager"),
    ("skill.*依赖|skill.*缺.*东西|skill.*跑不了|skill.*环境", "A-skill-manager"),
    ("打开.*网页|浏览器.*操作|自动.*点击|网页.*自动|浏览器.*填.*表单|自动.*填.*表单", "agent-browser"),
    ("electron.*操作|桌面.*应用.*自动|控制.*桌面", "electron"),
    ("gh.*ci|ci.*状态|检查.*ci|ci.*检查", "github"),
    # R-fix(2026-09-22) 死目标重指: `skill-install` 已退役 → A-skill-manager
    ("github.*技能|技能包|从github.*装|拉取.*技能", "A-skill-manager"),
    # 2026-09-09 审查专项: code-review 直连（须先于 github 的宽"代码.*审查"，
    # 否则本地代码审查任务被 github 二跳劫走；与 frontend-skill 负样本配对，
    # 审查类意图确定性直连，真设计任务"做个前端页面"不含审查词不受影响）
    ("全面审查|代码审查|审查.*代码|代码.*审查|code.*review|性能瓶颈|安全漏洞|可维护性|重复代码", "code-review"),
    ("代码.*审查|审查.*代码|code.*review|审查.*意见|审查.*项目|代码审查", "github"),
    ("创建.*pr|创建.*pull|提.*pr|pr.*创建|gh.*pr|pull.*request", "github"),
    ("ci.*跑挂|ci.*失败|ci.*挂了|pipeline.*失败|actions.*失败", "github"),
    ("操作.*notion.*客户端|notion.*桌面|notion.*客户端|桌面.*notion", "electron"),
    ("操作.*slack|slack.*桌面|桌面.*slack|控制.*slack", "electron"),
    ("callout|wikilink|笔记.*加.*callout", "obsidian-markdown"),
    ("解析.*pdf|pdf.*解析|pdf.*转.*markdown|pdf.*转.*md|文档.*解析|ocr.*pdf|pdf.*提取.*文本|扫描件.*识别", "pdf"),
    ("pdf.*改.*字|pdf.*编辑|pdf.*修改|编辑.*pdf|pdf.*里.*改|pdf.*水印|加.*水印", "nano-pdf"),
    ("hyperframes.*cli|npx.*hyperframes|渲染.*合成", "hyperframes-cli"),
    ("配音.*音频转写|配音生成|hf.*媒体|hyperframes.*素材", "hyperframes-media"),
    ("视频.*片段|做.*片段|标题.*卡片|title.*card|overlay|字幕.*动画|视频合成|html.*合成|合成动画", "hyperframes"),
    ("hyperframes.*registry|hf.*组件|安装.*hf|npx.*hf", "hyperframes-registry"),
    ("润色.*提示词|提示词.*润色|prompt.*润色|改改.*prompt|prompt.*改改", "A-prompt-better"),
    ("头脑风暴|brainstorm|想想.*需求|想.*新功能|构思一下", "A-ask-questions"),  # brainstorming 已退役(R201) → A-ask-questions(需求澄清)
    ("路由.*质量.*审计|命中率.*诊断|全链路.*诊断|路由.*审计", "A-skill-manager"),
    ("skill.*过时|定义.*过时|skill.*不匹配|工作流.*不匹配", "A-skill-manager"),
    ("sync_health|数据层.*不一致|死链.*清理|数据层.*修复", "A-skill-manager"),
    ("skill.*不被加载|skill.*每次.*不|为什么.*skill.*不|skill.*到底.*问题", "A-skill-manager"),
    # R-fix(2026-09-22): 去掉「无锚点的裸 `提出建议`」——它会劫持任何含该词的查询（实证：阶段5 审计
    #   「为优化我的所有自建skill及其所搭载的工作流提出建议」被直连到 vp-perspective-audit，
    #   而该意图应落审计族/skill 管理）。收窄为需带「项目/主线」锚点方可直连；`不足` 类锚点保留。
    ("主线.*不足|项目.*不足|还有哪些不足|有什么不足|不足在哪|不足.*建议|建议.*不足|阅读.*项目.*建议|项目文件.*建议|(项目|主线).*提出建议", "vp-perspective-audit"),
    ("vp.*视角|vp.*审计|预判.*agent|站在.*视角", "vp-perspective-audit"),
    ("subprocess.*编码|管道.*编码|cli.*管道|中文.*prompt.*传", "windows-cli-utf8-wrapper"),
    ("先.*重构|重构.*再|先重构", "refactoring"),
    ("分镜.*报告|视频.*分析报告|生成.*分析报告|钩子.*报告", "report-generator-skill"),
    ("超市.*订单.*没反应|订单.*提交.*没|下单.*没效果|下单.*按钮", "chaoshi-web-deploy"),
    ("mp4.*转录|转录.*文本|视频.*转录|音频.*转录", "video-whisper-transcribe"),
    ("canvas.*思维导图|思维导图.*canvas|json.*canvas", "json-canvas"),
    ("思维导图|思维地图|脑图|mind.*map", "diagram-maker"),
    ("debug一下|debug.*看看|排查一下|troubleshoot", "debugging-fixing"),
    ("git.*提交|commit一下|push一下|提交.*代码", "github"),
    ("docker.*部署|容器.*部署|docker.*跑", "chaoshi-web-deploy"),
    ("市场分析|竞品分析|行业研究|消费者洞察|品牌分析|咨询报告|优化建议|改进建议|项目建议|项目.*体检|评估.*项目", "consulting-analysis"),
    ("对标分析|项目对标|技术对标|开源项目.*对比|与.*开源.*对标", "consulting-analysis"),
    ("操作桌面|打开应用|桌面自动化|Windows.*自动|自动.*点击|自动.*打开", "computer-use-guidance-windows"),
    ("项目深度优化|项目方向优化|优化此项目|项目后续.*方向|项目.*下一步.*做|不知道.*下一步.*做|项目.*怎么优化", "A-project-better"),
    ("找.*技能|有没有.*相关.*技能|相关技能|匹配.*技能|技能.*发现", "find-skills"),
    ("技能市场|搜索.*技能|有没有.*skill|装个.*技能|find.*skill", "A-skill-manager"),
    ("无头.*浏览器|headless.*test|页面.*截图.*对比|表单.*测试|qa.*测试", "gstack"),
    ("写.*技术文档|写.*规格书|协作.*文档|文档.*协作|proposal.*写", "doc-coauthoring"),
    ("找.*cli|发现.*命令行|隐藏.*命令|桌面.*应用.*cli|藏.*命令行.*工具|挖.*命令行|桌面.*软件.*命令", "discover-agent-cli"),
    ("催款|催收|客户.*邮件|邮件.*客户", "internal-comms"),
    ("数据看板|仪表盘|看板.*配色", "chart-visualization"),
    ("bge.*(?:矩阵|嵌入|向量|模型)|嵌入矩阵|embedding.*矩阵|嵌入向量", "A-skill-manager"),
    # R-fix(2026-09-22) 死目标清理: `multi-search-engine` 已退役，无在役继任者 → 删除直连，回落常规管线
    # ("多引擎搜索|多搜索引擎", "multi-search-engine"),
    ("配置.*新平台|新平台.*(?:记忆|技能)|平台.*记忆树|平台.*技能树|新端.*接入|接入.*新端|配置.*记忆.*(?:tree|树)|记忆.*(?:tree|树).*配置|配置.*技能.*(?:tree|树)|技能.*(?:tree|树).*配置|记忆系统.*配置|配置.*记忆系统", "cross-platform-agent-sync"),

    # ====== R166 本地类 query 直连（2026-08-16） ======
    # local-* 技能（local-ocr-npu/local-tts/local-txt2img 等）为 TRAE 内置 Intel Local 系列，
    # 无 SKILL.md、不在路由系统技能集合，BGE 不可达。此处将本地类 query 直连到可达的合理技能：
    #   OCR/读图文字 → windows-native-ocr（Windows 原生 OCR，DIRECT_MAP 直连可达）
    #   TTS/同声翻译 → byted-mediakit-shared（mediakit-cli 本地工具，已移出 cloud_skills 守卫）
    #   本地图片生成 → byted-seedream-image-generate（唯一文生图技能，经本地守卫回落命中）
    ("本地.*ocr|npu.*ocr|npu.*识别|ocr.*识别.*图片|识别.*图片.*文字|图片.*识别.*文字|识别.*截图.*文字|截图.*识别.*文字|看看.*截图.*写了|截图.*写了什么|识别.*图片.*字|图片.*转.*文字|图片.*识别", "windows-native-ocr"),
    ("本地.*文字.*转.*语音|文字.*转.*语音|文本.*转.*语音|本地.*tts|tts.*生成|语音.*合成|文字转语音|文字.*合成.*语音", "byted-mediakit-shared"),
    ("同声.*翻译|同声传译|实时.*同声|实时.*翻译.*语音", "byted-mediakit-shared"),
    ("不用云端.*生成.*图|本地.*生成.*图|本地.*文生图|local.*本地.*生成|本地.*生成.*图片|本地.*画图", "byted-seedream-image-generate"),

    # ====== R-fix(2026-08-16) 盲测失败 query 直连补全（layered_testset 25 失败案例） ======
    ("灵感.*枯竭|发散.*点子|点子.*发散|发散一波", "story"),  # brainstorming 已退役(R201) → story(创作发散)
    ("高颜值.*落地页|做个.*落地页|做.*落地页|落地页$", "frontend-skill"),
    ("打开.*windows.*设置|windows.*设置|改.*系统.*配置|系统配置", "computer-use-guidance-windows"),
    ("skill.*权威.*规则.*冲突|权威.*规则.*冲突|检测.*skill.*冲突", "A-skill-manager"),
    ("注册表.*漂移|skill.*漂移|漂移.*修复", "A-skill-manager"),
    ("命中率.*提升|提升.*命中率|命中率.*pipeline|提升.*pipeline", "A-skill-manager"),
    ("任务.*中途|中途.*重跑|重跑.*匹配|skill.*匹配.*检查", "A-skill-manager"),
    ("一次性.*原型|原型.*验证|技术.*路子|spike", "spike"),
    ("收件箱.*分类|inbox|triage", "taskflow-inbox-triage"),
    ("副总.*视角|副总视角|审计.*agent.*行为|行为模式.*审计", "vp-perspective-audit"),
    ("委派.*编码|派给.*codex|codex.*委派|后台.*编码", "coding-agent"),
    ("总结一下|帮我总结|^总结$", "A-get-memory"),
    ("加载记忆|记忆.*加载", "A-memory-start"),
    ("写周报|周报", "internal-comms"),
    ("公司.*调查|调查.*公司|企业.*调查", "天眼一下"),
    # R-fix(2026-08-16) 续: 剩余 2 条盲测失败
    # '推荐个工具'→find-skills(技能推荐)；'显存不够用了咋限制'→c-cleanup(资源管理, local-vram 不可达)
    ("推荐个工具|推荐.*工具|工具.*推荐", "find-skills"),
    ("显存.*不够|显存.*限制|限制.*显存|显存.*满|显存.*咋", "c-cleanup"),

    # ====== R198.9 盲区 ROI 直连落地（2026-08-16, 依据 eval/blind_spot_roi.py 真实盲区分析） ======
    # 真实盲区 758 条 (3.28%) 的高频前缀映射。目标 skill 均已核验注册（退役 skill 不映射）。
    ("世界杯.*年|哪年.*世界杯|世界杯.*在哪", "NONE"),
    ("显存不够|显存.*用|显存.*不足|显存不够用了", "c-cleanup"),          # local-vram 已退役 → c-cleanup(可达)
    ("讲讲我的使用|我的使用习惯|使用习惯.*记", "A-get-memory"),
    ("会议材料提前|会议.*材料|提前.*会议材料", "NONE"),                  # meeting-intelligence 已退役 → NONE(宁直答不短路)
    ("两个功能重复|功能.*重复|重复.*技能.*合并|技能.*重复", "A-skill-manager"),  # 2026-09-21 修：skill-merge 在役 → 由 skill-manager 改指（原映射源于退役期）
    ("磁盘快爆|磁盘.*满|磁盘不够|磁盘.*清理|磁盘清理", "c-cleanup"),
    ("灵感枯竭|发散.*点子|帮我发散|没灵感|没有灵感", "story"),
    ("本地文字转语|文字转语音|文字.*转语音", "byted-mediakit-shared"),   # local-tts 已退役 → byted-mediakit(可达, TTS 职责)
    ("让另一个大模|另一个大模型|交叉复核.*方案|大模型交叉", "oracle"),     # 2026-09-21 修：oracle 在役(research) → 由 A-ask-questions 改指
    ("shadcn|组件注册表|components\\.json|组件.*安装.*管理", "shadcn"),   # 2026-09-21 修：shadcn 在役(design)，中文查询命中不到英文正文 → 直连兜底
    ("苹果和香蕉哪个热量|香蕉和苹果哪个热量", "NONE"),
]
