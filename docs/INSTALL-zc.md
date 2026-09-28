# 焚诀 ZC 端（ZCode）一键安装

> ZC 2026-09-22 入役：一级 junction 直连权威源（此前绕经 TR 的二级链已拆）。记忆经 `~/.zcode/AGENTS.md` 引导直读（程序无内置 memory 目录约定）。命令实跑验证过（2026-09-23）。

> 占位符约定：`<memory-root>` / `<skills-root>` = 你的全局记忆/技能权威源目录（自定义位置）；`<焚诀仓>` = 本仓克隆路径；`%USERPROFILE%` / `%LOCALAPPDATA%` 由 cmd 自动展开。

## 前提

- 同 INSTALL-wb.md 前提；ZCode 主包已安装（`%USERPROFILE%\.zcode` 存在）。

## 一键步骤

```powershell
# 1. 两个一级 junction（注意：没有 memory_content，ZC 程序不认该目录名）
cmd /c mklink /J "%USERPROFILE%\.zcode\skills" "<skills-root>"
cmd /c mklink /J "%USERPROFILE%\.zcode\memory" "<memory-root>"
# 2. 装依赖 + 验证（同 WB）
python -m pip install -r "<焚诀仓>\requirements-ci.txt"
pwsh -NoProfile -File "<焚诀仓>\scripts\check_junction.ps1"
python "<焚诀仓>\eval\verify_truth_consistency.py"
```

## 验证标准

- 同 WB。

## 排错

| 现象 | 处置 |
|---|---|
| 旧二级 junction 残留（指向 `.trae-cn` 下） | 按 `%USERPROFILE%\.zcode\_bak_zcode_skills_junctions_*.txt` 清单拆除后重建一级 |
| 记忆不生效 | 检查 `%USERPROFILE%\.zcode\AGENTS.md` 是否存在（引导直读的注入点，无它则记忆静默缺失） |
