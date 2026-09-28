# 焚诀 WB 端（WorkBuddy）一键安装

> 目标：在新机上重建 WB 端全部挂载 + 验证。命令均在 PowerShell 实跑验证过（2026-09-23）。

> 占位符约定：`<memory-root>` / `<skills-root>` = 你的全局记忆/技能权威源目录（自定义位置）；`<焚诀仓>` = 本仓克隆路径；`%USERPROFILE%` / `%LOCALAPPDATA%` 由 cmd 自动展开。

## 前提

- Windows + PowerShell 5.1+，`<memory-root>` 与 `<skills-root>` 权威源已就位（含 `<memory-root>\memory` 子目录）。
- 焚诀仓已克隆（下文 `<焚诀仓>` 指其路径，如 `%USERPROFILE%\Desktop\workspace\焚诀`）。
- Python 3.12+ 可用。

## 一键步骤

```powershell
# 1. 建三个 junction（失效先 rmdir 再重建，不要直接覆盖）
cmd /c mklink /J "%USERPROFILE%\.workbuddy\memory" "<memory-root>\memory"
cmd /c mklink /J "%USERPROFILE%\.workbuddy\memory_content" "<memory-root>"
cmd /c mklink /J "%USERPROFILE%\.workbuddy\skills" "<skills-root>"
# 2. 装依赖
python -m pip install -r "<焚诀仓>\requirements-ci.txt"
# 3. 验证
pwsh -NoProfile -File "<焚诀仓>\scripts\check_junction.ps1"
python "<焚诀仓>\eval\verify_truth_consistency.py"
```

## 验证标准

- `check_junction.ps1`：异常 **0** 个（总数随本机安装端数浮动，只看异常数）。
- `verify_truth_consistency.py`：`N PASS / 0 FAIL / 0 SKIP`。

## 排错

| 现象 | 处置 |
|---|---|
| junction 显示 MISMATCH（普通目录） | `cmd /c rmdir /q "<挂载点>"` 后重建（`check_junction` 输出自带修复行） |
| junction BROKEN | 目标盘未挂载，先恢复 `D:` 再重跑 |
| verify 报 C1/C2 不一致 | 跑 `python eval/build_registry.py --dry-run` 看差集，不要手改注册表 |
