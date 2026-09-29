# 在场但未接线的判据与已知债（逐条带实测 rc）

> 立这份清单的原因：对标轮发现本仓有**判据在场却不敢接 CI**的情况（一接就红，红因还是
> 「判据量了另一个面」）。"没接"本身不是问题，**没人知道没接**才是问题。
> 本文件每条都给：命令、本轮实测 rc、红因、接线前提。前提未满足前禁止为了让 CI 绿而改语料凑数。

| id | 对象 | 本轮实测 | 状态与接线前提 |
|---|---|---|---|
| L-1 | `ruff check .`（全仓） | rc=1，**88 处**（69 处可自动修） | 未接全仓面。已接的是 scoped 名册（本端新增文件 + 三个对外入口，rc=0，写在 ci.yml 与 ci-pr.yml）。前提＝清完余量后把 scoped 名册换成全仓；直接接全仓等于造一把必红的闸 |
| L-2 | `eval/check_gate_wiring.py` | rc=1，5 项失效：W1 检 `.git/hooks/pre-commit`（clone 里本来就没有钩子）、W2 检 `<MEMORY_ROOT>\.git\hooks`（私有记忆根） | 判据对象是**作者本机与私有源仓**的钩子接入面，在对外子集里必红。接线前提＝让它按面选目标（子集面只该检 `.pre-commit-config.yaml` 能否被 `pre-commit validate-config` 解析），未做；本轮只在 `scripts/ci_workflow_spec_check.py` 上做成了同类改造 |
| L-3 | `mypy`（配置在场，`[tool.mypy]`） | 未在本轮跑 | 无 CI 步骤。前提＝先量公开面告警数并按模块分批收紧，禁一次性接入 |
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

## 〔2026-09-29 对标第 79 轮追加〕L-1 的重跑值，与「文档计数族」这条新盲区

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

