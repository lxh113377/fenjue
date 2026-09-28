# 焚诀 CX 端（Codex CLI）一键安装

> CX 特殊点：记忆走 junction，**技能走物理镜像**（`.agents\skills`，由镜像门禁同步，非 junction）。命令实跑验证过（2026-09-23）。

> 占位符约定：`<memory-root>` / `<skills-root>` = 你的全局记忆/技能权威源目录（自定义位置）；`<焚诀仓>` = 本仓克隆路径；`%USERPROFILE%` / `%LOCALAPPDATA%` 由 cmd 自动展开。

## 前提

- 同 INSTALL-wb.md 前提；另需 Codex CLI 已安装（`.agents` 根存在）。

## 一键步骤

```powershell
# 1. 记忆 junction（两个拼写共存：.Codex 与 .codex）
cmd /c mklink /J "%USERPROFILE%\.Codex\memory_content" "<memory-root>"
cmd /c mklink /J "%USERPROFILE%\.codex\memory_content" "<memory-root>"
# 2. 技能镜像同步（CX 不建 skills junction，用物理副本）
powershell -NoProfile -ExecutionPolicy Bypass -File "<焚诀仓>\skill\sync\check-skill-mirror.ps1" -Fix
# 3. 装依赖 + 验证（同 WB）
python -m pip install -r "<焚诀仓>\requirements-ci.txt"
pwsh -NoProfile -File "<焚诀仓>\scripts\check_junction.ps1"
python "<焚诀仓>\eval\verify_truth_consistency.py"
```

## 验证标准

- 同 WB；另镜像脚本输出 `[GATE:mirror-pass]`（缺标记=协议失效，见 R216d）。

## 排错

| 现象 | 处置 |
|---|---|
| commit 被 MISSING/MISMATCH 拦截 | 命令加 `--fix-mirror` 或重跑 `-Fix` 后重试（禁 `git add -A` 卷走他人改动） |
| `.Codex` 与 `.codex` 只有一个 | 两个都要建（大小写两套，缺一端侧读不到记忆） |
