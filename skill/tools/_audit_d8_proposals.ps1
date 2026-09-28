# D8: 删除提案机制审计
$base = '<USER_HOME>\Desktop\workspace\焚诀\skill\proposals'

Write-Host "=== proposals/ directory ==="
if (Test-Path $base) {
    $proposals = Get-ChildItem $base -File -ErrorAction SilentlyContinue
    Write-Host "Active proposals: $($proposals.Count)"
    $proposals | ForEach-Object { Write-Host "  $($_.Name): $([math]::Round($_.Length/1KB,1)) KB" }
} else {
    Write-Host "proposals/ MISSING"
}

Write-Host ""
$archivedPath = "$base\archived"
Write-Host "=== proposals/archived/ ==="
if (Test-Path $archivedPath) {
    $archived = Get-ChildItem $archivedPath -File -ErrorAction SilentlyContinue
    Write-Host "Archived proposals: $($archived.Count)"
    $archived | ForEach-Object { Write-Host "  $($_.Name): $([math]::Round($_.Length/1KB,1)) KB" }
} else {
    Write-Host "archived/ MISSING"
}

# Check for STATUS.md or tracking file
Write-Host ""
$statusPath = "$base\STATUS.md"
if (Test-Path $statusPath) {
    Write-Host "STATUS.md: EXISTS"
} else {
    Write-Host "STATUS.md: MISSING (no proposal tracking)"
}

# Check proposal format (sample one)
Write-Host ""
Write-Host "=== Proposal format check (sample) ==="
$sampleProposal = Get-ChildItem $base -File -ErrorAction SilentlyContinue | Select-Object -First 1
if ($sampleProposal) {
    $content = Get-Content $sampleProposal.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    $hasDate = $content -match '\d{4}-\d{2}-\d{2}'
    $hasTarget = $content -match '(target|目标|delete|删除|提案)'
    $hasStatus = $content -match '(status|状态|approved|rejected|pending|executed)'
    $hasRationale = $content -match '(reason|原因|rationale|justification)'
    Write-Host "Sample: $($sampleProposal.Name)"
    Write-Host "  Date: $hasDate | Target: $hasTarget | Status: $hasStatus | Rationale: $hasRationale"
}

$score = 8
if ($proposals.Count -lt 1) { $score -= 2 }
if ($archived.Count -lt 2) { $score -= 2 }
if (-not (Test-Path $statusPath)) { $score -= 1 }
if ($score -lt 0) { $score = 0 }

Write-Host ""
Write-Host "D8 Score: $score/8"
