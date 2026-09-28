# 贡献指南

欢迎 issue 与 PR。本项目是公开仓库，任何提交都会对外可见，请严格遵守：

1. **提交前跑安全门禁**：`python scripts/check_public_clean.py`，发现密钥 / 个人身份 / 本机路径必须清除后才能提交。
2. **技能改动双门禁（P2E-1/2，对外发布必过）**：内容安全扫描（提示注入 / 危险命令 / 密钥外传，注入与外传族零容忍）+ 发布合规校验（frontmatter 必填、description ≤1024 字符、顶层字段白名单）。两门由主仓 CI 门禁 **C27/C28** 常态兜底（`verify_truth_consistency.py` 自动执行，PR 无需本地手跑）；技能随包对外分发前，C27 的 dangerous 族告警清单须逐条人工过目。
2. **不要提交个人数据**：个人记忆库（junction）、本机路径、私人项目名、姓名学号一律不进仓库。
3. **保持工具可用**：`eval/` 与 `audit/` 的脚本必须能配合示例数据运行，改动需带测试或验证记录。
4. **中文注释优先**：本项目默认中文文档与注释。
5. **本地启用 pre-commit 钩子**：`git config core.hooksPath .githooks`。

## 常用命令

```bash
python scripts/check_public_clean.py   # 安全门禁
python -m compileall -q eval audit scripts   # 语法检查
```
