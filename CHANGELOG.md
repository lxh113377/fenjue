# Changelog

格式参考 Keep a Changelog；**版本号只在 GitHub Release 上成立**（tag + 资产），
本文件记录每次对外可见的行为变更，条目必须带可复算依据（命令或 run id）。

## v1.0.0 — 2026-09-29

对外子集首个版本。仓库由私有源仓的**已提交 SHA** 单向生成（见 `PUBLIC-SUBSET.md`），
刻意不含个人记忆语料、会话日志、技能正文与模型权重。

### 新增

- **MCP 服务面** `eval/mcp_server.py`：`route_skill` / `list_skills` / `hitrate_report`
  三个工具，stdio 传输，走官方 SDK（mcp 2.x）。此前本仓只有 CLI，agent 要用这套
  路由必须自己 shell 出去解析 stdout。行为回执在测试里（真握手，不是"文件在场"）：
  `eval/tests/test_mcp_server.py::TestStdioHandshake`。
- **Agent Skills 标准目录格式可评估**：`hitrate_cli.py --skills-dir` 现在直接吃
  `<name>/SKILL.md` 布局（与 anthropics/skills 同形），免翻译成扁平 `*.md`。
  示例见 `examples/agent-skills/`（格式演示用，3 个技能不构成命中率评价）。
- **规模基准** `eval/bench_router.py`：合成档案 12/100/500/1000 规模的建索引耗时、
  单查询延迟中位与 p95、峰值分配，并做检索有效性抽查。本机实测（Python 3.12.2 /
  Windows-AMD64，预热后取 3 趟中位）：1000 规模 建索引 0.0446s、单查询 p95 0.1069ms、
  峰值分配 6.465MB。复算命令 `python eval/bench_router.py --sizes 12,100,500,1000`。
- **主打 CLI 首次有测试** `eval/tests/test_hitrate_cli.py`（14 例，含两种布局、
  零输入 rc=2、期望技能不在清单 rc=2、扁平面回归值锁定）。此前该入口在公开面的
  引用测试数为 **0**（`grep -rl hitrate_cli eval/tests/ | wc -l` 实测）。
- `SECURITY.md`：漏洞定义四类 + 报告渠道 + 已知结构性风险。**此前 README 已引用它
  而文件不存在**（死引用，2026-09-29 实测）。
- `.gitignore`：AGENTS.md 承诺「个人记忆库通过 gitignore 隔离」而公开面没有该文件。
- `CHANGELOG.md`（本文件）、`.github/ISSUE_TEMPLATE/`（3 份表单）、
  `.github/PULL_REQUEST_TEMPLATE.md`。

### 修复

- **CI 主分支判红两根因**（run `36466792735` 日志直读）：
  ① `pyproject.toml` 的 addopts 带 `--timeout=120`，而 CI 只装 `pytest`，
  未装 `pytest-timeout` ⇒ pytest rc=4（`unrecognized arguments`），整条测试步
  一根判据都没跑到；② `flask` 是随包分发的 `feedback/app.py` 的运行依赖，
  却只写在 `requirements-ci.txt` ⇒ 按 README 装 `requirements.txt` 的评委面
  实测 3 条 `ModuleNotFoundError: No module named 'flask'`。
- **文档死引用**：`AGENTS.md`/`index.md`/`CONTRIBUTING.md` 里的
  `scripts/check_public_clean.py` 改为实际在场的 `scripts/public_clean_check.py`；
  两处结构表把未随包分发的 `skill_tree/` 换成实际分发的 `examples/`。
- **`eval/check_doc_links.py` 的取数面**：此前是硬编名册（含私有源仓的
  `AGENTS.md.part1..5.md`、`STATUS*.md`），在公开面一上来就印「7 个文件缺失」
  并 rc=1——量的是「名册与另一个面不符」而不是「链接坏了」。改为 glob 派生，
  并加两条：取数面为空判 UNVERIFIED（rc=2，盲区≠零），PASS/FAIL 行印扫了几份文档。
- `eval/hitrate_cli.py`：`load_skills()` 重写为两布局合一，同名时标准目录优先；
  扁平面读数回归锁死在 `easy 5/5、medium 3/4、hard 2/5、合计 Top-1 10/14`
  （改分词器必然撞红该测试，这是有意的）。

### 已知未做（不藏着）

- PyPI 发布与真 `pip install .`：需要把 `eval/` 做成真 package，牵动 74 个测试模块
  的导入面与派生 JSON 语料的打包语义，本轮按前提未做，并从 pyproject 撤掉了
  那条装不出来的 `[project.scripts]`。
- `ruff check .` 在公开面实测 88 处告警（69 处可自动修），因此**没有**接进 CI；
  接进去而不清完，等于给下一个贡献者造一把必红的尺子。
