# eval — 路由与评估工具集

## 路由

`unified_router.py` 为主入口，`route()` 的分层链路（层名以源码注释为准，本处只列顺序）：

```
L0.1 直连（direct_map 正则）→ 归一化（同义扩展）→ L0 域分类 → L0.5 Tag 倒排
  → L1 BGE 召回（bge-small-zh-v1.5 / ONNX）→ L1.5 域并集补召 → L1.7 TF-IDF 集成重排
  → L1.9 NOT-USE 负标签终判 → L2 memory_boost → L2.5 置信分层 → L3 LLM 消歧 prompt 生成
```

- `bge_layer.py` 为唯一嵌入召回层（含 TF-IDF 确定性检索兜底）；ONNX 是默认后端，
  torch 仅在 `FENJUE_BGE_BACKEND=torch` 时启用（本机 torch/Rust tokenizers 段错误，
  故有纯 Python BERT-WordPiece 复现代 `bge_onnx_engine.py`）。
- `direct_map.json`（唯一真身）与 `direct_map_fallback_data.py`（离线兜底副本）双写，
  由 verify **C24** 强制一致；改一处必须 `save_direct_map.py --force` 同步。
- LLM 消歧是**出进程回合式**：router 只产出 prompt 包（`--json` 的 `llm_prompt`），
  由 agent 选定后回灌 `--llm-choice`，落 `llm_decisions.jsonl` 痕迹。router 自身不联网。
- `tfidf_router.py` 为 **LEGACY**（R207 P1-5 裁定：运行时无引用，仅发布 toolkit 兼容保留，
  新代码禁止 import）。

## 评估

| 命令 | 用途 |
|---|---|
| `python eval/unified_router.py --eval` | test_queries 回归（`--eval` 关 trace，防测试查询污染生产分母，R168） |
| `python eval/frozen_blind_eval.py` | 冻结盲测集（产物 `ci-blind-eval.json`） |
| `python eval/rotate_blindset.py` | 盲测集季度轮换台账（`blindset_rotation.json`） |
| `python eval/memory_recall_eval.py` | 记忆召回评测（gold 用例 + Hit@k / MRR，P1E-1） |
| `python eval/lessons_hitrate.py` | lessons 行为指纹命中率（主线④） |
| `python eval/skill_usage_stats.py` | 技能使用率采样（主线⑥） |
| `python eval/lessons_pread_audit.py` | 开场预读审计（`--days/--json`） |

评分：`scorecard.py`（track_150 遗留三线 50 分制）/ `score_track200.py`（六线全评），
当前生效口径由 `truth_constants.json` 的 `scorecard.active_track` 决定；渲染层一律读
`SCORECARD_ACTIVE_*`（2026-09-24 对标轮收口：此前 `generate_index`/`aggregate_status`
恒取 track_150，导致「182.5/200」配「120/150 达标线」的分母错配）。

## 真相源与生成器

- `truth_constants.json`（唯一常量源）+ `truth_constants.py`（薄 loader，含 `derive_max_gate_id()`
  等唯一派生点）。
- `verify_truth_consistency.py` — 真相源门禁（编号 `C1~C<N>`，N 以 `main()` 内 checks 注册表为准）。
- `build_indexes.py --apply` — 派生数据层**唯一生成器**（BGE npy / TF-IDF npz+pkl / skill_ids /
  域 JSON / disk_manifest；默认 dry-run，写后守恒校验）。
- `build_registry.py` → 注册表；`generate_index.py` → 根 `index.md`；`aggregate_status.py` → `STATUS*.md`。
- 旧生成器 `build_bge_index.py` / `build_skill_embeddings.py` 及包装器 `save_bge_fullbody.py` /
  `build_skill_vectors.py` 已删除（2026-09-23 观察期满）。

## 安全与门禁配套

- `index_integrity.py` — pickle 白名单反序列化 + SHA + vectorizer 结构校验（CWE-502 面）。
- `io_utils.py` — 读写原语唯一实现，含 `checked_path()` 路径穿越防护（CWE-22 面）。
- `skill_security_scan.py` / `skill_publish_compliance.py` — 内容安全（C27）与发布合规（C28）。
- `scan_secrets.py` / `pre_commit_hooks.py` / `gate_stub_runner.py` — 密钥扫描 / 全量闸 / 判据隔离桩复跑。
- `stubs/registry.json` — 判据隔离桩登记（新增判据必须补桩，否则 runner FAIL，R272）。

## 配置

`config.py` — `FENJUE_*` 环境变量覆盖 + 路径单源 re-export（默认兼容现有布局）。

测试：`python -m pytest`（`testpaths = eval/tests`，全部离线；`FENJUE_BGE_DISABLE=1` 可强制纯 TF-IDF）。
