# 在场但未接线的判据与已知债（逐条带实测 rc）

> 立这份清单的原因：对标轮发现本仓有**判据在场却不敢接 CI**的情况（一接就红，红因还是
> 「判据量了另一个面」）。"没接"本身不是问题，**没人知道没接**才是问题。
> 本文件每条都给：命令、本轮实测 rc、红因、接线前提。前提未满足前禁止为了让 CI 绿而改语料凑数。

| id | 对象 | 本轮实测 | 状态与接线前提 |
|---|---|---|---|
| L-1 | `ruff check .`（全仓） | **轮173 复尺**：`ruff 0.16.5`（与 CI 同一把尺）本轮起点实测 88 ⇒ safe autofix 后 **73**（`669 passed, 49 skipped` 不回退，`git ls-files \| wc -l` = 433）。余量构成：54×F401（全在 `eval/verify_checks/*_layer.py` 与 `eval/verify_truth_consistency.py`）＋16×E741（`l`）＋2×F841＋1×E701 | 未接全仓面，scoped 名册保留（本轮把 `eval/command_face_parity.py` 与其测试件补进名册）。**两处结构性前提，不是"再努力一点"**：① autofix 真删过 `verify_checks` 分片共用的 import 前言，4 条用例当场 `AttributeError: SKILL_CONTENT`——那批名字由 `verify_truth_consistency.py` 的 `_CHECK_HOME` 跨片属性代理**晚绑定**，F401 看不见这个读者（已整族回退，回退后全绿）；前提＝给该代理补一条「删任一分片的 import 必须变红」的守卫腿，再谈逐行 `# noqa: F401`；② 16 处 `l` 里有 4 处绑定跨行（`for l in links:` 的函数体在后续行、两处推导式续行到下一行），按行改名必坏，前提＝作用域级改写（AST）而不是按行替换。直接接全仓等于造一把必红的闸 |
| L-2 | `eval/check_gate_wiring.py` | rc=1，5 项失效：W1 检 `.git/hooks/pre-commit`（clone 里本来就没有钩子）、W2 检 `<MEMORY_ROOT>\.git\hooks`（私有记忆根） | 判据对象是**作者本机与私有源仓**的钩子接入面，在对外子集里必红。接线前提＝让它按面选目标（子集面只该检 `.pre-commit-config.yaml` 能否被 `pre-commit validate-config` 解析），未做；本轮只在 `scripts/ci_workflow_spec_check.py` 上做成了同类改造 |
| L-3 | `mypy`（配置在场，`[tool.mypy]`） | **轮173 第一次量**：`mypy 2.3.1`，`python -m mypy eval scripts audit` ⇒ **72 errors in 37 files（checked 260 source files）**。分布样例：`eval/tune_threshold.py:70` assignment 不兼容、`eval/bge_layer.py:225` 需变量注解 | 无 CI 步骤（本轮**只量未接**——一条第一版就命中 72 行的尺子接进去就是必红闸）。前提＝按文件分批：先把 `eval/command_face_parity.py`、`eval/fenjue_cli.py`、`scripts/mcp_stdio_smoke.py` 三个对外入口改到逐文件零告警，再以 `mypy <具名清单>` 接入（与 L-1 的 scoped 名册同一形状）；全仓面等 72 清零，禁一次性接入 |
| L-4 | PyPI 发布 | `curl https://pypi.org/pypi/fenjue/json` ⇒ 404（本轮实测） | 包已可 `pip install .`（wheel 592KB 实测装通，三个入口在仓外跑绿，见 CI 的 install-face job），但**发布到 PyPI 需账号与 Trusted Publishing 配置**，归归属方裁。未发布前对外一律写「从源码安装」，禁写 `pip install fenjue` |
| L-5 | `docs/` Pages 站点 | **已闭合**：Pages 源经 API 设为 GitHub Actions（`build_type=workflow`），部署 run `36478918872` completed/success，站点实测 **HTTP 200／2,699 B**（2026-09-29 04:2x +08，本机直连） | 复算：`gh api repos/lxh113377/fenjue/pages --jq .html_url` 与 `curl -sI https://lxh113377.github.io/fenjue/`。可达性一律带时刻——同一地址同日 03:5x 实测是 404（那时尚未建站），所以文档里每条在线链接都注了测量时间，禁把 200 当永久事实 |
| L-6 | `.ci/contract.json` | 文件内 `repo` 字段写 `lxh113377/fenjue-private-archive`、`branch: master`（本轮直读原文） | 这是私有面的契约被原样带进公开面。改造前提＝要么按子集重写 checks 与 repo/branch，要么在 `PUBLIC-SUBSET.md` 里显式标注"此文件描述源仓"。本轮未动它（属他人写的口径，需归属方裁） |

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
| L-10 | 散文式主张的双语对账 | 不核。第一版按"代码块行集合"比，两面差 **53 处**且全是译名与排版噪声（mermaid 节点标签、基准表输出行）——一条第一版就命中 50 余行的尺子没资格当闸（R236 补注③），故收窄到命令 token | 要扩到散文 claim，前提＝先给"同一主张"一个显式句柄（如两面同段的锚点标记），而不是再回去猜语义 |
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

