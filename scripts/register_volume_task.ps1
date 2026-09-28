# register_volume_task.ps1 — 注册每日体量治理心跳任务（主心跳，用户 2026-09-26 裁定）
#
# 三条规避都是本机实测踩过的坑，改动前先读注释再动：
#   1) Execute 用 **绝对 System32 powershell.exe** —— 在册的周快照任务当初用 `pwsh.exe`
#      注册，后来 pwsh 不在 PATH 就静默不跑；而 register 脚本与在册任务用的解释器不一致
#      本身就是配置漂移（实测 2026-09-26）。
#   2) `-StartWhenAvailable` —— 没有它，到点时机器关机/睡眠 = 这一次**永久丢失**
#      （周快照实测 08-16 直接跳到 09-26，缺 6 周，而 NumberOfMissedRuns 仍显示 0）。
#   3) 注册后立刻回读 `Get-ScheduledTaskInfo` 并把状态打出来 —— 只看 Register 的
#      退出码不足以证明任务真的在册且可跑。
param(
    [string]$TaskName = 'Fenjue-VolumeGov-Daily',
    [string]$At = '03:40',
    [string]$Script = '<USER_HOME>\Desktop\workspace\焚诀\scripts\volume_gov_daily.ps1',
    [switch]$WhatIf
)
$ErrorActionPreference = 'Stop'
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $ps)) { Write-Output "❌ 找不到 {0}" -f $ps; exit 1 }
if (-not (Test-Path -LiteralPath $Script)) {
    Write-Output "❌ 脚本不存在: {0}" -f $Script
    Write-Output "   拒注册：任务指向不存在的脚本就是 FenjueAutoSync 的死法（rc=0x80070002）"
    exit 1
}
$action = New-ScheduledTaskAction -Execute $ps -Argument (
    '-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $Script)
$trigger = New-ScheduledTaskTrigger -Daily -At $At
# 时长一律用 -Minutes：`New-TimeSpan -FromHours` 只有 PowerShell 7 有，而本脚本
# 故意用 System32 的 5.1 注册（见上方第 1 条），首轮实测就是在这里报错拒注册的
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 60) -Priority 7 `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 10)
$desc = '工作区体量治理每日心跳（A-project-handoff volume --sweep --apply）；' +
        'advisory 不阻断，处置一律走 recycle 禁永久删'
if ($WhatIf) {
    Write-Output ("将注册: {0} 每日 {1}`n  Execute={2}`n  Argument={3}`n  Settings=StartWhenAvailable" -f
        $TaskName, $At, $ps, $action.Arguments)
    exit 0
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description $desc -Force | Out-Null
$t = Get-ScheduledTask -TaskName $TaskName
$i = $t | Get-ScheduledTaskInfo
Write-Output ("✅ 已注册 {0}｜State={1}｜NextRun={2}｜StartWhenAvailable={3}" -f
    $TaskName, $t.State, $i.NextRunTime, $t.Settings.StartWhenAvailable)
Write-Output ("   判据侧对账：handoff.py volume --sweep 的 L5 行应显示该任务 rc=0/Ready，" +
              "且「无人值守心跳」项从 warn 转 ok（首次跑完之后）")
