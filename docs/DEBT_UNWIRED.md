# 在场但未接线的判据与已知债（逐条带实测 rc）

> 立这份清单的原因：对标轮发现本仓有**判据在场却不敢接 CI**的情况（一接就红，红因还是
> 「判据量了另一个面」）。"没接"本身不是问题，**没人知道没接**才是问题。
> 本文件每条都给：命令、本轮实测 rc、红因、接线前提。前提未满足前禁止为了让 CI 绿而改语料凑数。

| id | 对象 | 本轮实测 | 状态与接线前提 |
|---|---|---|---|
| L-1 | `ruff check .`（全仓） | **2026-09-29 部分闭合**：`ruff 0.16.5` 全仓 **73 ⇒ 34**（F401 54⇒34、E741 16⇒0、F841 2⇒0、E701 1⇒0；`pytest` 回归见本轮提交）。其中：① 前提已兑现——`eval/tests/test_reexport_surface_guard.py`（5 腿：基线等式＋属性在位＋2 条变异精确等式）锁死 vtc＋8 分片共 53 个「导入但词法未用」名，基线 `eval/reexport_surface_baseline.json` 随仓提交（活算总数与 ruff 独立对上 53=53；基线 key 固定 `/` 防 Linux 面红）；`verify_truth_consistency.py` 的 20 个重导出名已逐行 `# noqa: F401` 标注意图。② 安全删除 3 处（`diagnose_session.cite_sec` 死存、`status_layer.uni_ok` 死存、`split_md_4kb` E701 展行）＋16 处 `l`→`ln` 改名（逐处核对作用域，跨行绑定一并改全）。③ 剩余 34 ＝分片 stdlib 前言 31＋vtc `glob/time` 2（有守卫无 noqa，删即红，须 deliberate 基线更新）＋`build_indexes.py:59` 的 `GLOBAL_MEMORY` 1（源仓共面文件，本轮不动）。**全仓面仍不接**（33＋1 未清），scoped 名册保留 | 未接全仓面；scoped 名册＋新守卫测试已接（CI 跑全量 pytest 即覆盖） |
| L-2 | `eval/check_gate_wiring.py` | **2026-09-29 已闭合**：按面选目标落地（`detect_face()`：GM 根不可达或为字面量占位即 subset 面；`run_checks()` 单实现，`verify_truth_consistency._cgw_run` 同走该实现，双源合一）。子集面核三项：版本化 hook 副本（W1-subset）＋ CI 门禁链引用（W4-subset：verify/doc_claim_face/command_face_parity/spec_check 任一在场且脚本存在）＋ pre-commit 声明解析（W7-subset，零钩子判红）；GM 两项记 SKIP 不计通过。7 条测试腿（真面零失败＋4 条专属反例精确等式＋full 面无泄漏），`eval/tests/test_check_gate_wiring_face.py` 全绿；已接进 `ci.yml`（"Gate-wiring self-check selects face" 步），名册（jobs 级）不受影响，`workflow-spec check: PASS` | 已接线（ci.yml 新步骤；C19 经 `_cgw_run` 同面自动转绿，待复算） |
| L-3 | `mypy`（配置在场，`[tool.mypy]`） | **2026-09-29 前提兑现一半**：三个对外入口 `eval/command_face_parity.py`＋`eval/fenjue_cli.py`＋`scripts/mcp_stdio_smoke.py` 共 8 处告警清零（`_version` 返回标注与实现对齐、stdio 管道 None 显式收窄为 rc=2、tomllib 守卫式回退加 `type: ignore`），`mypy` 单文件复算零告警且各自回归（selftest/test/mcp 握手）全绿。全仓由 72 errors/37 files ⇒ **62 errors/34 files（checked 262）**，仍无 CI 步骤（第一版即 60＋ 行的尺子接进去仍是必红闸）。接线前提不变：继续按文件分批收敛，全仓清零那一刻才接 | 无 CI 步骤；入口三文件零告警已达成（与 scoped 名册同一形状，待接 `mypy <具名清单>` 步） |
| L-4 | PyPI 发布 | `curl https://pypi.org/pypi/fenjue/json` ⇒ 404（本轮实测） | 包已可 `pip install .`（wheel 592KB 实测装通，三个入口在仓外跑绿，见 CI 的 install-face job），但**发布到 PyPI 需账号与 Trusted Publishing 配置**，归归属方裁。未发布前对外一律写「从源码安装」，禁写 `pip install fenjue` |
| L-5 | `docs/` Pages 站点 | **已闭合**：Pages 源经 API 设为 GitHub Actions（`build_type=workflow`），部署 run `36478918872` completed/success，站点实测 **HTTP 200／2,699 B**（2026-09-29 04:2x +08，本机直连） | 复算：`gh api repos/lxh113377/fenjue/pages --jq .html_url` 与 `curl -sI https://lxh113377.github.io/fenjue/`。可达性一律带时刻——同一地址同日 03:5x 实测是 404（那时尚未建站），所以文档里每条在线链接都注了测量时间，禁把 200 当永久事实 |
| L-6 | `.ci/contract.json` | **2026-09-29 已闭合**：`repo` 改 `lxh113377/fenjue`、`branch` 改 `main`；第四项 `greencheck-selftest` 引用仓外 `<SKILLS_ROOT>` 脚本（公开面不存在，恒不可执行）⇒ 换成仓内 `scripts/ci_workflow_spec_check.py`（名册⇄workflow 对账，实测 PASS）。JSON 解析＋四命令存在性＋三可跑项 rc 已复算（verify 本体在裸 clone 面 11 PASS/5 FAIL，改前后 stash 对照零差异，属源仓面事项不在本轮射程） | 预推送检查契约（四命令均可在干净签出执行） |

## 本文件自身的可复算性

