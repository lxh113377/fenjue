<#
.SYNOPSIS
  平台键集单一源（2026-09-23 P2-8 平台合并落地）
.DESCRIPTION
  sync-skills-bridge.ps1 / watcher/auto-sync.ps1 / watcher/confirm-delete.ps1
  三处曾各硬编码一套平台键集（多的含退役 cc/td/mv、少的漏在役 oc/zc/codex），
  本文件为唯一正史，改键集只改此处。
  2026-09-26 治本（千问办公退役同轮，用户批准）：本文件原把端清单**再抄一遍**（写死
  「在役六端」且漏 qd），与 truth_constants 脱节 ⇒ 唯一正史自己就成了第二真相源。
  现改为**运行时从 truth_constants.json 读 endpoints.active 派生**，本文件只保留
  「端 ID → 注册表 install_state 键名」映射与展示名，端清单不再落抄本。
  正史 = truth_constants.json endpoints.active（当前在役七端 wb/tr/cx/hm/zc/oc/qd）：
    端 ID: wb / tr / cx / hm / zc / oc / qd（tr=TR 别名 TC，cx=Codex）
    注册表 install_state 键: wb / tc / codex / hm / zc / oc / qd（tr→tc，cx→codex）
  退役/历史键（cc/qw/mv/td）：禁新写；注册表既有值不动（C4 只清 platform-*.json 残留，
  不管 install_state 旧值）。qw 于 2026-09-26 退役（千问办公，junction 已拆）。
  读不到真相源即抛错（fail-closed），禁止静默回退到旧硬编码清单。
.USAGE
  . (Join-Path (Split-Path -Parent $PSScriptRoot) 'registry\platform-keys.ps1')
  # 之后用 $CanonicalInstallStateKeys / $CanonicalPlatformNames / $CanonicalEndpointIds
#>

$TruthPath = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'eval\truth_constants.json'
if (-not (Test-Path -LiteralPath $TruthPath)) {
    throw "platform-keys.ps1：真相源不可达 $TruthPath（端清单唯一权威，拒绝回退硬编码）"
}
$Truth = Get-Content -Raw -LiteralPath $TruthPath -Encoding UTF8 | ConvertFrom-Json
$CanonicalEndpointIds = @($Truth.endpoints.active)

# 端 ID → 注册表 install_state 键名：aliases 承载 tr→tc，cx→codex 为注册表历史命名（此处唯一落点）
$RegKeyAlias = @{}
foreach ($p in $Truth.endpoints.aliases.PSObject.Properties) { $RegKeyAlias[$p.Name] = [string]$p.Value }
$RegKeyAlias['cx'] = 'codex'
$CanonicalInstallStateKeys = @($CanonicalEndpointIds | ForEach-Object {
    if ($RegKeyAlias.ContainsKey($_)) { $RegKeyAlias[$_] } else { $_ }
})

# 展示名（人读文案，非端清单；端增删以 truth_constants 为准）
$CanonicalPlatformNames = @{
    wb    = "WorkBuddy"
    tc    = "TRAE SOLO CN"
    codex = "Codex (OpenAI)"
    hm    = "Hermes Agent"
    zc    = "ZCode"
    oc    = "OpenCode"
    qd    = "Qoder CN"
}
$LegacyInstallStateKeys = @("cc", "qw", "mv", "td")
