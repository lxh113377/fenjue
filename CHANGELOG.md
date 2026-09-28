# Changelog

格式参考 Keep a Changelog；**版本号只在 GitHub Release 上成立**（tag + 资产），
本文件记录每次对外可见的行为变更，条目必须带可复算依据（命令或 run id）。

## v1.1.0 — 2026-09-29（轮166：打包分发面打通 + CI 拆双闸 + 名册化判据）

对标第二轮的取证对象换成「上手路径最短」的样板：`gptme/gptme`（26 个 console script + PyPI +
仓内 sphinx 文档站 + release 作业带 cron）、`pre-commit/pre-commit`（一行装、204 次 PyPI 发布）、
`pydantic/pydantic-ai`（34 条 workflow / 21 条定时）、`letta-ai/letta-code`、`microsoft/autogen`
（对照用：近 90 天 0 提交、PyPI 停在 2025-09-30）。结论是「clone→装→跑」这条链我方当时**断在装**：
入口点 0 个、PyPI 404、`homepage` 为 null。

### 新增

- **可安装**：`[build-system]` + `packages=["eval"]` + `package-data` + 三条入口点
  `fenjue-hitrate` / `fenjue-bench` / `fenjue-mcp`；依赖走 `dynamic = ["dependencies"]` 读
  `requirements.txt`，**不在 pyproject 再抄一份版本**（抄第二次就是下一处双真相）。
  实测：wheel 592 KB；装进新建 venv 后三条命令**在仓外**（cwd 换成临时目录）跑出读数，
  MCP 那条回包含 `protocolVersion` 与两个工具名。`eval/__init__.py` 因此出现，
  兄弟模块导入改成「先相对、失败退回绝对」，避免同一模块装后出现两个实例。
- **CI 拆双闸**（对标 mem0 的 `ci-gate.yml` / `pr-gate.yml`）：`ci.yml` 只跑 push（全档 + 覆盖率地板
  + `install-face` 独立 job），`ci-pr.yml` 跑 PR 快档。拆的理由是归因不是省算力——本仓常有并发会话在写。
- **`bench-nightly.yml`**：cron + `workflow_dispatch`，跑 12/100/500/1000 全量基准并上传 artifact
  （`if-no-files-found: error`，产物空了不许算跑过）。装面 smoke 刻意**不**重复放这里：同一事实只许一处判。
- **`pages.yml` + `docs/index.html`**：把 `docs/` 发成 Pages，补 `homepage` 落点。
  在实测到 HTTP 200 之前，仓内任何文档都不写"在线演示"（本轮此前刚清掉一条 404 的假演示链）。
- **`docs/DEBT_UNWIRED.md`**：在场但未接线的判据清单，逐条带本轮实测 rc 与「接线前提」
  （前提只写修复会产出的代码标识符/命令，写散文前提就永远不会变红）。

### 修复

- `scripts/ci_workflow_spec_check.py` 的硬编作业名册（8 个属**私有源仓** CI 形态）改为读
  `.ci/workflow_jobs.json`；名册缺失/为空判 **UNVERIFIED** 不判 PASS。改造后本判据第一次在子集面
  跑绿（实测 `PASS: 名册 5 个作业全部在声明的 workflow 文件里定义`）并接进 `ci.yml` / `ci-pr.yml` /
  nightly 三处。同族缺陷本轮已在 `eval/check_doc_links.py` 上抓到并修过一次。
- scoped lint 棘轮接 CI：对本端新增文件 + 三个对外入口跑 `ruff==0.16.5`，实测 rc=0；
  全仓仍 88 处（其中 69 可自动修）未清，因此**没有**接全仓面（见债册 L-1）。修掉的 2 条是本端自己写的
  `bench_router.py`（`F841` 未用变量、`E741` 歧义名 `l`）；顺带把基准的抽查改成复用计时趟的 top-k，
  不再多跑第四趟打分——「计时的那次」和「被检查的那次」必须是同一次。

### 未做（前提写在债册）

- PyPI 发布（需账号 + Trusted Publishing）；`mypy` 未量过公开面告警故不接（L-3）；
  `eval/check_gate_wiring.py` 判的是本机钩子面，未做按面选目标前不接 CI（L-2）。

回归面：本机 pin 环境 `652 passed, 48 skipped`（与 v1.0.0 同数，加 `eval/__init__.py` 未造成用例流失）；
`doc-links` / `doc-claims` / `spec-check` 三判据 rc=0。

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
