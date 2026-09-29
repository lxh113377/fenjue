# Changelog

格式参考 Keep a Changelog；**版本号只在 GitHub Release 上成立**（tag + 资产），
本文件记录每次对外可见的行为变更，条目必须带可复算依据（命令或 run id）。

## Unreleased — 2026-09-29（轮173：双语命令面对账 + 一处「教人跑出一条没有用例数的绿」）

对标报告 §4 的 M-8 只完成了半边（「已重写英文面并接线判据；未做逐 claim 双向 diff 工具」），
本轮补上，并按报告 §5 的顺序推进 L-1。取证时点 2026-09-29 17:4x–18:2x，全部本机实跑。

### 新增

- **`eval/command_face_parity.py`**（doctor 第九项自检，进 `ci.yml` / `ci-pr.yml` 双闸）：
  判「对外声明的命令面」三面一致——入口点取 `pyproject [project.scripts]`、子命令取
  `fenjue --help` 的 argparse 自述行，两面（`README.md` / `README.en.md`）+ `llms.txt` 逐条对账。
  它补的是 `doc_claim_face.py` 盖不到的那一格：后者判「每面各自 ⇄ 真相源」，两面彼此不看，
  于是"两面都自洽、但一面承诺了另一面没有的用法"能双双溜过。
  反向腿 9 项（1 对偶 + 6 注入/回归 + 2 盲区），复算＝`python eval/command_face_parity.py --selftest`。
  **本件自己第一版被反例腿咬到两处判据缺陷**（不是语料缺陷）：`\s+` 跨行把散文里的行尾
  `fenjue` 与次行 `python` 拼成一条假承诺；`(\S.*)?` 让 `python -m pytest -q`（pytest 与 -q 之间
  是空格）整行不匹配 ⇒ 判据对它最想抓的那个形状直接失明。两条都补了钉死它们的回归腿。

### 修（接线第一次跑真面就抓到的）

- `llms.txt` 只列了 **1/4** 条 console script——`llms.txt` 是给 agent 读的机器友好面，
  按它装完的 agent 拿不到另外三条命令。补 `Installed commands` 一节（四条入口点 + 七个子命令）。
- `README.en.md` 两处教 `python -m pytest -q`：`pyproject` 的 `addopts` 已带 `-q`，再叠一次就是
  `-qq`，而 `-qq` **不打** `N passed, M skipped` 那一行 ⇒ 评委照英文面跑完，拿到的是"一份没有
  用例数的绿"，而本仓 CI 的 `README face parity` 步判的正是那一行。同一条缺陷今天在本机
  复现脚本上咬过一次（回执里 `PYTEST_RC=0` 后面确实没有汇总行）。两侧实测：
  `pytest` ⇒ `669 passed, 49 skipped`；`pytest -q` ⇒ 零条汇总。`.github/ISSUE_TEMPLATE/bug.yml`
  里的同形建议一并改。
- 撤掉四处写死的计数（`8 项自检`×3、CI 面汇总值×1）改为复算指针：一次正常提交就变不了绿的
  数字没资格留在散文里——本仓自己的立身主张就是「写死数字会被抓」。

### L-5：`examples/agent-skills` 从「格式演示」补成**能承载命中率评价**的语料

报告原话是「现仅 3 个互不重叠技能 ⇒ 命中率 100% 无评价意义」。那 100% 不是成绩，是语料没有判别力。
本轮把这一面扩到 **15 件合成技能 / 34 条查询**（easy 14 · medium 5 · hard 15），触发词**故意**撞车：
`日志` 同属 `log-triage` 与 `log-archive`、`数据` 同属 `csv-clean` 与 `data-sync`、
`构建` 同属 `docker-build` 与 `ci-pipeline`、`字段` 同属 `schema-audit` 与 `api-doc`。

本轮实测（复算＝`python eval/hitrate_cli.py --skills-dir examples/agent-skills/skills --queries examples/agent-skills/queries.json --top 3`）：
easy 13/14 = 92.9% · medium 4/5 = 80.0% · **hard 8/15 = 53.3%** · 合计 top1 25/34 = 73.5%、top3 30/34 = 88.2%。
hard 档那个 53.3% 是这张表里最有用的数——它证明语料问得出路由器答不出的地方，
MISS 逐条可看（`--show-cases`），例如「给这个看板配一张趋势图」被判到 `dashboard-build` 而期望 `chart-render`。

测试侧同时换立场：`test_hitrate_cli.py` 不再断言「标准面恒全对」（那句是把 100% 当验收），改判**结构判别力**——共用触发词少于 3 个即判红（`test_standard_corpus_can_discriminate`）、hard 档少于 10 条判红、每条查询的期望技能必须在语料里；另按 flat 面同一惯例把对外数字锁进测试（改分词器或权重必然撞红，有意如此）。
### 全仓 lint（L-1）：量到 73，但**没有**接全仓闸

`ruff 0.16.5`（与 CI 同一把尺）实测 88 ⇒ safe autofix 后 **73**（`669 passed, 49 skipped` 不回退）。
剩下这 73 处不是"再努力一点"的问题，两处有结构性前提：
① `eval/verify_checks/*_layer.py` + `verify_truth_consistency.py` 的 54 处 F401 是**分片模块共用
   一段 import 前言**，其中被跨片属性代理 `_CHECK_HOME` 晚绑定的那些删不得——autofix 真删过一次，
   后果是 4 条用例 `AttributeError: SKILL_CONTENT`（当场被测试拦下，已整族回退）；
