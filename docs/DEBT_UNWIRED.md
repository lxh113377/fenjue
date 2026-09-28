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
