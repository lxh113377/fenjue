#!/usr/bin/env pwsh
<#
wf_zc.ps1 — ZCode 端七步闭环工作流薄包装（ZC 于 2026-09-22 入役；薄调用 wf_generic.ps1，平台固定 zc）
逻辑唯一源：焚诀/eval/workflow_gate.py；本脚本只固定平台参数并透传其余参数。
用法：
  pwsh scripts/wf_zc.ps1 --check boot|task-card|pre-savepoint
  pwsh scripts/wf_zc.ps1 --bootstrap | --status | --next | --task-card
  pwsh scripts/wf_zc.ps1 --record <step> <done|skip> [reason]
#>
& (Join-Path $PSScriptRoot 'wf_generic.ps1') -Platform zc @args
exit $LASTEXITCODE
