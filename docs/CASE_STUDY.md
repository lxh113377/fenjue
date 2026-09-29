# 实际使用案例（可复算，不写观感）

> 赛道官方描述一手整句：**「尤其关注工具易用性、文档完善程度与实际使用案例」**。
> 本文就是第三格的载体：四组案例，每组都给「当时遇到什么 → 哪条判据抓到的 → 你现在能一条命令复算什么」。
> 所有时刻读数截至 2026-09-29；跨日引用前请按文末命令重跑。

## 案例 1 · 一台机器上 7 个编码助手共用一套记忆与技能库

**场景**：同一份"踩过的坑"要在 WorkBuddy / TRAE / Codex CLI / Hermes / ZCode / OpenCode / Qoder 七端各记一遍，
几周内必然长歪（同一事实不同端不同版本）。

**这套结构怎么解**：单一权威记忆根 + 端侧 junction/镜像 + 一份机器可读的真相源。
`eval/truth_constants.json` 是在役端的**唯一**权威名册，文档里出现的任何端数都要和它对账。

**复算**：

```bash
python -c "import json;d=json.load(open('eval/truth_constants.json',encoding='utf-8'));a=d['endpoints']['active'];print(len(a),a)"
python eval/doc_claim_face.py          # 扫全部对外文档里的端数声明，与上面现算值比对
```

**这套判据抓到的真缺陷（不是构造的）**：接线当轮（2026-09-29 02:1x）就抓到两处——
英文 README 写 `6 agents`、`docs/INSTALL.md` 写 `shared by 8 agent frontends`，而权威值 7。
（这两处历史错值按本仓铁律**保留原文不改写**，所以它们以行内代码的形式留在本文里——
判据在匹配前会先剥掉 `...` 片段：逐字引用不是本仓在主张。裸声明才会被抓，
`python eval/doc_claim_face.py --selftest` 的两条腿分别证这两件事。）
中文 README 早已把「六端」当历史错误改掉，还写着"写死数字会被抓"，但**没有一条判据看英文面**。
现值实测：`doc-claims PASS: 扫 12 份文档 / 1 处端数声明，与真相源 7 全一致`。

## 案例 2 · 命中率盲测：把"记住了"和"用上了"分开

**场景**：技能库长到上百个以后，最常见的失效不是报错，而是**明明有合适的技能却没被路由到**，
而使用者的主观感受在这里完全不可信。

**做法**：查询集按难度分层（easy 明确关键词 / medium 口语化 / hard 一句里含多个候选），分别出数。

```bash
python eval/hitrate_cli.py --skills-dir examples/skills --queries examples/queries.json --top 3 --show-cases
```

**读数**（2026-09-29，Python 3.12 / pin 依赖面）：easy 5/5、medium 3/4、hard 2/5，合计 Top-1 10/14。
决策就是这么来的：**hard 层 40% 是真实短板**，所以改进方向定为"同义扩展 + 查询改写"，
而不是把三层合并成一个 71.4% 上报——合并就是把度量做成宣传。

**规模那一侧**（同一条技能链路涨到 1000 个技能会怎样）：

```bash
python eval/bench_router.py --sizes 12,100,500,1000
```

实测 1000 档：建索引 0.0446 s、单查询 p95 0.107 ms、峰值分配 6.5 MB，抽查列全 `ok`。
这个基准第一次跑出来的时候，最小档读到 6.2 s——那是进程首趟的 sklearn 惰性初始化，
不是 12 个技能贵。加预热之前它会把一个由**取数顺序**决定的数字写进对外文档。

## 案例 3 · 门禁真的会红：三条被自己抓出来的缺陷

本仓的立场是「一把从来没红过的尺子和一把坏尺子无法区分」，所以这里给的是**已发生的红**，
每条都留了能复算的载体。

