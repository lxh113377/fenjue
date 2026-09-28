# D6: 文档质量审计 (FIXED - actual docs/ filenames)
$base = '<USER_HOME>\Desktop\workspace\焚诀\skill'
$docs = @(
    @{Path="$base\README.md"; Name="README"},
    @{Path="$base\OPERATIONS.md"; Name="OPERATIONS"},
    @{Path="$base\docs\architecture_overview.md"; Name="architecture_overview"},
    @{Path="$base\docs\junction_recovery_guide.md"; Name="junction_recovery_guide"},
    @{Path="$base\LESSONS.md"; Name="LESSONS"}
)

$missingCount = 0
foreach ($d in $docs) {
    if (Test-Path $d.Path) {
        $sizeKB = [math]::Round((Get-Item $d.Path).Length/1KB, 1)
        Write-Host "$($d.Name): $sizeKB KB OK"
    } else {
        Write-Host "$($d.Name): MISSING"
        $missingCount++
    }
}

# Check for supplementary docs (watcher, mv, proposal_flow)
Write-Host ""
$extraDocs = @('watcher.md', 'mv.md', 'proposal_flow.md')
$missingSupp = 0
foreach ($ed in $extraDocs) {
    $edPath = "$base\docs\$ed"
    if (Test-Path $edPath) {
        Write-Host "$ed : EXISTS"
    } else {
        Write-Host "$ed : MISSING"
        $missingSupp++
    }
}

# List all docs
Write-Host ""
Write-Host "All docs/ files:"
Get-ChildItem "$base\docs" -File | ForEach-Object { Write-Host "  $($_.Name): $([math]::Round($_.Length/1KB,1)) KB" }

# List notes
Write-Host ""
Write-Host "Notes/ files:"
Get-ChildItem "$base\notes" -File | ForEach-Object { Write-Host "  $($_.Name): $([math]::Round($_.Length/1KB,1)) KB" }

# Check checklist/
Write-Host ""
Write-Host "Checklist/ files:"
Get-ChildItem "$base\checklist" -File | ForEach-Object { Write-Host "  $($_.Name): $([math]::Round($_.Length/1KB,1)) KB" }

# Check if README/OPERATIONS accurately describe current state
Write-Host ""
Write-Host "=== README doc accuracy spot-check ==="
$readme = Get-Content "$base\README.md" -Raw -Encoding UTF8
$hasSyncSection = $readme -match 'cross-platform-skill-sync|sync.*skill|skill.*sync'
$hasJunctionSection = $readme -match 'junction|Junction'
$hasPlatformList = $readme -match '(CC|OC|WB|TC|QW|Marvis)'
Write-Host "README mentions sync: $hasSyncSection"
Write-Host "README mentions junction: $hasJunctionSection"
Write-Host "README mentions platforms: $hasPlatformList"

$score = 10 - ($missingCount * 2) - $missingSupp
if ($score -lt 0) { $score = 0 }
Write-Host ""
Write-Host "D6 Score: $score/10"
