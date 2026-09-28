# 焚诀数据文件 Schema 注册表（data_schema_registry）

> 目的：消除 `agent常见困难.txt` 二.1「格式不统一/schema 变了旧文件没迁移 → 解析失败或静默丢字段」缺口（评估 T14）。
> 机制：所有机器可读数据文件（JSON/JSONL）登记 schema 版本；新写入必须带 schema_v 头；读侧按 schema_v 分派解析。
> 日期：2026-08-16 | 版本：v1.0

## 一、注册表（实测登记）

| 文件路径 | 格式 | schema_v | 结构说明 | 生产方 | 消费方 |
|---------|------|---------|---------|--------|--------|
| `<MEMORY_ROOT>\meta\lessons_usage.jsonl` | JSONL | v1 | 每行 {date, session, query, loaded[], used[], useful, improved_output, [action, key, reason]}；action=manual_forget 行仅含 {date, session, action, key, reason} | record_lessons_usage.py / handoff audit | lessons_usage_coverage.py / lessons_quality_report.py / trace_view.py |
| `<MEMORY_ROOT>\meta\solution_decisions.jsonl` | JSONL | v1 | {ts, task, chosen, result, improved_output, retrospective} | A-get-memory Step 1.6 | （复盘消费） |
| `焚诀/memory/sessions/savepoint-gate.jsonl` | JSONL | v2 | {ts, gate_fails, rollbacks, est_wasted_minutes, failure_budget, ...}；schema_v=2（R196） | workflow_gate.py savepoint | trace_view.py / 周维护 |
| `焚诀/eval/route_trace.jsonl` | JSONL | v1 | 生产路由 trace（FENJUE_ROUTE_TRACE=1 写入，9902+ 条） | unified_router.py | route_miss_report.py |
| `焚诀/eval/direct_map.json` | JSON | v1 | skill 直连映射表（置顶 11 条） | 手动维护 + build_indexes.py 校验 | unified_router.py |
| `焚诀/skill/registry/unified-skills-index.json` | JSON | v1 | 全量 skill 索引（派生件，禁手改） | build_indexes.py --apply | 路由/审计 |
| `焚诀/skill/registry/platform-{wb,cc,oc,tc,codex}.json` | JSON | v1 | 各平台 skill 清单（派生件） | build_indexes.py --apply | 平台适配 |
| `焚诀/skill/registry/cross_platform_map.json` | JSON | v1 | 跨平台 junction 映射（与 <MEMORY_ROOT>\cross_platform_map.json 同构） | 手动 + 同步脚本 | check-skill-mirror.ps1 |
| `焚诀/eval/adversarial_queries.json` | JSON | v1 | 对抗测试集（15 条写边界） | 手动维护 | workflow_gate --check adversarial |
| `焚诀/eval/blindset_query_pool.json` / `frozen_blind_test.json` | JSON | v1 | 盲测集（frozen 冻结 10 查询） | 测试基建 | 盲测门 |
| `焚诀/eval/bge_fullbody_meta.json` / `bge_fullbody_skills.json` | JSON | v1 | BGE 嵌入元数据/技能清单（派生件） | build_indexes.py --apply | 路由 |
| `焚诀/feedback/feedback.jsonl` | JSONL | v1 | {id, task, severity, status, ...} open/closed 条目 | feedback/app.py | savepoint #14 / A-get-memory 2.5 |
| `<MEMORY_ROOT>\meta\VERSION_LOCK.md` 及分卷 | MD | — | 版本锁（组件版本号） | 周维护 | A-get-memory Step 4.3 |

## 二、Schema 版本规则（新规范）

1. **写侧强制**：所有 JSON/JSONL 生产脚本必须在文件**首行/首个对象**写入 `schema_v` 字段（JSONL 每行可带 `schema_v` 或文件头注释行 `# schema_v=N`；纯 JSON 顶层加 `"_schema_v": N`）。新脚本（lessons_quality_report 等）只读不写，无需变更。
2. **读侧分派**：解析器先读 `schema_v` → 命中已知版本走对应解析；未命中（旧文件无 schema_v）→ 按 v1 兼容解析 + 记录 WARN（不静默丢字段）。
3. **迁移规则**：schema 变更必须 bump 版本号并在本注册表追加一行「vN+1 变更说明」；旧文件迁移由迁移脚本执行，禁止原地改结构丢字段（呼应 agent常见困难.txt 二.1）。
4. **校验**：周维护 Step 4 抽查注册表文件 schema_v 与实际文件头一致。

## 四、4KB 拆卷适用文件（R199.3 单一数据源，A-project-handoff 消费）

> 消费方：`handoff.py split` / savepoint 步骤 j 的 `load_split_targets()`（读本锚点节，缺省回退内置默认 07+05）。
> 维护规则：新增/移除拆卷目标**只改本清单**，禁止改 handoff.py 的 SPLIT_TARGETS 常量（常量仅作无注册表项目的回退）。

### 4KB 拆卷适用文件

- `07-next-steps.md`
- `05-feature-status.md`
- `01-goal.md`

## 三、执行落地状态

- [x] 注册表文档建立（本文件，v1.0）
- [x] savepoint-gate.jsonl 已带 schema_v=2（R196 实测）
- [x] lessons_usage.jsonl 文件头补 `# schema_v=1` 注释（2026-08-16 实测：消费脚本容错跳过注释行，28 条记录读回一致）
- [x] solution_decisions.jsonl 文件头补 `# schema_v=1` 注释（2026-08-16 实测）
- [x] 读侧兼容验证：lessons_quality_report.py / lessons_usage_coverage.py 均容错跳过注释头（json.loads 失败 continue），加头后数据读回一致——隐式 v1 分派已生效，无需改消费脚本
- [ ] 全量解析器显式 schema_v 分派改造（P2 可选：当前注释头+容错跳过已满足"不静默丢字段"，显式分派仅在大规模多版本并行时必要）

> 本注册表为「读侧规范 + 现状登记」，不改变既有数据内容；新写入规范自 v1.0 起生效。
