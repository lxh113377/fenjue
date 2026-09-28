# D7: 同步脚本质量审计
$syncPath = '<USER_HOME>\Desktop\workspace\焚诀\skill\sync\sync-skills-bridge.ps1'

if (Test-Path $syncPath) {
    $size = (Get-Item $syncPath).Length
    $content = Get-Content $syncPath -Raw -Encoding UTF8
    $lines = (Get-Content $syncPath | Measure-Object).Count

    Write-Host "sync-skills-bridge.ps1: $size B, $lines lines"

    # Structural checks
    $hasTryCatch = $content -match 'try\s*\{'
    $hasCatch = $content -match '}\s*catch'
    $hasParam = $content -match 'param\s*\('
    $hasErrorAction = $content -match '-ErrorAction\s+(Stop|SilentlyContinue)'
    $hasThrow = $content -match 'throw\s+'
    $hasExit = $content -match 'exit\s+[1-9]'
    $hasWriteError = $content -match 'Write-Error'
    $hasLogging = $content -match 'Write-Host.*(\[OK\]|\[ERROR\]|\[WARN\]|\[INFO\])'
    $hasValidate = $content -match 'Test-Path.*Validate|Validate|validation'
    $hasTransaction = $content -match 'begin\s*\{|process\s*\{|end\s*\{'

    Write-Host "try/catch: $hasTryCatch (catch: $hasCatch)"
    Write-Host "param block: $hasParam"
    Write-Host "ErrorAction: $hasErrorAction"
    Write-Host "throw: $hasThrow"
    Write-Host "non-zero exit: $hasExit"
    Write-Host "Write-Error: $hasWriteError"
    Write-Host "Logging markers: $hasLogging"
    Write-Host "Validation: $hasValidate"

    # Function/Module structure
    $functionCount = ([regex]::Matches($content, 'function\s+\w+')).Count
    Write-Host "Function count: $functionCount"

    # Check for sync logic keywords
    $hasJunction = $content -match 'Junction|junction|ReparsePoint'
    $hasSyncLogic = $content -match 'sync|Sync|Copy-Item|Robocopy'
    Write-Host "Junction awareness: $hasJunction"
    Write-Host "Sync logic: $hasSyncLogic"

    $score = 5  # base
    if ($hasTryCatch) { $score += 1 }
    if ($hasErrorAction) { $score += 1 }
    if ($hasValidate) { $score += 1 }
    if ($score -gt 8) { $score = 8 }
    if (-not $hasSyncLogic) { $score -= 3 }

    Write-Host ""
    Write-Host "D7 Score: $score/8"
} else {
    Write-Host "sync-skills-bridge.ps1: MISSING"
    Write-Host "D7 Score: 0/8"
}
