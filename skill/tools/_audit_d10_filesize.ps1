# D10: 文件大小控制审计
$files = @{
    'unified-skills-index.json' = '<USER_HOME>\Desktop\workspace\焚诀\skill\registry\unified-skills-index.json'
    'cross_platform_map.json' = '<USER_HOME>\Desktop\workspace\焚诀\skill\registry\cross_platform_map.json'
    'sync-skills-bridge.ps1' = '<USER_HOME>\Desktop\workspace\焚诀\skill\sync\sync-skills-bridge.ps1'
    'detect-changes.ps1' = '<USER_HOME>\Desktop\workspace\焚诀\skill\watcher\detect-changes.ps1'
    'auto-sync.ps1' = '<USER_HOME>\Desktop\焚訣\skill\watcher\auto-sync.ps1'
    'confirm-delete.ps1' = '<USER_HOME>\Desktop\焚訣\skill\watcher\confirm-delete.ps1'
}

$totalSize = 0
$warnings = 0

Write-Host "=== Core File Sizes ==="
foreach ($name in $files.Keys) {
    $path = $files[$name]
    if (Test-Path $path) {
        $size = (Get-Item $path).Length
        $sizeKB = [math]::Round($size/1KB, 1)
        $totalSize += $size

        $status = "OK"
        # Thresholds: >200KB=warn, >500KB=critical
        if ($size -gt 500KB) { $status = "CRITICAL"; $warnings += 2 }
        elseif ($size -gt 200KB) { $status = "LARGE"; $warnings += 1 }

        Write-Host "$name : $sizeKB KB [$status]"
    } else {
        Write-Host "$name : MISSING"
        $warnings += 1
    }
}

$totalKB = [math]::Round($totalSize/1KB, 1)
Write-Host ""
Write-Host "Total core size: $totalKB KB"

# Also check docs
Write-Host ""
Write-Host "=== Document Sizes ==="
$docFiles = @(
    '<USER_HOME>\Desktop\焚訣\skill\README.md',
    '<USER_HOME>\Desktop\焚訣\skill\OPERATIONS.md',
    '<USER_HOME>\Desktop\焚訣\skill\LESSONS.md'
)
foreach ($df in $docFiles) {
    if (Test-Path $df) {
        $sz = [math]::Round((Get-Item $df).Length/1KB, 1)
        Write-Host "$(Split-Path $df -Leaf): $sz KB"
    }
}

$score = 4 - $warnings
if ($score -lt 0) { $score = 0 }
if ($score -gt 4) { $score = 4 }

Write-Host ""
Write-Host "D10 Score: $score/4"