| 抓到什么 | 判据 | 当时的真实后果 | 复算 |
|---|---|---|---|
| CI 测试步一根判据都没跑到 | `--timeout=120` 需要 pytest-timeout，而 CI 只装了 pytest | pytest rc=4（`unrecognized arguments`），README 挂着 CI 徽章而 main 是红的 | `gh run view 36466792735 --log-failed`；修复后见 `gh run list --workflow ci` |
| 文档指向不存在的对象 | `eval/check_doc_links.py` | `README.en.md` 的 `docs/showcase.png` 从未存在；同一文件还有 3 条 404 的 Pages 链接与 5 条 `blob/master` URL | `python eval/check_doc_links.py` |
| 判据自己的分母来自另一个面 | `scripts/ci_workflow_spec_check.py` 与 `check_doc_links.py` 双双硬编私有源仓名册 | 一接 CI 就必红，红因与它想防的事无关 ⇒ 长期无人接（"在场未接线"） | `python scripts/ci_workflow_spec_check.py`（名册改为读 `.ci/workflow_jobs.json` 后 rc=0） |

外加一条本端自打的：MCP 握手判据原写成 `printf frames | fenjue-mcp`，Linux 上写完即 EOF、服务端没答完就退出 ⇒ 判红；
同一条命令在 Windows 拿得到完整回包。**一段在两个面行为不同的 shell 不能当尺子**，
改用 `scripts/mcp_stdio_smoke.py`（Popen + 读线程 + 显式等待），并给它两条反例腿：
起不来 rc=2、起得来但不应答 rc=1。

## 案例 4 · 一条命令问「我这台机器上哪条链是通的」

```bash
python eval/fenjue_cli.py doctor          # 或装好后： fenjue doctor
python eval/fenjue_cli.py doctor --json   # 机器可读（stdout 是单一 JSON 文档，结论行走 stderr）
```

`doctor` 串跑 8 项随包自检：脱敏闸双向自证、文档链接、端数对账、workflow 名册、两条命中率面、
基准 smoke、MCP 真握手。逐条给 rc，实测输出：

```
fenjue doctor · 版本=1.2.0 · 取数面=<仓根>
  [ok ] public-clean-selftest  rc=0  [GATE:clean-selftest-pass] 正向 0 命中/1 文件；反例命中 1 处
  [ok ] doc-links              rc=0  doc-links PASS: 扫 6 份根文档，相对链接均存在
  [ok ] doc-claims             rc=0  doc-claims PASS: 扫 11 份文档 / 1 处端数声明，与真相源 7 全一致
  [ok ] workflow-roster        rc=0  workflow-spec check: PASS
  [ok ] hitrate-face           rc=0  合计 14 10 71.4% 85.7%
  [ok ] skills-md-face         rc=0  合计  4  4 100.0% 100.0%
  [ok ] bench-smoke            rc=0  12 4 0.0019 0.0018 0.0078 0.166 ok
  [ok ] mcp-handshake          rc=0  [GATE:mcp-smoke-pass] 工具 3 个、握手往返齐全
合计：跑 8 项，红 0 项，跳过 0 项（跳过带原因，不计入通过）
```

三条边界写死在行为里：**载体不在场 ⇒ 记"跳过 + 原因"**（不算通过）；**一项都没跑 ⇒ rc=2 并打印原因**
（零检查不等于全绿）；**任一条红 ⇒ rc=1 且点名**（不折成"有检查失败"）。

## 让 agent 自己接上（易用性那一格）

```bash
fenjue mcp-config --client claude     # JSON；--client codex 出 TOML；--client generic/qoder 出 JSON
```

输出即粘进客户端配置，并在 stderr 注明这条命令是按「装好的 `fenjue-mcp`」还是「源码树
`python -m eval.mcp_server`」生成的——两种形态的命令不同，不给来源的配置就是让人照着跑不通的配置。

## 全部复算命令

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python eval/fenjue_cli.py doctor
python eval/hitrate_cli.py --skills-dir examples/skills --queries examples/queries.json --top 3 --show-cases
python eval/bench_router.py --sizes 12,100,500,1000
python -m pytest            # 本机面 652 passed / 48 skipped；Linux CI 面 642 / 58（平台专属跳过 10 条）
```
