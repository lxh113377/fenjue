#!/usr/bin/env pwsh
<#
wf_generic.ps1 — 七端七步闭环工作流统一薄包装（R208 O-2，P2-14 合并 wf_cc/cx/oc/tr/wb）
逻辑唯一源：焚诀/eval/workflow_gate.py；本脚本只做三件事：固定平台参数 + Python 解析优先级 + 透传退出码。
兼容层：wf_cc.ps1 / wf_cx.ps1 / wf_oc.ps1 / wf_tr.ps1 / wf_wb.ps1 均为薄调用本脚本（平台参数各自固定）。
2026-09-26：千问办公（qw）退役，ValidateSet 与 wf_qw.ps1 同步摘除（端清单权威 = truth_constants.endpoints.active）。
用法：
  pwsh scripts/wf_generic.ps1 -Platform cc --check boot|task-card|pre-savepoint
  pwsh scripts/wf_generic.ps1 -Platform wb --bootstrap | --status | --next | --task-card
  pwsh scripts/wf_generic.ps1 -Platform wb --record <step> <done|skip> [reason]
#>
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('wb', 'tr', 'cx', 'cc', 'oc', 'hm', 'zc', 'qd')]
  [string]$Platform,
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$GatewayArgs
)

$ErrorActionPreference = 'Stop'
$gate = Join-Path $PSScriptRoot '..\eval\workflow_gate.py'

$py = $env:WORKBUDDY_PYTHON
foreach ($name in @('python3', 'python')) {
  if ($py) { break }
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source -and $cmd.Source -notlike '*WindowsApps*') { $py = $cmd.Source }
}
if (-not $py) { $py = '<USER_HOME>\.workbuddy\binaries\python\versions\3.13.12\python.exe' }

& $py $gate @GatewayArgs --platform $Platform
exit $LASTEXITCODE