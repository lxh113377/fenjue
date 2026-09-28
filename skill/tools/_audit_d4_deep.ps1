# D4: Cross-platform consistency check with correct paths
Write-Host "=== Registry directory listing ==="
Get-ChildItem '<USER_HOME>\Desktop\workspace\焚诀\skill\registry' -File | ForEach-Object { Write-Host "$($_.Name) : $([math]::Round($_.Length/1KB,1)) KB" }

Write-Host ""
Write-Host "=== cross_platform_map.json structure depth ==="
$map = Get-Content '<USER_HOME>\Desktop\workspace\焚诀\skill\registry\cross_platform_map.json' -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host "Top keys: $($map.PSObject.Properties.Name -join ', ')"

# Check oc_only_skills count
$ocOnly = $map.cross_platform_mapping.oc_only_skills
Write-Host "oc_only_skills: $($ocOnly.Count)"

# Check if there are other mapping sections
$cpmKeys = $map.cross_platform_mapping.PSObject.Properties.Name
Write-Host "cross_platform_mapping keys: $($cpmKeys -join ', ')"

# Check platforms section
$plats = $map.platforms
Write-Host "Platforms: $($plats.PSObject.Properties.Name -join ', ')"

# Verify each platform's skills_path exists
Write-Host ""
Write-Host "=== Platform path verification ==="
foreach ($pname in $plats.PSObject.Properties.Name) {
    $pdata = $plats.$pname
    $sp = $pdata.skills_path
    $exists = Test-Path $sp
    Write-Host "$pname : $sp -> Exists=$exists"
}

# Check if the 37 oc_only_skills match the 37 ghosts in D2
Write-Host ""
$uniPath = '<USER_HOME>\Desktop\workspace\焚诀\skill\registry\unified-skills-index.json'
$uni = Get-Content $uniPath -Raw -Encoding UTF8 | ConvertFrom-Json
$allSkills = $uni.skills.PSObject.Properties.Name
$diskDirs = (Get-ChildItem '<SKILLS_ROOT>' -Directory).Name
$actualGhosts = $allSkills | Where-Object { $_ -notin $diskDirs }
Write-Host "Ghosts (index but not disk): $($actualGhosts.Count)"
Write-Host "OC-only list: $($ocOnly.Count)"
$match = ($actualGhosts | Sort-Object) -join ',' -eq ($ocOnly | Sort-Object) -join ','
Write-Host "Ghosts === OC-only list: $match"
if (-not $match) {
    $onlyGhost = $actualGhosts | Where-Object { $_ -notin $ocOnly }
    $onlyOc = $ocOnly | Where-Object { $_ -notin $actualGhosts }
    if ($onlyGhost) { Write-Host "In ghosts but not OC-only: $($onlyGhost -join ', ')" }
    if ($onlyOc) { Write-Host "In OC-only but not ghosts: $($onlyOc -join ', ')" }
}
