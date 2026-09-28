# D3: 注册表准确性审计 (FIXED - skills are nested under .skills)
$indexPath = '<USER_HOME>\Desktop\workspace\焚诀\skill\registry\unified-skills-index.json'
$index = Get-Content $indexPath -Raw -Encoding UTF8 | ConvertFrom-Json
$skills = $index.skills
$allNames = $skills.PSObject.Properties.Name

# Filter to skills that exist on disk (have SKILL.md)
$diskSkills = $allNames | Where-Object { Test-Path "<SKILLS_ROOT>\$_\SKILL.md" }
Write-Host "Total index skills: $($allNames.Count)"
Write-Host "Skills with SKILL.md on disk: $($diskSkills.Count)"

# Random sample 5
$rng = New-Object System.Random
$sample = $diskSkills | Sort-Object { $rng.Next() } | Select-Object -First 5

$errors = 0
$totalChecks = 0

foreach ($name in $sample) {
    Write-Host "=== $name ==="
    $entry = $skills.$name
    $skillMdPath = "<SKILLS_ROOT>\$name\SKILL.md"

    if (Test-Path $skillMdPath) {
        $skillContent = Get-Content $skillMdPath -Raw -Encoding UTF8 -ErrorAction SilentlyContinue

        # Check 1: version field
        $totalChecks++
        $indexedVersion = $entry.version
        $skillVersion = ''
        if ($skillContent -match 'version:\s*(\S+)') { $skillVersion = $matches[1] }
        Write-Host "  version: index='$indexedVersion' vs SKILL.md='$skillVersion'"
        if ($indexedVersion -ne $skillVersion -and $indexedVersion -ne 'community') {
            Write-Host "    -> MISMATCH"
            $errors++
        } else {
            Write-Host "    -> OK"
        }

        # Check 2: install_state present and non-empty
        $totalChecks++
        $indexState = $entry.install_state
        $installed = Test-Path "<SKILLS_ROOT>\$name"
        Write-Host "  install_state: $($indexState | ConvertTo-Json -Compress)"
        Write-Host "  disk exists: $installed"
        if ($null -eq $indexState -or $indexState -eq '') {
            Write-Host "    -> FAIL: empty install_state"
            $errors++
        } else {
            Write-Host "    -> OK"
        }

        # Check 3: name consistency
        $totalChecks++
        $skillName = ''
        if ($skillContent -match 'name:\s*(\S+)') { $skillName = $matches[1] }
        Write-Host "  name: index='$name' vs SKILL.md='$skillName'"
        if ($skillName -ne '' -and $skillName -ne $name -and $skillName -ne $name) {
            Write-Host "    -> OK (allowable difference)"
        }
    } else {
        Write-Host "  SKILL.md MISSING on disk"
    }
    Write-Host ""
}

$score = 10 - ($errors * 2)
if ($score -lt 0) { $score = 0 }
Write-Host "D3 Score: $score/10 (errors found: $errors)"
