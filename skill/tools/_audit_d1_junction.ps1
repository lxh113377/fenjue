# D1: Junction连通性审计
$dirs = @{
    'CC' = '<USER_HOME>\.claude\skills'
    'OC' = '<USER_HOME>\.openclaw\skills'
    'WB' = '<USER_HOME>\.workbuddy\skills'
    'TC' = '<USER_HOME>\.trae\skills'
}
$score = 0
foreach ($platform in $dirs.Keys) {
    $d = $dirs[$platform]
    $exists = Test-Path $d
    if ($exists) {
        $item = Get-Item $d -Force -ErrorAction SilentlyContinue
        $isJunction = ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        if ($isJunction) {
            $target = $item.Target
            Write-Host "$platform [OK] Junction -> $target"
            if ($target -eq '<SKILLS_ROOT>') { $score += 3 }
            else { Write-Host "  WARN: Target not <SKILLS_ROOT>, got $target" }
        } else {
            Write-Host "$platform [FAIL] Exists but NOT a junction"
        }
    } else {
        Write-Host "$platform [FAIL] Path does not exist"
    }
}
Write-Host ""
Write-Host "D1 Score: $score/15"
