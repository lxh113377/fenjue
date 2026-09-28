# 焚诀 HM 端（Hermes Agent）一键安装

> HM 特殊点：**逐技能 junction**（`skills\global-skills\*` 每技能一条），非整根挂载；记忆走整根。命令实跑验证过（2026-09-23）。

> 占位符约定：`<memory-root>` / `<skills-root>` = 你的全局记忆/技能权威源目录（自定义位置）；`<焚诀仓>` = 本仓克隆路径；`%USERPROFILE%` / `%LOCALAPPDATA%` 由 cmd 自动展开。

## 前提

- 同 INSTALL-wb.md 前提；`$env:HERMES_HOME` 指向 HM 数据根（默认 `%LOCALAPPDATA%\hermes`）。

## 一键步骤

```powershell
# 1. 记忆整根 junction
cmd /c mklink /J "$env:HERMES_HOME\memories" "<memory-root>"
# 2. 逐技能 junction（已存在则跳过；退役残留会被探活报 BROKEN）
Get-ChildItem "<skills-root>" -Directory | ForEach-Object {
  $dst = Join-Path "$env:HERMES_HOME\skills\global-skills" $_.Name
  if (-not (Test-Path -LiteralPath $dst)) { cmd /c mklink /J $dst $_.FullName }
}
# 3. 装依赖 + 验证（同 WB；探活会逐条扫描 HM 技能链路并打印 [INFO] 扫描数）
python -m pip install -r "<焚诀仓>\requirements-ci.txt"
pwsh -NoProfile -File "<焚诀仓>\scripts\check_junction.ps1"
python "<焚诀仓>\eval\verify_truth_consistency.py"
```

## 验证标准

- 同 WB；HM 根不存在时探活打印 `[WARN] …不可信`（属环境事实，不计异常，但不得静默 PASS）。

## 排错

| 现象 | 处置 |
|---|---|
| 某技能 MISMATCH（实体目录） | 该端布置形态错，删实体后按步骤2重建单条 junction |
| BROKEN（目标不可达） | 退役残留，清掉该条即可 |
