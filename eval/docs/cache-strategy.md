# scorecard 子脚本结果缓存策略 (.cache/)

> P1-2 阶段 5 文档 | 2026-08-11
> 状态: 调研完成, 策略落地中

## 1. 现状 (调研结果, 2026-08-11 实测)

**目录位置**: `<repo>/.cache/` (项目根, 不在 eval/ 下)
**已 gitignore**: 是 (`.gitignore` line 55)
**当前实际文件**: 1 个, `triple_diff-c90169ef9337fce6fd458081.json` (1.5KB)

**写者**: 只有 `eval/scorecard.py` 一个脚本, 落键格式 `{tag}-{key}.json`, key = sha256("命令 + 输入文件 mtime/size 指纹 + 相关 env")[:24]

**读者**: 同 `eval/scorecard.py` (写者即读者)

**不归 P1-2 管**:
- `eval/.memory_pread_cache/` — `eval/memory_pread.py` 独立维护, 已在 .gitignore line 13 排除
- `~/.cache/huggingface/...` — HuggingFace 全局用户级 cache, 由 huggingface_hub 库管, 不归 repo
- `eval/.before_sha256.json` / `eval/policy_override_audit.jsonl` 等单文件中间产物 — 已在 .gitignore, 不在 `.cache/` 目录下

## 2. 三类分级 (P1-2 方案 §任务范围 步骤 2)

| 类别 | 描述 | 例子 | 清掉影响 | 恢复命令 |
|---|---|---|---|---|
| **A 类 (硬加速)** | 默认模式清掉自动重跑, 性能降但不报错 | `.cache/triple_diff-*.json` (scorecard 默认模式) | scorecard.py 默认跑变慢 (≈ 30s → 2min), 结果一致 | `python eval/scorecard.py` 重跑即可重新落盘 |
| **B 类 (硬依赖)** | 清掉直接报错, 必须先重生成 | `.cache/triple_diff-*.json` (scorecard --fast 模式) | `python eval/scorecard.py --fast` 报 `rc=-2`, 显式提示 "无缓存" | `python eval/scorecard.py` 全量跑一次, 再 `--fast` |
| **C 类 (中间产物)** | 当前未发现, 留给未来分类 | (无) | n/a | n/a |

**关键事实**: **A 和 B 物理上是同一文件, 区别只在调用方是否带 `--fast` 参数**. P1-2 不拆文件, 只在策略文档说清调用方语义, clear_cache.py 走统一清.

## 3. 何时清 / 谁清 / 怎么清 (P1-2 方案 §任务范围 步骤 3)

| 场景 | 谁负责 | 怎么清 |
|---|---|---|
| 日常开发, 想确认 scorecard 真实结果 (排除缓存污染) | 老大 (手动) | `python eval/scripts/clear_cache.py --tag triple_diff` |
| scorecard 跑出"奇怪结果", 怀疑是旧缓存 | 老大 (手动) | `python eval/scripts/clear_cache.py` (全清, 默认 dry-run, 加 `--yes` 真正删) |
| CI 全量跑 (非 --fast) | 自动化 | 跑前自动清: `rm -rf .cache/*.json` (PowerShell: `Remove-Item .cache\*.json -Force`) |
| CI 跑 --fast 验证 (B 类硬依赖) | 自动化 | **不能清** — 先跑全量, 再跑 --fast; 清了会报 rc=-2 |
| 磁盘紧张, 想瘦身 | 老大 (手动) | `python eval/scripts/clear_cache.py --older-than 7d` (7 天前的清掉) |
| 误删 / 误清后想恢复 | n/a | 无版本控制, 无法恢复 — **清之前先想清楚** |

## 4. clear_cache.py 用法 (P1-2 方案 §任务范围 步骤 4)

详见 `eval/scripts/clear_cache.py` 头部 docstring. 三条核心:

```bash
# 默认: dry-run, 列出会清的 1 个文件, 不真删
python eval/scripts/clear_cache.py

# 真清: dry-run + --yes 才真删
python eval/scripts/clear_cache.py --yes

# 选清: 只清 scorecard 的 triple_diff 类
python eval/scripts/clear_cache.py --tag triple_diff --yes

# 7 天前的清掉 (按 mtime, 老的算过期)
python eval/scripts/clear_cache.py --older-than 7d --yes
```

**安全门**:
1. **默认 dry-run** — 不带 `--yes` 一律只列不删 (老大已确认)
2. **写锁互斥** — 跑前检测 `.cache/scorecard.lock` (借用 .git/fenjue-write-lock 模式), 锁存在则拒绝 (防 scorecard 跑到一半被清)
3. **清后留痕** — 真删的清单写到 `archive/cache-cleanup-YYYY-MM-DD.log`, 可追
4. **不递归子目录** — 只删 `.cache/*.json` 一层, 不动 `eval/.memory_pread_cache/` (那个是 memory_pread 自己管的)

## 5. 验证 (P1-2 方案 §任务范围 步骤 6)

跑前 4 条验收 (本阶段 P1-2 落档时跑一遍, 写进阶段 5 报告):

```
T1 clear_cache.py 默认 dry-run 列出 1 文件, 不删 (1 PASS)
T2 clear_cache.py --yes 真删, archive/cache-cleanup-*.log 有 1 行记录 (1 PASS)
T3 清掉后跑 scorecard.py 默认模式 (非 --fast) → 重生 .cache/, 结果一致 (1 PASS)
T4 清掉后跑 scorecard.py --fast → rc=-2, stderr 显式 "无缓存" (1 PASS, 验证 B 类硬依赖语义)
```

## 6. 关联审计/任务

- AGENTS.md 行为规则 (`.cache/` 已排除, 但缺操作口径) — P1-2 治本
- 阶段 3 报告 §下一步 P1-2 原文
- 阶段 3 报告 §已知限制 #1 隐含 (审计日志 rotate 不动 .cache/)

## 7. 不做什么 (明确划界)

- **不**清 `eval/.memory_pread_cache/` (那个归 memory_pread.py 单独管, P1-2 不跨界)
- **不**清 `~/.cache/huggingface/...` (用户全局, 不归 repo)
- **不**动 `.gitignore` (已经排除, 别再加, 加多了反而看不清)
- **不**做 .cache/ 子目录结构化 (P1-2 是"加规则", 不是"重设计"; 真要重设计留给 P2-X)
- **不**接 Windows Task Scheduler (定时清理 = 自动化, 但定时会清掉 CI 依赖的 cache, 反而误事; 留手动触发)
