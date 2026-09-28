#!/usr/bin/env pwsh
<#
start_feedback.ps1 — 启动焚诀用户反馈通道（Flask 127.0.0.1:8787）

用法:
  powershell -ExecutionPolicy Bypass -File scripts/start_feedback.ps1       # 后台隐藏启动 + 端口校验
  powershell -ExecutionPolicy Bypass -File scripts/start_feedback.ps1 -Foreground  # 前台运行（调试）
#>
param(
  [switch]$Foreground
)

$ErrorActionPreference = 'Stop'
$py = 'C:\Program Files\Python312\python.exe'
$app = Join-Path $PSScriptRoot '..\feedback\app.py'
$appArgs = @($app, '--no-browser')

if ($Foreground) {
  & $py @appArgs
  exit $LASTEXITCODE
}

Start-Process -FilePath $py -ArgumentList $appArgs -WindowStyle Hidden
Start-Sleep -Seconds 2
$conn = Get-NetTCPConnection -LocalPort 8787 -ErrorAction SilentlyContinue
if (-not $conn) {
  Write-Error '[feedback] 启动失败：8787 端口无监听'
}
Write-Host '[feedback] http://127.0.0.1:8787/ 已启动（后台隐藏运行）'
