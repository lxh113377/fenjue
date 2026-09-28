# skill-hitrate-toolkit — Skill 命中率诊断工具链

> 焚诀项目专用。覆盖触发词质量审计、碎片检测、冲突检测、语义路由评估四大模块。

## 触发场景
- 用户问"skill 命中率怎么样"/"触发词质量有问题吗"
- 新增/修改 skill 后需要验证触发词覆盖
- 定期巡检路由健康度
- 需要对比关键词 vs 语义匹配效果

## 工具清单

| 工具 | 路径 | 功能 | 依赖 |
|------|------|------|------|
| 触发词审计 | `audit/skill_hitrate_audit.py` | 全量 135 skill 触发词质量 PASS/FAIL | Python stdlib |
| 碎片检测 | `audit/fragment_detector.py` | 识别截断碎片/泛化短词 | Python stdlib |
| 冲突检测 | `audit/collision_check.py` | V2(跨域)+V3(域内)触发词冲突 | Python stdlib |
| 碎片修复 | `audit/fix_fragments.py` | 批量替换截断碎片为语义短语 | Python stdlib |
| 冲突修复 | `audit/fix_collisions.py` | 为泛化词添加领域消歧触发词 | Python stdlib |
| 数据层生成器 | `eval/build_indexes.py` | BGE+TF-IDF 双索引（213×512 / 213×5000，双写双校验） | sentence-transformers+sklearn+numpy+scipy |
| 关键词Eval | `eval/skill_hitrate_eval.py` | 纯关键词命中率评估(P/R/F1/Top-N) | Python stdlib |
| 语义Eval | `eval/skill_hitrate_eval_v2.py` | TF-IDF vs 关键词对比评估 | sklearn+numpy+scipy |
| 双树Eval | `eval/eval_dual_tree.py` | Memory上下文增强路由评估 | sklearn+numpy+scipy |
| 阈值调优 | `eval/tune_threshold.py` | TF-IDF相似度阈值扫描 | sklearn+numpy+scipy |
| 路由桥接 | `eval/tfidf_router.py` | TF-IDF路由CLI+API(集成到降级链) | sklearn+numpy+scipy |
| 测试集 | `eval/test_queries.json` | 50条分层测试集(easy/medium/hard/negative) | — |

## 标准工作流

### 工作流1: 触发词质量快速诊断（5分钟）
```bash
cd <USER_HOME>\Desktop\workspace\焚诀
python audit/skill_hitrate_audit.py     # ①触发词PASS/FAIL
python audit/fragment_detector.py       # ②碎片检测
python audit/collision_check.py         # ③冲突检测
```

### 工作流2: 命中率完整评估（10分钟）
```bash
python eval/build_indexes.py --apply    # ①重建 BGE+TF-IDF 双索引（213 条，双写）
python eval/skill_hitrate_eval_v2.py    # ②关键词 vs TF-IDF对比
python eval/eval_dual_tree.py           # ③双树协同评估
```

### 工作流3: 修复+验证闭环
```bash
python audit/fix_fragments.py           # ①修截断碎片
python audit/fix_collisions.py          # ②修跨域冲突
python eval/build_indexes.py --apply    # ③重建索引(触发词/SKILL.md 变了)
python eval/skill_hitrate_eval_v2.py    # ④验证提升
```

## 关键数据

| 指标 | 纯关键词 | TF-IDF | 提升 |
|------|:------:|:------:|:----:|
| Top-1 | 6.7% | 28.9% | +4.3x |
| Top-3 | 22.2% | 51.1% | +2.3x |
| F1 | 12.5% | 44.8% | +3.6x |
| 召回率 | 62.2% | 100% | — |

## 已知限制
- TF-IDF 基于 char n-gram（BGE 同源语料：SKILL.md 前 800 字符），对同义词语义理解有限
- sentence-transformers (all-MiniLM-L6-v2) 预期 Top-1 可到 40-50%，安装依赖 torch 较大
- 测试集覆盖 24 数据域（注册表 domain 口径，R193），但口语化覆盖率仍需扩充
- 纯模拟路由，未接入 LLM 实际调用链路

## 版本
V1.0 | 2026-07-28 | 初始版本（Batch 1-5 全工具链）
