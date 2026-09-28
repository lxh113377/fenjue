# D10: Check actual watcher file paths (encoding issue)
Write-Host "=== Listing watcher directory ==="
Get-ChildItem '<USER_HOME>\Desktop\workspace\焚诀\skill\watcher' -File | ForEach-Object { Write-Host "$($_.Name) : $([math]::Round($_.Length/1KB,1)) KB" }

Write-Host ""
Write-Host "=== Checking D10 script paths that failed ==="
$autoSync = '<USER_HOME>\Desktop\workspace\焚诀\skill\watcher\auto-sync.ps1'
$confirmDelete = '<USER_HOME>\Desktop\焚訣\skill\watcher\confirm-delete.ps1'

Write-Host "auto-sync (焚诀): $(Test-Path $autoSync)"
Write-Host "confirm-delete (焚訣): $(Test-Path $confirmDelete)"

# Check which path actually works
$altAutoSync = '<USER_HOME>\Desktop\焚訣\skill\watcher\auto-sync.ps1'
Write-Host "auto-sync (焚訣): $(Test-Path $altAutoSync)"

$altConfirmDelete = '<USER_HOME>\Desktop\workspace\焚诀\skill\watcher\confirm-delete.ps1'
Write-Host "confirm-delete (焚诀): $(Test-Path $altConfirmDelete)"
