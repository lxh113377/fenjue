# check_platform_tiers.ps1 — 平台分层一致性检查（R170）
# 用法: pwsh -NoProfile -File skill\tools\check_platform_tiers.ps1 [-All]
# 周检(默认)只查活跃端；-All 季度检全端（含备用）。
param([switch]$All)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tierFile = Join-Path $root 'registry\platform_tiers.json'
$registry = Join-Path $root 'registry'

if (-not (Test-Path -LiteralPath $tierFile)) { Write-Error "缺少 $tierFile"; exit 1 }
$cfg = Get-Content -Raw -LiteralPath $tierFile -Encoding UTF8 | ConvertFrom-Json
$known = @('wb','codex','cc','oc','tc','td','hm','mv')
$validValues = @('active','standby','incompatible')
$badKeys = @($cfg.tiers.PSObject.Properties.Name | Where-Object { $_ -notin $known })
if ($badKeys.Count -gt 0) { Write-Error "未知平台: $($badKeys -join ',')"; exit 1 }
$badVals = @($cfg.tiers.PSObject.Properties | Where-Object { $_.Value -notin $validValues })
if ($badVals.Count -gt 0) { Write-Error "非法 tier 值: $($badVals.Name -join ',')"; exit 1 }

$tiers = @{ active = @(); standby = @(); incompatible = @() }
foreach ($p in $cfg.tiers.PSObject.Properties) { $tiers[$p.Value] += $p.Name }
Write-Host ("active: " + ($tiers.active -join ', '))
Write-Host ("standby: " + ($tiers.standby -join ', '))
Write-Host ("incompatible: " + ($tiers.incompatible -join ', '))

$targets = if ($All) { $cfg.tiers.PSObject.Properties.Name } else { $tiers.active }
$fail = 0
foreach ($p in $targets) {
  $pf = Join-Path $registry ("platform-{0}.json" -f $p)
  if (-not (Test-Path -LiteralPath $pf)) {
    Write-Host "FAIL $p : 缺 platform-$p.json" -ForegroundColor Red; $fail++; continue
  }
  $j = Get-Content -Raw -LiteralPath $pf -Encoding UTF8 | ConvertFrom-Json
  if ($j.tier -ne $cfg.tiers.$p) {
    Write-Host "FAIL $p : tier 字段不符 (期望 $($cfg.tiers.$p), 实测 $($j.tier))" -ForegroundColor Red; $fail++; continue
  }
  if ($cfg.tiers.$p -eq 'incompatible') {
    Write-Host "OK $p : 不兼容占位（跳过非空校验）"
    continue
  }
  $n = if ($null -ne $j.skills_count) { [int]$j.skills_count } else { @($j.skills_list).Count }
  if ($n -le 0) {
    Write-Host "FAIL $p : skills_count=0" -ForegroundColor Red; $fail++
  } else {
    Write-Host "OK $p : $n skills"
  }
}
if ($fail -gt 0) { Write-Host "平台分层检查: FAIL ($fail)" -ForegroundColor Red; exit 1 }
Write-Host "平台分层检查: PASS"
exit 0
