#!/usr/bin/env pwsh
<#
wf_qd.ps1 — Qoder CN 端七步闭环工作流薄包装（QD 于 2026-09-24 入役；薄调用 wf_generic.ps1，平台固定 qd）
逻辑唯一源：焚诀/eval/workflow_gate.py；本脚本只固定平台参数并透传其余参数。
状态：DRAFT（truth_constants / 注册表 / junction 落地前不生效）
用法：
  pwsh scripts/wf_qd.ps1 --check boot|task-card|pre-savepoint
  pwsh scripts/wf_qd.ps1 --bootstrap | --status | --next | --task-card
  pwsh scripts/wf_qd.ps1 --record <step> <done|skip> [reason]
#>
& (Join-Path $PSScriptRoot 'wf_generic.ps1') -Platform qd @args
exit $LASTEXITCODE
