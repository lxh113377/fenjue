# D4: Full cross_platform_map audit
$map = Get-Content '<USER_HOME>\Desktop\workspace\焚诀\skill\registry\cross_platform_map.json' -Raw -Encoding UTF8 | ConvertFrom-Json

Write-Host "=== Complete top-level structure ==="
$map.PSObject.Properties | ForEach-Object {
    $key = $_.Name
    $val = $_.Value
    if ($val -is [array]) { Write-Host "$key : array[$($val.Count)]" }
    elseif ($val -is [System.Management.Automation.PSCustomObject]) { Write-Host "$key : object[$(($val.PSObject.Properties | Measure-Object).Count) keys]" }
    else { Write-Host "$key : $val" }
}

# Check skills section
Write-Host ""
Write-Host "=== Skills section ==="
$mapSkills = $map.skills
if ($mapSkills) {
    $mapSkillCount = ($mapSkills.PSObject.Properties | Measure-Object).Count
    Write-Host "Skills in cross_platform_map: $mapSkillCount"
    # Sample 3
    $sample = $mapSkills.PSObject.Properties.Name | Select-Object -First 3
    foreach ($s in $sample) {
        $sd = $mapSkills.$s
        Write-Host "  $s : $($sd.PSObject.Properties.Name -join ', ')"
    }
} else {
    Write-Host "No skills section"
}

# Check user_created_skills
Write-Host ""
Write-Host "=== User created skills section ==="
$ucs = $map.user_created_skills
if ($ucs) {
    Write-Host "user_created_skills: $($ucs.Count)"
    $ucs | ForEach-Object { Write-Host "  $_" }
}

# Map a random OC-only skill to verify mapping correctness
Write-Host ""
Write-Host "=== Verify OC-only skill mapping (sample: 1password) ==="
$skill = $map.skills.'1password'
if ($skill) {
    Write-Host "Mapped platforms: $($skill.PSObject.Properties.Name -join ', ')"
    $skill.PSObject.Properties | ForEach-Object {
        Write-Host "  $($_.Name): $($_.Value)"
    }
} else {
    Write-Host "1password: NOT in cross_platform_map skills section"
}

# Check unified index consistency
Write-Host ""
Write-Host "=== Unified index cross-ref ==="
$uni = Get-Content '<USER_HOME>\Desktop\workspace\焚诀\skill\registry\unified-skills-index.json' -Raw -Encoding UTF8 | ConvertFrom-Json
$uniSkillCount = ($uni.skills.PSObject.Properties | Measure-Object).Count

# Compare unified skills with cross_platform_map skills
$uniNames = $uni.skills.PSObject.Properties.Name
$mapNames = $map.skills.PSObject.Properties.Name

$inUniNotMap = $uniNames | Where-Object { $_ -notin $mapNames }
$inMapNotUni = $mapNames | Where-Object { $_ -notin $uniNames }

Write-Host "Unified skills: $uniSkillCount"
Write-Host "Cross-platform map skills: $($mapNames.Count)"
Write-Host "In unified but NOT in map: $($inUniNotMap.Count)"
Write-Host "In map but NOT in unified: $($inMapNotUni.Count)"

if ($inUniNotMap.Count -gt 0 -and $inUniNotMap.Count -le 10) {
    Write-Host "  Missing from map: $($inUniNotMap -join ', ')"
}
if ($inMapNotUni.Count -gt 0 -and $inMapNotUni.Count -le 10) {
    Write-Host "  Extra in map: $($inMapNotUni -join ', ')"
}
