# D1: Enumerate all possible junction paths for OC/TC
Write-Host "=== Searching for any .openclaw directory ==="
$ocHome = Get-ChildItem "<USER_HOME>" -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*openclaw*' -or $_.Name -like '*claw*' }
$ocHome | ForEach-Object { Write-Host "Found: $($_.FullName)" }

Write-Host ""
Write-Host "=== Searching for any .trae directory ==="
$tcHome = Get-ChildItem "<USER_HOME>" -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*trae*' }
$tcHome | ForEach-Object { Write-Host "Found: $($_.FullName)" }

Write-Host ""
Write-Host "=== All . directories in user home ==="
Get-ChildItem "<USER_HOME>" -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '.*' } | ForEach-Object { Write-Host $_.Name }

Write-Host ""
Write-Host "=== Check existing junctions that point to <SKILLS_ROOT> ==="
$junctions = @()
Get-ChildItem "<USER_HOME>" -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '.*' } | ForEach-Object {
    try {
        $item = Get-Item $_.FullName -Force -ErrorAction Stop
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            $target = $item.Target
            Write-Host "$($_.Name) -> $target"
            if ($target -eq '<SKILLS_ROOT>') { Write-Host '  *** SKILLS JUNCTION ***' }
        }
    } catch {}
}

# Also check non-hidden directories that might be skills junctions
Write-Host ""
Write-Host "=== Non-hidden skill junction candidates ==="
$candidates = @('claude', 'workbuddy', 'openclaw', 'trae-cn', 'to-desk-ai')
foreach ($c in $candidates) {
    $p = "<USER_HOME>\$c"
    if (Test-Path $p) {
        Write-Host "$c exists (directory)"
        # Check for skills subdir
        $sp = "$p\skills"
        if (Test-Path $sp) {
            $item = Get-Item $sp -Force -ErrorAction SilentlyContinue
            $isJunc = ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
            Write-Host "  skills/: Junction=$isJunc"
            if ($isJunc) { Write-Host "  Target: $($item.Target)" }
        }
    }
}
