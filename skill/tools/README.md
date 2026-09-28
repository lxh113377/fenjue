# tools/ — 注册表维护工具

> 此目录存放用于注册表维护的辅助脚本。

## 脚本列表

| 脚本 | 用途 | 执行方式 |
|------|------|----------|
| `_optimize_registry.js` | 批量新增/比对注册表 | `node _optimize_registry.js --force` |

### _optimize_registry.js

自动扫描 <SKILLS_ROOT> 与 unified-skills-index.json 的差异：
- 新增 skill → 自动写入 unified index + cross_platform_map（无审批）
- 删除 skill → 报告差异（需审批）
- 自动更新 oc_only_skills 列表

**参数：**
- `--force`：执行新增操作
- `--report`：仅报告，不修改
