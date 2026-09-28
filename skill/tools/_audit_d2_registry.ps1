# D2: 注册表完整性审计 (FIXED - skills are nested under .skills)
$indexPath = '<USER_HOME>\Desktop\workspace\焚诀\skill\registry\unified-skills-index.json'
$index = Get-Content $indexPath -Raw -Encoding UTF8 | ConvertFrom-Json
$skills = $index.skills
$indexNames = $skills.PSObject.Properties.Name
$indexCount = $indexNames.Count
$diskDirs = Get-ChildItem '<SKILLS_ROOT>' -Directory -ErrorAction SilentlyContinue
$diskNames = $diskDirs.Name
$diskCount = $diskNames.Count

$orphan = $diskNames | Where-Object { $_ -notin $indexNames }
$ghost = $indexNames | Where-Object { $_ -notin $diskNames }
$npmGhost = $ghost | Where-Object { $_ -match '^(npm-|@)' }
$nonNpmGhost = $ghost | Where-Object { $_ -notmatch '^(npm-|@)' }

Write-Host "Index skill entries: $indexCount"
Write-Host "Disk directories: $diskCount"
Write-Host "Orphan (disk, not index): $($orphan.Count)"
if ($orphan.Count -gt 0) { $orphan | ForEach-Object { Write-Host "  ORPHAN: $_" } }
Write-Host "Non-npm Ghost (index, not disk): $($nonNpmGhost.Count)"
if ($nonNpmGhost.Count -gt 0) { $nonNpmGhost | ForEach-Object { Write-Host "  GHOST: $_" } }
Write-Host "npm Ghost (expected, npm packages): $($npmGhost.Count)"
if ($npmGhost.Count -gt 0) { Write-Host "  (first 10): $($npmGhost[0..[Math]::Min(9, $npmGhost.Count-1)] -join ', ')" }

$score = 15 - ($nonNpmGhost.Count * 2)
if ($score -lt 0) { $score = 0 }
Write-Host ""
Write-Host "D2 Score: $score/15"
