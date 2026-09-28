# D5: Watcher自动化审计
$base = '<USER_HOME>\Desktop\workspace\焚诀\skill\watcher'
$scripts = @('detect-changes.ps1', 'auto-sync.ps1', 'confirm-delete.ps1')

$allOk = $true
$confirmNoTry = $false

foreach ($s in $scripts) {
    $sp = Join-Path $base $s
    Write-Host "=== $s ==="
    if (Test-Path $sp) {
        $size = (Get-Item $sp).Length
        $content = Get-Content $sp -Raw -Encoding UTF8
        $hasTry = $content -match 'try\s*\{'
        $hasCatch = $content -match '}\s*catch'
        $hasParam = $content -match 'param\s*\('
        $hasExit = $content -match 'exit\s+\d+'
        $hasWriteError = $content -match 'Write-Error'
        $hasWriteHost = $content -match 'Write-Host'

        Write-Host "  Size: $size B | try: $hasTry | catch: $hasCatch | param: $hasParam"
        Write-Host "  exit codes: $hasExit | Write-Error: $hasWriteError | Write-Host: $hasWriteHost"

        if ($s -eq 'confirm-delete.ps1' -and (-not $hasTry)) {
            $confirmNoTry = $true
            Write-Host "  ** ISSUE: confirm-delete.ps1 lacks try/catch **"
        }
        if ($size -lt 500) {
            Write-Host "  ** ISSUE: File too small ($size bytes), may be stub **"
            $allOk = $false
        }
    } else {
        Write-Host "  ** MISSING **"
        $allOk = $false
    }
    Write-Host ""
}

# Check scheduled task
Write-Host "=== Scheduled Task Check ==="
$taskInfo = schtasks /query /tn "skill-watcher-detect" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "Scheduled task EXISTS"
} else {
    Write-Host "Scheduled task NOT FOUND (may run differently)"
}

$score = 10
if (-not $allOk) { $score -= 3 }
if ($confirmNoTry) { $score -= 3 }
Write-Host ""
Write-Host "D5 Score: $score/10"
