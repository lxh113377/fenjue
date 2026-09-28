# ci_panel_daily.ps1 — 每日 CI 全绿面板上报（计划任务 \Fenjue-CIGreenPanel-Daily 的入口）
# 三件事：跑判据 → 状态行追加小台账 → 全量输出覆盖 latest（防无限长大）。
# 解释器一律写绝对路径：计划任务的 PATH 不等于交互 shell 的 PATH，裸 `python` 会在无人值守时
# 静默失败（同仓 snapshot_global_memory.ps1:31 已按此口径钉死）。
$ErrorActionPreference = 'Stop'
$root = '<USER_HOME>\Desktop\workspace\焚诀'
$py = 'C:\Program Files\Python312\python.exe'
$runs = Join-Path $root '.ci\logs\ci-panel-runs.log'
$latest = Join-Path $root '.ci\logs\ci-panel-latest.txt'
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

if (-not (Test-Path $py)) {
    Add-Content -Path $runs -Value "[$stamp] exit=2 BLOCKED: 解释器不存在 $py" -Encoding utf8
    Write-Error "解释器不存在：$py"
    exit 2
}

Set-Location $root
# 走项目自带的闸门包装器：除执行外还要在 ci-results/ 留一份 ci-panel.json + .log，
# 这样"每天真的跑了"是可被指到的产物，而不是某台机器上的计划任务注册项（D-81）。
# 命令串不写在这里：由 scripts/run_gate.py 的 TASK_CMDS 登记（写两遍必漂移，且 shlex 会把
# `scripts\ci_panel_report.py` 的 `\c` 当转义吞掉 —— 实测造出过 scriptsci_panel_report.py）。
$out = & $py scripts\run_gate.py --task ci-panel 2>&1
$code = $LASTEXITCODE
$summary = ($out | Select-String -Pattern '\[CI面板\]' | Select-Object -First 1)
$line = "[{0}] exit={1} {2}" -f $stamp, $code, $(if ($summary) { $summary.Line } else { ($out | Select-Object -First 1) })
Add-Content -Path $runs -Value $line -Encoding utf8
($out -join "`n") | Set-Content -Path $latest -Encoding utf8
exit $code
