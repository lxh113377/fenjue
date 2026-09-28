# AGENTS.md — Fenjue

本仓库是「多 Agent 统一记忆与技能路由系统」的公开治理工作区，用于展示架构、协作开发与持续迭代。

> 个人记忆库通过 gitignore 的 junction 隔离，永不入库。任何 agent 会话在本仓库工作时，提交前必须通过 `scripts/public_clean_check.py` 门禁。

## 项目结构

| 目录 | 用途 |
|------|------|
| `eval/` | 四层路由管线（直连 + Tag + BGE + Memory）评估工具集 |
| `audit/` | skill 触发词 / 命中率 / 语义重叠审计脚本 |
| `skill/` | 跨平台技能注册 + 同步管理 |
| `examples/` | 合成技能与分层查询集（评估链零真实语料可跑） |
| `scripts/` | 公开仓库安全门禁与辅助脚本 |
| `docs/` | 演示页与文档 |

## 六条主线

1. 跨平台 skill 互通（junction + registry + sync）
2. 统一记忆 + 技能路由（memory-root + routing + intent classifier）
3. skill 命中率优化（四层路由 + 盲测回归）
4. lessons 复用度量（指纹 + 机械判定）
5. 注意力优化（token 边际税实测）
6. 前置使用率采样度量（skill 前置使用率采样 + 统计）

## 给贡献者的规则

- 提交前：`python scripts/public_clean_check.py` 必须 CLEAN。
- 个人记忆 / 本机路径 / 密钥：一律禁止提交。
- 测试：核心脚本用示例数据可运行；大改动补测试或附验证输出。
- 文档：中文为主，README 双语同步。