```bash
python -m ruff check . ; echo rc=$?                       # 期望 rc=1，计数见 L-1
python eval/check_gate_wiring.py ; echo rc=$?             # 期望 rc=1，红因见 L-2
curl -s -o /dev/null -w "%{http_code}\n" https://pypi.org/pypi/fenjue/json   # 期望 404
python scripts/ci_workflow_spec_check.py ; echo rc=$?     # 期望 rc=0（名册改造后已接线）
```

⚠️ 上列数字是 **2026-09-29 的时点读数**，不随仓库演进自动成立；引用前先重跑。
每条的「前提」写的是**修复会产出的代码标识符或命令**（如 `pages.yml`、scoped 名册），
不写散文式期望——散文前提永远不会变红，也就永远无人执行。

## 〔2026-09-29 轮173 追加〕新判据 `command_face_parity.py` 的自身限度

接它的时候报告 M-8 只剩后半句（「未做逐 claim 双向 diff 工具」）。它现在**只**核三样语言无关对象：
入口点、子命令、测试命令行。以下形态**不在射程**，据实登记，不许被一句"双语已对账"盖过去：

| id | 对象 | 现状与限度 | 前提 |
|---|---|---|---|
| L-10 | 散文式主张的双语对账 | **2026-09-29 半闭合**：数字表这一格有了显式句柄——`eval/check_readme_numbers.py` 核 README 分层表 4 行 12 格 ⇄ `hitrate_cli.evaluate` 同批函数活算（top=3），`--selftest` 3/3（真面绿＋改格精确点名＋删表 UNVERIFIED），已接进 `ci.yml`/`ci-pr.yml`。散文 claim 仍不核（第一版 53 处噪声的前车之鉴仍成立，R236 补注③）。要扩到散文，前提不变＝先给"同一主张"显式句柄（如两面同段锚点），而不是回去猜语义 | 数字表已接线；散文面待锚点 |
| L-11 | 链接/URL 的双语一致性 | 不核。曾实现过一版"两面 URL 集合相等"，真面首跑命中 2 处且**都该放行**（中文面链 CI workflow 页、英文面链 actions 首页，两个都是活页）——它是"教作者改语料"形状的闸。链接是否死由 `check_doc_links.py` 判（同事实一处判，不双载体） | — |
| L-12 | `docs/*.md` 与 `index.md` 的命令面 | 只核 `llms.txt`（本轮 llms 缺 3/4 入口点就是它抓的）；`docs/INSTALL*.md` 未进 FACES | 前提＝先量各册的合法面差异（安装册本就该只写该端命令），否则接进去就是一把必红闸 |



## 〔2026-09-29 对标第 79 轮追加〕L-1 的重跑值，与「文档计数族」这条新盲区

> 〔轮173 复核〕下面那句「0.16.5 下午重跑为 **122 errors / 97 fixable**」与轮173 在同一条命令
> `python -m ruff check --statistics .`（尺子同为 `ruff 0.16.5`，工作树 = 本仓 `4030395`）实测的
> **88** 不等。两句都自称同一把尺，差 34 处却**没有一句记下取数面**——这正是本文件 L-1 上面
> 「lint 计数必须同时写尺子版本」没写完的另一半：**还须写哪棵树、哪个 rev**。
> 现值以轮173 的 88（safe autofix 后 73）为准；122 那句原样保留不删（它是当日某个面的时点读数，
> 历史留痕不改写），但禁止再当现状引用。复算＝
> `git rev-parse --short HEAD && python -m ruff --version && python -m ruff check --statistics .`

`python -m pip install "ruff==0.16.5" && python -m ruff check . | tail -2` 当日下午重跑为
**122 errors / 97 fixable**（本表 L-1 与 `README.md` 先前写的 88/69 是同一天上午的面）。
⚠️ **lint 计数必须同时写尺子版本**：本机 0.16.9 与 CI 钉的 0.16.5 这次给出同一个数，
但「88→122」在没有版本号的情况下无法归因是回归还是换尺——这是本轮实测到的取数面缺陷。

同轮新增判据（已接线，非在场未接）：`eval/doc_claim_face.py` 原先只核**端数**一族，
本轮补上「测试模块（在仓/摘除两个合法现算值）」与「pytest 汇总行（与同一次跑批对账）」两族，
`--selftest` 由 3 腿增至 12 腿；CI 侧新增 `README face parity` 步把跑批日志喂进去。
由此产生的**新盲区**（据实登记，不假装覆盖）：

| id | 对象 | 现状 | 前提 |
|---|---|---|---|
| L-7 | `doc_claim_face.py` 族[pytest汇总] | 只在**有跑批日志**的面生效；本机直接跑 ⇒ 记盲区、不判通过 ⇒ 该族在本地等于没核 | 本机侧要真核，需 `python -m pytest 2>&1 \| tee /tmp/p.log` 后 `python eval/doc_claim_face.py --from-pytest-log /tmp/p.log`（两步都得 rc=0） |
| L-8 | 族[测试模块] 的合法值集合 | 放行 {在仓 74, 摘除 20}；若有人把「在仓数」误写成摘除数，本族**放行**（第一版用同行关键词分面，两处方向都判错，故改为集合放行） | 想收紧成逐句分面，前提＝文档给出显式面标记（如 `[在仓]`/`[摘除]` 语法）并由 `doc_claim_face.py` 解析，而不是再回去猜散文 |
| L-9 | `--audit-receipts`（计数断言缺复算留痕） | **只报不拦**：本轮真面命中 18 行。按 R236 补注③，一条第一版就命中 18 行的尺子没有资格直接当闸（会把人逼成删数字而不是补命令） | 升档前提＝该 18 行逐行补上复算命令后，`--audit-receipts` 命中降到 0，再把该行改判红并补变异腿 |

