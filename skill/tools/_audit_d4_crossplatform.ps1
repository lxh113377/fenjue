# D4: 跨平台映射审计 (FIXED - parsing actual structure)
$mapPath = '<USER_HOME>\Desktop\workspace\焚诀\skill\registry\cross_platform_map.json'

# Check BOM
$bytes = [System.IO.File]::ReadAllBytes($mapPath)
$hasBOM = ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
Write-Host "BOM: $hasBOM"

try {
    $map = Get-Content $mapPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host "JSON parse: OK"

    # Structure: .cross_platform_mapping has oc_only_skills array
    # .platforms has per-platform config (mv, cc, oc, wb, qw, tc)
    $platforms = $map.platforms
    Write-Host "Platform entries: $(($platforms.PSObject.Properties | Measure-Object).Count)"
    $platforms.PSObject.Properties | ForEach-Object {
        $name = $_.Name
        $pdata = $_.Value
        Write-Host "  $name : skills_path=$($pdata.skills_path) sync_type=$($pdata.sync_type)"
    }

    # Check cross_platform_mapping section
    $cpm = $map.cross_platform_mapping
    Write-Host ""
    Write-Host "Cross-platform mapping section:"
    Write-Host "  oc_only_skills count: $(($cpm.oc_only_skills | Measure-Object).Count)"
    if ($cpm.oc_only_skills) {
        Write-Host "  Sample: $($cpm.oc_only_skills[0..4] -join ', ')"
    }
    Write-Host "  Known keys: $($cpm.PSObject.Properties.Name -join ', ')"

    # Check the structure consistency between unified-skills-index and cross_platform_map
    Write-Host ""
    Write-Host "=== Consistency check ==="
    $uniPath = '<USER_HOME>\Desktop\焚訣\skill\registry\unified-skills-index.json'
    $uni = Get-Content $uniPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $uniSkills = $uni.skills
    $uniCount = ($uniSkills.PSObject.Properties | Measure-Object).Count
    Write-Host "Unified index skills: $uniCount"
    Write-Host "Cross-platform map ref: $($uni.cross_platform_map_ref)"

    # Check platform-qc.json
    $qcPath = '<USER_HOME>\Desktop\焚訣\skill\registry\platform-qc.json'
    if (Test-Path $qcPath) {
        Write-Host "platform-qc.json: STILL EXISTS (should be deleted) -> -2"
    } else {
        Write-Host "platform-qc.json: DELETED (expected)"
    }

    # Error scoring
    $errors = 0
    if ($hasBOM) { $errors++ }
    # Check if platform entries are consistent with junction test
    if ($null -eq $platforms.tc) { $errors++ }
    if ($null -eq $platforms.oc) { $errors++ }

    $score = 10 - ($errors * 2)
    if ($score -lt 0) { $score = 0 }
    Write-Host ""
    Write-Host "D4 Score: $score/10 (errors: $errors)"
} catch {
    Write-Host "JSON parse FAILED: $_"
    Write-Host "D4 Score: 0/10"
}
