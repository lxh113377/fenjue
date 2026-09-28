#!/usr/bin/env pwsh
<#
wf_oc.ps1 — OpenCode 端七步闭环工作流薄包装（代号 oc 由 OpenClaw 2026-09-21 退役后腾位，2026-09-23 起服务 OpenCode；R195；R208 O-2 起薄调用 wf_generic.ps1，平台固定 oc）
逻辑唯一源：焚诀/eval/workflow_gate.py；本脚本只固定平台参数并透传其余参数。
用法：
  pwsh scripts/wf_oc.ps1 --check boot|task-card|pre-savepoint
  pwsh scripts/wf_oc.ps1 --bootstrap | --status | --next | --task-card
  pwsh scripts/wf_oc.ps1 --record <step> <done|skip> [reason]
#>
& (Join-Path $PSScriptRoot 'wf_generic.ps1') -Platform oc @args
exit $LASTEXITCODE
