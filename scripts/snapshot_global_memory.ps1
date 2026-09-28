#!/usr/bin/env pwsh
<#
snapshot_global_memory.ps1 — 全局记忆快照 + 季度恢复演练（R193 阶段2）
=====================================================================
快照：robocopy <MEMORY_ROOT> -> D:\fenjue_backup\global_memory-snapshots\gm-YYYYMMDD-HHMMSS（R192 灾备目录延续）
      同时备份 eval/route_trace.jsonl（R192 原行为保留）
      保留最近 $Retention 份（默认 8），旧快照自动清理。
演练：-Drill 把最新快照还原到临时目录，设置 FENJUE_GLOBAL_MEMORY 环境变量
      指向临时目录后跑 verify_truth_consistency.py（C10 为数据层权威），
      通过则把记录追加到 焚诀\reports\DR-drills.md（临时目录演练后删除）。
注册：-RegisterTask 注册每周日 03:00 快照计划任务（当前用户，无需管理员）。

用法:
  pwsh scripts/snapshot_global_memory.ps1                    # 周快照
  pwsh scripts/snapshot_global_memory.ps1 -Drill             # 季度恢复演练
  pwsh scripts/snapshot_global_memory.ps1 -RegisterTask      # 注册计划任务
#>
param(
    [switch]$Drill,
    [switch]$RegisterTask,
    [int]$Retention = 8,
    [switch]$WhatIf   # R208 O-3（P2-13）: 预演模式——只打印将删除的路径，不实际删除
)

$ErrorActionPreference = 'Stop'
$src = '<MEMORY_ROOT>'
$snapRoot = 'D:\fenjue_backup\global_memory-snapshots'
$traceSrc = '<USER_HOME>\Desktop\workspace\焚诀\eval\route_trace.jsonl'
$repoReports = '<USER_HOME>\Desktop\workspace\焚诀\reports'
$verifyPy = '<USER_HOME>\Desktop\workspace\焚诀\eval\verify_truth_consistency.py'
$py = 'C:\Program Files\Python312\python.exe'

if ($RegisterTask) {
    $scriptPath = Join-Path $PSScriptRoot 'snapshot_global_memory.ps1'
    $action = New-ScheduledTaskAction -Execute 'pwsh.exe' -Argument "-NoProfile -File `"$scriptPath`""
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3:00am
    Register-ScheduledTask -TaskName 'Fenjue-GlobalMemory-WeeklySnapshot' -Action $action -Trigger $trigger -Description '焚诀全局记忆周快照（R193）' -Force | Out-Null
    Write-Host "[snapshot] 计划任务已注册: Fenjue-GlobalMemory-WeeklySnapshot (每周日 03:00)"
    return
}

if (-not (Test-Path $src)) {
    Write-Error "[snapshot] 源目录不存在: $src"
}

New-Item -ItemType Directory -Force -Path $snapRoot | Out-Null
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$dest = Join-Path $snapRoot "gm-$ts"

Write-Host "[snapshot] 开始快照 $src -> $dest"
& robocopy $src $dest /E /MT:16 /NFL /NDL /NJH /NJS /R:1 /W:1 | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error "[snapshot] robocopy 失败，退出码 $LASTEXITCODE"
}
$LASTEXITCODE = 0
if (Test-Path -LiteralPath $traceSrc) {
    Copy-Item -LiteralPath $traceSrc -Destination (Join-Path $dest 'route_trace.jsonl')
}

$all = @(Get-ChildItem $snapRoot -Directory | Sort-Object Name -Descending)
if ($all.Count -gt $Retention) {
    $old = $all | Select-Object -Skip $Retention
    foreach ($o in $old) {
        # R208 O-3（P2-13）: 沙盒断言——只允许删除快照根内的目录，越界即拒
        if (-not $o.FullName.StartsWith($snapRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Write-Error "[snapshot] 拒绝删除越界路径: $($o.FullName)（不在 $snapRoot）"
        }
        if ($WhatIf) {
            Write-Host "[snapshot] [WhatIf] 将清理旧快照: $($o.FullName)"
            continue
        }
        Remove-Item -LiteralPath $o.FullName -Recurse -Force
        Write-Host "[snapshot] 清理旧快照: $($o.Name)"
    }
}
Write-Host "[snapshot] 完成: $dest（保留 $Retention 份）"

if ($Drill) {
    # R1 修复（2026-08-16 实测）：按名称字典序取最新会误选 `gm-*-rebuild-pre` 等
    # 中间态快照（'-rebuild' > '-0323' 字典序），改按 LastWriteTime 取最近常规快照。
    $latest = @(Get-ChildItem $snapRoot -Directory | Where-Object { $_.Name -notmatch '-rebuild-pre$' } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if (-not $latest) {
        Write-Error "[drill] 无可用常规快照，先跑一次快照"
    }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("fenjue-drill-" + [IO.Path]::GetRandomFileName())
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    Write-Host "[drill] 还原 $($latest.FullName) -> $tmp"
    & robocopy $latest.FullName $tmp /E /MT:16 /NFL /NDL /NJH /NJS /R:1 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Error "[drill] 还原失败，退出码 $LASTEXITCODE"
    }
    $LASTEXITCODE = 0
    $env:FENJUE_GLOBAL_MEMORY = $tmp
    $env:FENJUE_SKILL_CONTENT = Join-Path $tmp 'skill_content'
    $out = & $py $verifyPy --json 2>&1
    $rc = $LASTEXITCODE
    $pass = $false
    $json = $out -join "`n"
    try {
        $data = $json | ConvertFrom-Json
        $pass = $data.all_pass -and ($data.results | Where-Object { $_.id -eq 'C10' }).status -eq 'PASS'
    } catch {
        $pass = $false
    }
    # R208 O-3（P2-13）: 沙盒断言——临时目录须带 fenjue-drill- 前缀且位于系统 TEMP
    if (-not $tmp.StartsWith([IO.Path]::GetTempPath(), [System.StringComparison]::OrdinalIgnoreCase) -or
        -not $tmp.Contains('fenjue-drill-')) {
        Write-Error "[snapshot] 拒绝删除未知临时目录: $tmp"
    }
    if ($WhatIf) {
        Write-Host "[snapshot] [WhatIf] 演练后本应删除临时目录: $tmp"
    } else {
        Remove-Item -LiteralPath $tmp -Recurse -Force
    }
    $rec = @"
## [$(Get-Date -Format 'yyyy-MM-dd HH:mm')] DR 恢复演练
- 快照: $($latest.Name)
- 还原目标: 临时目录（演练后已删除）
- 校验: verify_truth_consistency.py (FENJUE_GLOBAL_MEMORY=临时目录) 退出码 $rc
- 结果: $(if ($pass) { 'PASS — C10 三方一致，快照可恢复' } else { 'FAIL — 见上方输出' })
"@
    New-Item -ItemType Directory -Force -Path $repoReports | Out-Null
    Add-Content -LiteralPath (Join-Path $repoReports 'DR-drills.md') -Value $rec -Encoding UTF8
    Write-Host "[drill] 演练结果: $(if ($pass) { 'PASS' } else { 'FAIL' })（已记录 reports/DR-drills.md）"
    if (-not $pass) { exit 1 }
}
