# D10: Fix file size check with correct paths
$REG = "<USER_HOME>\Desktop\焚訣\skill\registry"
$BASE = "<USER_HOME>\Desktop\焚訣\skill"

Write-Host "=== D10 REFINED: File Size Control ==="
$files = @(
    @{Path="$REG\unified-skills-index.json"; Name="unified-skills-index.json"; Max=300000},
    @{Path="$REG\cross_platform_map.json"; Name="cross_platform_map.json"; Max=150000},
    @{Path="$BASE\sync\sync-skills-bridge.ps1"; Name="sync-skills-bridge.ps1"; Max=30000},
    @{Path="$BASE\README.md"; Name="README.md"; Max=15000},
    @{Path="$BASE\OPERATIONS.md"; Name="OPERATIONS.md"; Max=15000},
    @{Path="$BASE\LESSONS.md"; Name="LESSONS.md"; Max=15000},
    @{Path="$BASE\docs\architecture_overview.md"; Name="architecture_overview.md"; Max=10000},
    @{Path="$BASE\docs\junction_recovery_guide.md"; Name="junction_recovery_guide.md"; Max=10000},
    @{Path="$BASE\checklist\weekly_maintenance.md"; Name="weekly_maintenance.md"; Max=10000},
    @{Path="$BASE\watcher\README.md"; Name="watcher_README.md"; Max=10000},
    @{Path="$BASE\watcher\detect-changes.ps1"; Name="detect-changes.ps1"; Max=15000},
    @{Path="$BASE\watcher\auto-sync.ps1"; Name="auto-sync.ps1"; Max=20000},
    @{Path="$BASE\watcher\confirm-delete.ps1"; Name="confirm-delete.ps1"; Max=15000},
    @{Path="$BASE\manage.ps1"; Name="manage.ps1"; Max=15000}
)
$score = 4
$totalSize = 0
foreach ($f in $files) {
    if (Test-Path $f.Path) {
        $fs = (Get-Item $f.Path).Length
        $totalSize += $fs
        $ok = $fs -le $f.Max
        $status = if ($ok) { "OK" } else { "OVERSIZE" }
        Write-Host "  $($f.Name): ${fs}B / max $($f.Max) -> $status"
        if (-not $ok) { $score -= 0.5 }
    } else {
        Write-Host "  $($f.Name): MISSING **"
        $score -= 0.5
    }
}
Write-Host "  Total core files size: ${totalSize}B ($([Math]::Round($totalSize/1024, 1))KB)"
Write-Host "  D10 REFINED Score: $score/4"
