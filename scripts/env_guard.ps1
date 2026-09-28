#!/usr/bin/env pwsh
<#
env_guard.ps1 — 环境隔离检查薄包装（R196）
逻辑唯一源：焚诀/eval/env_guard.py；本脚本只做 Python 解析优先级 + 透传退出码。
用法：
  pwsh scripts/env_guard.ps1 [--project <path>] [--json]
#>
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$GatewayArgs
)

$ErrorActionPreference = 'Stop'
$guard = Join-Path $PSScriptRoot '..\eval\env_guard.py'

$py = $env:WORKBUDDY_PYTHON
foreach ($name in @('python3', 'python')) {
  if ($py) { break }
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source -and $cmd.Source -notlike '*WindowsApps*') { $py = $cmd.Source }
}
if (-not $py) { $py = '<USER_HOME>\.workbuddy\binaries\python\versions\3.13.12\python.exe' }

& $py $guard @GatewayArgs
exit $LASTEXITCODE