② 16 处 E741 的 `l` 里有 4 处绑定跨行（`for l in links:` 的函数体在后续行、两处推导式续行），
   按行改名必坏，需要作用域级改写。
⇒ 全仓面不接，scoped 名册保留并补进本轮两个新件。逐条前提见 `docs/DEBT_UNWIRED.md` L-1。

### 账面（同一把尺的两个时点）

| 面 | 本轮起点（`4030395`） | 本轮后 |
|---|---|---|
| 本机评委面（真 venv + 干净 clone） | `655 passed, 49 skipped` | `669 passed, 49 skipped`（+14 条，全为新判据的腿） |
| 测试模块 | 74 | 75 |
| doctor 随包自检 | 8 | 9（`command-face-parity`） |
| 全仓 ruff（0.16.5） | 88 | 73（未接全仓面，前提见上） |
| 跟踪文件 | 431 | 433 |



## v1.2.0 — 2026-09-29（轮167：易用性轴与「实际使用案例」轴补齐）

第三轮对标的取证对象换成易用性样板：`cli/cli`（单一 `gh` 总命令 + docs/primer/getting-started，70 个 docs 文件）、
`gptme`（**`gptme/cli/doctor.py` + `gptme/cli/onboard.py`** 与 8 个以上 console script）、
`memodb-io/memobase`（`docs/site/quickstart.mdx` + `assets/quickstart.py`）、`getzep/zep`（按语言分目录的 `examples/`）。
对照之下我方缺的不是能力而是**入口形状**：三个分立命令、没有总入口、没有一条命令问「这台机器哪条链通」、
没有「实际使用案例」文档载体（而赛道官方描述第三格正是它）。

### 新增

- **统一入口 `fenjue`**（`eval/fenjue_cli.py`，console script `fenjue`）：子命令
  `route` / `eval` / `bench` / `mcp` / `doctor` / `mcp-config`，另有 `--version`。
- **`fenjue doctor`**：串跑 8 项随包自检（脱敏闸双向自证、文档链接、端数对账、workflow 名册、
  两条命中率面、基准 smoke、MCP 真握手），逐条给 rc。三条边界写成行为而非文案：
  载体不在场 ⇒ 跳过并给原因（不计通过）；零检查 ⇒ rc=2；任一红 ⇒ rc=1 且点名。
- **`fenjue mcp-config --client claude|qoder|generic|codex`**：输出可直接粘贴的接入配置
  （JSON / TOML 两种形态），并在 stderr 注明命令面来源是装好的 `fenjue-mcp` 还是源码树
  `python -m eval.mcp_server`——不给来源的配置就是让人照着跑不通的配置。
- **`docs/CASE_STUDY.md`**：四组实际使用案例，每组带「当时遇到什么 → 哪条判据抓到 → 现在能一条命令复算什么」。
- 新增测试 `eval/tests/test_fenjue_cli.py` 12 例：版本单源自证、route 排序与空清单 rc=2、
  配置生成 JSON 可解析 / TOML 有节头 / 未知 client 被拒、doctor 全绿真跑一次 +
  注入必红检查必须点名 + 载体缺失记跳过 + 零检查判 rc=2。
- CI 两处新面：build job 跑 `doctor --json` 并断言聚合到 ≥8 项且逐项 rc 一致
  （判的是聚合面本身，不是重复判各单项）；install-face 跑装出来的 `fenjue --version` /
  `fenjue route` / `fenjue mcp-config` 并 `json.loads` 校验配置生成物。

### 修复

- **版本单源化**：`eval/__init__.py` 里那份 `__version__ = "1.1.0"` 删除，运行时一律经
  `_version()` 读分布元数据或 `pyproject.toml`；两处都读到且不等 ⇒ 报 `DRIFT` 并 rc=2。
  同一事实存两份是本仓这三轮里被自己判据抓到最多次的形态。
- **`scripts/mcp_stdio_smoke.py` 的参数拆分按平台分档**：posix 模式的 `shlex.split`
  会把 Windows 路径里的反斜杠当转义吃掉（`C:\Users\…\python.exe` → `C:Users…python.exe`，
  实测 doctor 因此起不来服务）⇒ `posix=(sys.platform != "win32")`，并新增 `--server-arg`
  可重复参数，让调用方不再把参数拼进单个命令串。
- **`doctor --json` 的回执不再污染 stdout**：结论行改走 stderr，否则 stdout 是
  「JSON + 一行尾巴」，`json.loads` 报 Extra data——判据自己的输出格式也是契约。

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

### 修复（第二轮落地时抓到的假判据）

- **install-face 第一次跑就抓到一条"忽红忽绿"的尺子**（run `36478129692`）：MCP 握手原用
  `printf frames | fenjue-mcp` 写，printf 写完即 EOF，Linux runner 上服务端还没答 `tools/list`
  就退出 ⇒ `grep -q` 对空文件判红；而**同一条命令在 Windows 能拿 1,304 字节完整回包**。
  一段在两个面行为不同的 shell 不能当判据 ⇒ 改为仓内探针 `scripts/mcp_stdio_smoke.py`
  （Popen + 读线程 + 显式等待条件，与 `eval/tests/test_mcp_server.py::TestStdioHandshake` 同机制），
  并补两条反例腿实测：服务起不来 ⇒ rc=2；起得来但从不应答 ⇒ rc=1（`--wait 5`）。
  探针现在 build job（从仓内起服务）与 install-face（装出来的 `fenjue-mcp`）各跑一次，
  免得「装出来的能握手、仓里的不能」这种半瘫状态被单条步掩盖。

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
