# D9: 用户自建保护审计
$base = '<SKILLS_ROOT>\_my-skills'

Write-Host "=== _my-skills/ directory ==="
if (Test-Path $base) {
    $mySkills = Get-ChildItem $base -Directory -ErrorAction SilentlyContinue
    Write-Host "User skill dirs: $($mySkills.Count)"
    $mySkills | ForEach-Object { Write-Host "  $($_.Name)" }

    $regPath = "$base\registry.json"
    if (Test-Path $regPath) {
        $regSize = (Get-Item $regPath).Length
        Write-Host "registry.json: $regSize B"
        try {
            $reg = Get-Content $regPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $regCount = ($reg.PSObject.Properties | Measure-Object).Count
            Write-Host "  Protected skills in registry: $regCount"
            $reg.PSObject.Properties | ForEach-Object { Write-Host "    $($_.Name): $($_.Value)" }
        } catch {
            Write-Host "  registry.json PARSE FAILED: $_"
        }
    } else {
        Write-Host "registry.json: MISSING"
    }
} else {
    Write-Host "_my-skills/ MISSING"
}

# Check 焚诀-side mirror
Write-Host ""
$fenjueMySkills = '<USER_HOME>\Desktop\焚訣\skill\_my-skills'
if (Test-Path $fenjueMySkills) {
    Write-Host "焚诀/skill/_my-skills: EXISTS"
    $mirrorReg = "$fenjueMySkills\registry.json"
    if (Test-Path $mirrorReg) {
        Write-Host "  焚诀 registry mirror: EXISTS"
    } else {
        Write-Host "  焚诀 registry mirror: MISSING"
    }
} else {
    Write-Host "焚诀/skill/_my-skills: MISSING (no management mirror)"
}

# Check for anti-delete mechanisms in scripts
Write-Host ""
Write-Host "=== Anti-delete checks in scripts ==="
$syncScript = '<USER_HOME>\Desktop\焚訣\skill\sync\sync-skills-bridge.ps1'
if (Test-Path $syncScript) {
    $content = Get-Content $syncScript -Raw -Encoding UTF8
    $protectsUser = $content -match '_my-skills|protected|preserve|skip.*user|user.*skip'
    $hasConfirmDelete = $content -match 'confirm|Confirm.*delete|delete.*confirm'
    Write-Host "Protects _my-skills: $protectsUser"
    Write-Host "Delete confirmation: $hasConfirmDelete"
}

$score = 6
if (-not (Test-Path $base)) { $score -= 3 }
if (-not (Test-Path "$base\registry.json")) { $score -= 2 }
if (-not (Test-Path $fenjueMySkills)) { $score -= 1 }
if ($score -lt 0) { $score = 0 }

Write-Host ""
Write-Host "D9 Score: $score/6"
