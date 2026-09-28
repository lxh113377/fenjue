# volume_gov_daily.ps1 — 工作区体量治理「无人值守心跳」（A-project-handoff volume 治理链）
#
# 为什么需要它：用户 2026-09-26 裁定主心跳 = 每日计划任务。而本机三件定时器已实测证明
# 会静默坏掉（CIGreenPanel-Daily 从未运行 / AutoSync 停用且目标文件不存在 / 周快照缺 6 周），
# 所以本脚本必须同时写一份**心跳落痕**，让 volumegov 的 L5 判据能反证"这条链真的跑过"，
# 而不是又多一个坏了没人知道的定时器（判据侧见 handoff_lib/volumegov.py scan_chain）。
#
# 手动跑：powershell -NoProfile -ExecutionPolicy Bypass -File "...\volume_gov_daily.ps1"
# 注册：   powershell -NoProfile -ExecutionPolicy Bypass -File "...\register_volume_task.ps1"
# advisory：本脚本任何失败都只落痕，绝不非零退出中断（看守不得成闸门，用户 2026-09-25 裁定）。
param(
    [string]$Python  = 'C:\Program Files\Python312\python.exe',
    [string]$Handoff = '<SKILLS_ROOT>\A-project-handoff\scripts\handoff.py',
    [string]$GmRoot  = '<MEMORY_ROOT>',
    [string]$LogRoot = 'D:\fenjue_backup\volume-daily',
    [int]$LogKeep    = 14,
    [int]$HbKeep     = 200
)
$ErrorActionPreference = 'Continue'
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$hbPath = Join-Path $GmRoot 'meta\volume-heartbeat.log'
$runLog = Join-Path $LogRoot ('volume-daily-{0}.log' -f (Get-Date -Format 'yyyy-MM-dd'))
$out = @()
$rc = -1
$note = ''

if (-not (Test-Path -LiteralPath $LogRoot)) {
    New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $Python)) {
    $note = 'python 缺失: {0}' -f $Python
} elseif (-not (Test-Path -LiteralPath $Handoff)) {
    $note = 'handoff.py 缺失（全局技能 junction 未挂载？）: {0}' -f $Handoff
} else {
    # sweep --apply：逐面按 auto_layers 白名单处置（默认 L3 可再生缓存 + L4 过期备份，
    # 一律走 recycle 禁永久删；字节/件数帽与处置锁在 volumegov 内部）
    $out = & $Python $Handoff volume --sweep --apply --snapshot 2>&1 | ForEach-Object { [string]$_ }
    $rc = $LASTEXITCODE
    $out | Set-Content -LiteralPath $runLog -Encoding UTF8
}
$freed = ''
foreach ($ln in $out) {
    if ($ln -match '本轮自动处置') { $freed = $ln.Trim() }
}
if ($note) { $freed = $note }
# 用 .NET 追加而非 Add-Content -Encoding UTF8：后者在**新建文件**时写 BOM，判据读末行
# 会把  当内容显示出来（本机立规「落盘扫控制符」同源问题，日志首行带 BOM 也会让
# grep 类判据漏判第一行）
[System.IO.File]::AppendAllText($hbPath, ("run {0} rc={1} {2}`r`n" -f $stamp, $rc, $freed),
    (New-Object System.Text.UTF8Encoding($false)))

# 心跳落痕自身不得膨胀（治理件不得自染，与 volumegov ledger_max 同口径）
$hb = Get-Item -LiteralPath $hbPath
if ($hb.Length -gt 65536) {
    $tail = Get-Content -LiteralPath $hbPath -Tail $HbKeep
    Set-Content -LiteralPath $hbPath -Value $tail -Encoding UTF8
}
# 日志只留 $LogKeep 天，且**只删本脚本自己的命名**（越界断言：路径必须以 LogRoot 开头）
Get-ChildItem -LiteralPath $LogRoot -Filter 'volume-daily-*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$LogKeep) -and
                   $_.FullName.StartsWith($LogRoot, [StringComparison]::OrdinalIgnoreCase) } |
    Remove-Item -Force -ErrorAction SilentlyContinue
exit 0
