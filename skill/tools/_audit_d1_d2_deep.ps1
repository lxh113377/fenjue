# Deep D1+D2: Check junction paths + ghost legitimacy
# Check OC alternative paths
Write-Host "=== OC junction search ==="
$ocPaths = @(
    '<USER_HOME>\.openclaw\skills',
    '<USER_HOME>\.openclaw\extensions',
    '<USER_HOME>\openclaw\skills'
)
foreach ($p in $ocPaths) {
    $exists = Test-Path $p
    if ($exists) {
        $item = Get-Item $p -Force -ErrorAction SilentlyContinue
        $isJunction = ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        Write-Host "$p : Exists, Junction=$isJunction"
        if ($isJunction) { Write-Host "  Target: $($item.Target)" }
    } else {
        Write-Host "$p : Not found"
    }
}

Write-Host ""
Write-Host "=== TC junction search ==="
$tcPaths = @(
    '<USER_HOME>\.trae\skills',
    '<USER_HOME>\.trae\extensions'
)
foreach ($p in $tcPaths) {
    $exists = Test-Path $p
    if ($exists) {
        $item = Get-Item $p -Force -ErrorAction SilentlyContinue
        $isJunction = ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        Write-Host "$p : Exists, Junction=$isJunction"
        if ($isJunction) { Write-Host "  Target: $($item.Target)" }
    } else {
        Write-Host "$p : Not found"
    }
}


# D2 Deep: Check if ghosts are legitimate OC-only
Write-Host ""
Write-Host "=== D2 Deep: Ghost vs OC-only ==="
$mapPath = '<USER_HOME>\Desktop\workspace\焚诀\skill\registry\cross_platform_map.json'
$map = Get-Content $mapPath -Raw -Encoding UTF8 | ConvertFrom-Json
$ocOnly = $map.cross_platform_mapping.oc_only_skills

$indexPath = '<USER_HOME>\Desktop\workspace\焚诀\skill\registry\unified-skills-index.json'
$index = Get-Content $indexPath -Raw -Encoding UTF8 | ConvertFrom-Json
$skills = $index.skills
$indexNames = $skills.PSObject.Properties.Name
$diskDirs = Get-ChildItem '<SKILLS_ROOT>' -Directory -ErrorAction SilentlyContinue
$diskNames = $diskDirs.Name

$ghost = $indexNames | Where-Object { $_ -notin $diskNames }
Write-Host "Total ghosts: $($ghost.Count)"

$ghostInOcOnly = $ghost | Where-Object { $_ -in $ocOnly }
$ghostNotInOcOnly = $ghost | Where-Object { $_ -notin $ocOnly }
Write-Host "Ghosts in OC-only list (expected): $($ghostInOcOnly.Count)"
Write-Host "Ghosts NOT in OC-only list (unexpected): $($ghostNotInOcOnly.Count)"
if ($ghostNotInOcOnly.Count -gt 0) {
    Write-Host "UNEXPECTED: $($ghostNotInOcOnly -join ', ')"
}

# Are all 37 ghosts exactly the OC-only list?
$allGhostsAreOcOnly = ($ghost.Count -eq $ocOnly.Count) -and ($ghostNotInOcOnly.Count -eq 0)
Write-Host ""
Write-Host "All ghosts are OC-only skills: $allGhostsAreOcOnly"
