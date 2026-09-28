# 锋(Feng) — Registry Optimization v1.0
# 2026-07-05
# 自动执行：新增 skill → 写入注册表（无需审批）
# 需审批：删除/清理（报告差异）

param(
    [switch]$ForceUpdate,
    [switch]$ReportOnly
)

$RegistryPath = "<USER_HOME>\Desktop\workspace\焚诀\skill\registry"
$UnifiedIndexPath = Join-Path $RegistryPath "unified-skills-index.json"
$CrossPlatformMapPath = Join-Path $RegistryPath "cross_platform_map.json"
$GlobalSkillsPath = "<SKILLS_ROOT>"
$NotePath = "<USER_HOME>\Desktop\workspace\焚诀\skill\notes\2026-07-05-optimize.md"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " 锋(Feng) - Registry Optimization v1.0     " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# === Step 1: Load Current Data ===
Write-Host "`n[Step 1] Loading current registry..." -ForegroundColor Cyan

$unifiedJson = Get-Content $UnifiedIndexPath -Raw -Encoding UTF8
$unified = $unifiedJson | ConvertFrom-Json

$mapJson = Get-Content $CrossPlatformMapPath -Raw -Encoding UTF8
$crossMap = $mapJson | ConvertFrom-Json

$registryNames = $unified.skills.PSObject.Properties.Name | Sort-Object
$globalSkills = Get-ChildItem -Path $GlobalSkillsPath -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name | Sort-Object

Write-Host "Registry skills: $($registryNames.Count)" -ForegroundColor Gray
Write-Host "Global skills:   $($globalSkills.Count)" -ForegroundColor Gray

# === Step 2: Identify differences ===
Write-Host "`n[Step 2] Analyzing differences..." -ForegroundColor Cyan

# Skills to ADD (exist on disk, missing from registry)
$toAdd = $globalSkills | Where-Object { $registryNames -notcontains $_ } | Sort-Object
Write-Host "Missing from registry (will auto-add): $($toAdd.Count)" -ForegroundColor Yellow

# Skills that are ORPHANED (in registry, not on disk)
$orphaned = $registryNames | Where-Object { $globalSkills -notcontains $_ } | Sort-Object
Write-Host "Orphaned in registry (need approval): $($toAdd.Count)" -ForegroundColor Yellow

# Separate orphaned by type
$orphanedUserCreated = @()
$orphanedCommunity = @()
foreach ($s in $orphaned) {
    if ($unified.skills.$s.user_created) {
        $orphanedUserCreated += $s
    } else {
        $orphanedCommunity += $s
    }
}

Write-Host "  - Orphaned user-created: $($orphanedUserCreated.Count)" -ForegroundColor Red
$orphanedUserCreated | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
Write-Host "  - Orphaned community:    $($orphanedCommunity.Count)" -ForegroundColor Yellow
$orphanedCommunity | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }

# === Step 3: Domain classification for new skills ===
Write-Host "`n[Step 3] Classifying new skills by domain..." -ForegroundColor Cyan

# 2026-09-22 第 10 轮：本函数原返回旧数字前缀域（01-memory-knowledge / 06-frontend-ui /
# 09-dev-tools 等 16 域体系，2026-08-16 已软删除）。按 build_registry._infer_domain 的明令
# 「禁止再生成」，此处**去掉整套前缀猜测**，统一落 general_utils；
# 真实域判定唯一权威 = eval/build_registry.py → domain_classifier.classify_domain。
function Get-SkillDomain {
    param([string]$Name)
    return "general_utils"
}

if ($ReportOnly) {
    Write-Host "`nNOTE: Report-only mode. No changes will be made." -ForegroundColor Yellow
    Write-Host "Use -ForceUpdate to execute." -ForegroundColor Yellow
} elseif ($ForceUpdate) {
    Write-Host "`n[Step 4] Updating unified-skills-index.json..." -ForegroundColor Cyan

    $addedCount = 0
    foreach ($skillName in $toAdd) {
        if ($unified.skills.PSObject.Properties.Name -contains $skillName) {
            Write-Host "  SKIP $skillName (already exists)" -ForegroundColor Gray
            continue
        }

        $isUserCreated = $false
        $source = "community"
        if ($skillName -eq "_my-skills") { $isUserCreated = $true; $source = "user-created" }

        $domain = Get-SkillDomain -Name $skillName

        $newEntry = [PSCustomObject]@{
            name                = $skillName
            display_name        = ($skillName -replace '-', ' ')
            domain              = $domain
            compatible_platforms = @("oc", "wb", "cc", "tc")
            source              = $source
            user_created        = $isUserCreated
        }

        $unified.skills | Add-Member -MemberType NoteProperty -Name $skillName -Value $newEntry -Force
        Write-Host "  ADD $skillName -> $domain" -ForegroundColor Green
        $addedCount++
    }

    $unified.last_updated = (Get-Date -Format "o")
    $unified | ConvertTo-Json -Depth 10 | Set-Content $UnifiedIndexPath -Encoding UTF8
    Write-Host "  unified-skills-index.json updated ($addedCount new)" -ForegroundColor Green

    # === Step 5: Update cross_platform_map.json ===
    Write-Host "`n[Step 5] Updating cross_platform_map.json install states..." -ForegroundColor Cyan

    $mapAdded = 0
    foreach ($skillName in $toAdd) {
        if ($crossMap.skills.PSObject.Properties.Name -contains $skillName) {
            Write-Host "  SKIP $skillName (already in map)" -ForegroundColor Gray
            continue
        }

        $installState = [PSCustomObject]@{
            oc = $true; wb = $true; cc = $true; tc = $true
            qc = $false; mv = $null
        }

        $entry = [PSCustomObject]@{
            name          = $skillName
            qc_equivalent = $null
            install_state = $installState
        }

        $crossMap.skills | Add-Member -MemberType NoteProperty -Name $skillName -Value $entry -Force
        Write-Host "  ADD $skillName -> install_state" -ForegroundColor Green
        $mapAdded++
    }

    $crossMap.last_updated = (Get-Date -Format "o")
    $crossMap | ConvertTo-Json -Depth 10 | Set-Content $CrossPlatformMapPath -Encoding UTF8
    Write-Host "  cross_platform_map.json updated ($mapAdded new)" -ForegroundColor Green
}

# === Summary ===
Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host " Summary" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

if ($ForceUpdate) {
    Write-Host "✅ Auto-added: $($toAdd.Count) skills to registry" -ForegroundColor Green
    Write-Host ""
    Write-Host "⚠️  PENDING APPROVAL (orphaned entries):" -ForegroundColor Yellow
    if ($orphanedUserCreated.Count -gt 0) {
        Write-Host "  User-created (need careful handling):" -ForegroundColor Red
        $orphanedUserCreated | ForEach-Object { Write-Host "    - $_" }
    }
    if ($orphanedCommunity.Count -gt 0) {
        Write-Host "  Community (safe to remove after approval):" -ForegroundColor Yellow
        $orphanedCommunity | ForEach-Object { Write-Host "    - $_" }
    }
} else {
    Write-Host "Report Only — no changes made." -ForegroundColor Yellow
    Write-Host "Add these ($($toAdd.Count)):"
    $toAdd | ForEach-Object { Write-Host "  + $_" }
    Write-Host ""
    Write-Host "Orphaned ($($orphaned.Count)) — need approval:"
    $orphaned | ForEach-Object { Write-Host "  - $_" }
    Write-Host ""
    Write-Host "Run with -ForceUpdate to apply additions." -ForegroundColor Cyan
}
