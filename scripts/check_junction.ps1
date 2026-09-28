#!/usr/bin/env pwsh
<#
check_junction.ps1 — 焚诀六端 junction 断裂探活（R198 补漏-3 / agent常见困难 一.3）

治「Junction/符号链接断裂时，路径存在但内容不可达」：路径在，但指向失效，
AI 读到空目录或旧内容，记忆/技能静默缺失。

机制：
  ① 已知 junction 表（基于磁盘实测挂载点）逐一校验
     - 挂载点存在？  - 是 ReparsePoint( junction/symlink)？
     - 目标 == 预期？ - 目标可达（可列目录/读文件）？
  ② 动态扫描各客户端根目录下的所有 ReparsePoint，通用校验可达性（捕获未知 junction）
  ③ HM 端逐技能 junction 扫描（HERMES_HOME\skills\global-skills\*）：
     该端不用整根 junction，而是逐技能挂载（164 条规模），是本脚本此前唯一未覆盖的形态。
     非 junction 实体项 = MISMATCH；目标不可达项 = BROKEN；根不存在 = 显式 WARN（不可信，非静默 PASS）。
  ④ 输出 OK / BROKEN(目标不可达) / MISMATCH(目标≠预期) / MISSING(挂载点不存在)
     + 修复提示（mklink /J）

退出码：0 全部 OK；1 存在 BROKEN/MISMATCH/MISSING。（③ 的「根不存在」不计异常：端未安装属环境事实，
   但必须打印 WARN 行，不得静默 PASS —— R247。）

覆盖口径（2026-09-23 补全）：六端 = HM/WB/CX/TC/ZC/OC（truth_constants.endpoints.active）。
此前本脚本只覆盖 WB/古端 + 焚诀自身，ZC/TC/HM 三端既不在 Known 表也不在扫描根内
（2026-08-15 建表时 ZC 未入役、HM 曾被列为退役端）→ 脚本报「异常 0 个」属假绿。
2026-09-23 OC（OpenCode）入役补 4 条 Known（.config\opencode + .opencode 兼容位双 junction）。
CX 端 skills 为物理镜像（.agents\skills，非 junction），由 check-skill-mirror.ps1 覆盖，不入本表。
#>
param(
    [switch]$Json,
    [string[]]$Roots = @(
        "<USER_HOME>\Desktop\workspace\焚诀",
        "<USER_HOME>\.workbuddy",
        "<USER_HOME>\.Codex",
        "<USER_HOME>\.codex",
        "<USER_HOME>\.claude",
        "<USER_HOME>\.openclaw",
        "<USER_HOME>\.agents",
        "<USER_HOME>\.zcode",
        "<USER_HOME>\.trae-cn",
        "<USER_HOME>\.config\opencode",
        "<USER_HOME>\.opencode"
    ),
    # 隔离桩注入用：跳过 ① Known 表，仅跑 ②/③（防桩结果依赖本机真实挂载状态）
    [switch]$SkipKnownTable,
    # HM 逐技能 junction 根（默认由 HERMES_HOME 推导；隔离桩注入临时目录）
    [string]$HermesSkillsRoot = ''
)

$ErrorActionPreference = 'Stop'

$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { "<USER_HOME>\AppData\Local\hermes" }
if (-not $HermesSkillsRoot) { $HermesSkillsRoot = Join-Path $HermesHome "skills\global-skills" }

# ① 已知 junction 表（mount -> expected target），磁盘实测
#    2026-09-23 补 ZC / TC / HM 三端（五端口径 = HM/WB/CX/TC/ZC）：
#      - .zcode\skills / .zcode\memory            = ZC 2026-09-22 入役（一级 junction）
#      - .trae-cn\{skills,memory,memory_content}  = TC（TR 别名）
#      - <HERMES_HOME>\memories                   = HM 记忆树
#    2026-09-23 补 OC 四端（六端口径 = HM/WB/CX/TC/ZC/OC）：
#      - .config\opencode\{skills,memory}         = OC 2026-09-23 入役（一级 junction）
#      - .opencode\{skills,memory}                = OC 兼容位双 junction
#    不列 .zcode\memory_content：ZC 程序内置无 memory 目录约定（truth_constants.endpoints.notes.zc）。
#    不列 .config\opencode\memory_content：OC 程序内置无 memory 目录约定（与 ZC 同形态）。
$Known = @(
    @{ Mount = "<USER_HOME>\Desktop\workspace\焚诀\memory";        Target = "<MEMORY_ROOT>\memory" },
    @{ Mount = "<USER_HOME>\Desktop\workspace\焚诀\memory_content"; Target = "<MEMORY_ROOT>" },
    @{ Mount = "<USER_HOME>\Desktop\workspace\焚诀\prompts";        Target = "<MEMORY_ROOT>\prompts" },
    @{ Mount = "<USER_HOME>\.workbuddy\memory";                    Target = "<MEMORY_ROOT>\memory" },
    @{ Mount = "<USER_HOME>\.workbuddy\memory_content";            Target = "<MEMORY_ROOT>" },
    @{ Mount = "<USER_HOME>\.workbuddy\skills";                    Target = "<SKILLS_ROOT>" },
    @{ Mount = "<USER_HOME>\.Codex\memory_content";                Target = "<MEMORY_ROOT>" },
    @{ Mount = "<USER_HOME>\.codex\memory_content";                Target = "<MEMORY_ROOT>" },
    @{ Mount = "<USER_HOME>\.zcode\skills";                        Target = "<SKILLS_ROOT>" },
    @{ Mount = "<USER_HOME>\.zcode\memory";                        Target = "<MEMORY_ROOT>" },
    @{ Mount = "<USER_HOME>\.config\opencode\skills";              Target = "<SKILLS_ROOT>" },
    @{ Mount = "<USER_HOME>\.config\opencode\memory";              Target = "<MEMORY_ROOT>" },
    @{ Mount = "<USER_HOME>\.opencode\skills";                     Target = "<SKILLS_ROOT>" },
    @{ Mount = "<USER_HOME>\.opencode\memory";                     Target = "<MEMORY_ROOT>" },
    @{ Mount = "<USER_HOME>\.trae-cn\skills";                      Target = "<SKILLS_ROOT>" },
    @{ Mount = "<USER_HOME>\.trae-cn\memory";                      Target = "<MEMORY_ROOT>" },
    @{ Mount = "<USER_HOME>\.trae-cn\memory_content";              Target = "<MEMORY_ROOT>" },
    @{ Mount = (Join-Path $HermesHome "memories");                    Target = "<MEMORY_ROOT>" },
    # CC 端 2026-09-08 弃用：挂载点保留留痕，SKIP 不计异常（R269 伴生：活跃口径以 ENDPOINTS 为准）
    @{ Mount = "<USER_HOME>\.claude\memory";                       Target = "<MEMORY_ROOT>\memory"; Retired = $true },
    @{ Mount = "<USER_HOME>\.claude\memory_content";               Target = "<MEMORY_ROOT>"; Retired = $true },
    @{ Mount = "<USER_HOME>\.claude\skills";                       Target = "<SKILLS_ROOT>"; Retired = $true }
)

function Get-ReparseTarget($path) {
    try {
        $item = Get-Item -Force -LiteralPath $path -ErrorAction Stop
        if ($item.Attributes -match 'ReparsePoint') {
            return $item.Target
        }
        return $null
    } catch {
        return $null
    }
}

function Test-Reachable($target) {
    if ([string]::IsNullOrEmpty($target)) { return $false }
    try {
        # 目标可读（目录可列 或 文件可读）
        if (Test-Path -LiteralPath $target) { return $true }
        return $false
    } catch {
        return $false
    }
}

function Repair-Hint($mount, $target) {
    # 先 rmdir 失效 junction，再 mklink /J 重建
    return "cmd /c rmdir /q `"$mount`" && cmd /c mklink /J `"$mount`" `"$target`""
}

$results = @()

# ① 已知表校验（去重）
$seen = @{}
if (-not $SkipKnownTable) {
foreach ($k in $Known) {
    $m, $exp = $k.Mount, $k.Target
    if ($seen.ContainsKey($m)) { continue }
    $seen[$m] = $true
    $row = @{ mount = $m; expected = $exp; actual = $null; status = 'OK'; detail = ''; repair = '' }
    if ($k.Retired) {
        # 已弃用端：只探活留痕，不判异常、不计退出码
        $row.status = 'SKIP'
        $row.detail = '端已弃用（CC 2026-09-08），留痕不判异常'
        $results += $row; continue
    }
    if (-not (Test-Path -LiteralPath $m)) {
        $row.status = 'MISSING'; $row.detail = '挂载点不存在'
        $row.repair = "cmd /c mklink /J `"$m`" `"$exp`""
        $results += $row; continue
    }
    $actual = Get-ReparseTarget $m
    if ($null -eq $actual) {
        $row.status = 'MISMATCH'; $row.detail = '不是 ReparsePoint（疑似普通目录/文件）'
        $row.repair = Repair-Hint $m $exp
        $results += $row; continue
    }
    $row.actual = $actual
    if ($actual.TrimEnd('\') -ne $exp.TrimEnd('\')) {
        $row.status = 'MISMATCH'; $row.detail = "目标≠预期: $actual"
        $row.repair = Repair-Hint $m $exp
        $results += $row; continue
    }
    if (-not (Test-Reachable $actual)) {
        $row.status = 'BROKEN'; $row.detail = "目标不可达: $actual"
        $row.repair = Repair-Hint $m $exp
        $results += $row; continue
    }
    $results += $row
}
}

# ② 动态扫描：各根下所有 ReparsePoint，通用可达性校验（捕获未知 junction）
$scanRoots = @($Roots) + $HermesHome
foreach ($root in $scanRoots) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    try {
        $items = Get-ChildItem -Force -LiteralPath $root -ErrorAction SilentlyContinue |
            Where-Object { $_.Attributes -match 'ReparsePoint' }
    } catch { continue }
    foreach ($it in $items) {
        $m = $it.FullName
        if ($seen.ContainsKey($m)) { continue }
        $seen[$m] = $true
        $actual = $it.Target
        $row = @{ mount = $m; expected = '(动态发现)'; actual = $actual; status = 'OK'; detail = ''; repair = '' }
        if (-not (Test-Reachable $actual)) {
            $row.status = 'BROKEN'; $row.detail = "动态发现 junction 目标不可达: $actual"
            $row.repair = Repair-Hint $m $actual
        }
        $results += $row
    }
}

# ③ HM 端逐技能 junction（唯一逐技能挂载端；整根 junction 形态不适用）
#    判据：非 ReparsePoint 实体 = MISMATCH（端侧布置形态错）；ReparsePoint 但目标不可达 = BROKEN。
#    根不存在 = 打印 WARN「不可信」，不计异常也不静默 PASS（R247）。
$hmScanned = 0
$hmState = 'ok'
if (-not (Test-Path -LiteralPath $HermesSkillsRoot)) {
    $hmState = 'unavailable'
    Write-Output ("[WARN] HM 逐技能 junction 根不存在或不可达，本次检查不可信: {0}" -f $HermesSkillsRoot)
} else {
    $hmItems = @(Get-ChildItem -Force -LiteralPath $HermesSkillsRoot -ErrorAction SilentlyContinue)
    foreach ($it in $hmItems) {
        $hmScanned++
        if ($it.Attributes -notmatch 'ReparsePoint') {
            $results += @{ mount = $it.FullName; expected = '(HM 端要求逐技能 junction)'; actual = '(实体目录/文件)'
                           status = 'MISMATCH'; detail = '不是 ReparsePoint（HM 端布置形态错）'; repair = '' }
            continue
        }
        $t = $it.Target
        $ts = if ($t -is [array]) { $t[0] } else { $t }
        if (-not (Test-Reachable $ts)) {
            $results += @{ mount = $it.FullName; expected = '(可达技能目录)'; actual = $ts
                           status = 'BROKEN'; detail = '逐技能 junction 目标不可达（残留/退役未清）'; repair = '' }
        }
    }
    Write-Output ("[INFO] HM 逐技能 junction: 扫描 {0} 个（根: {1}）" -f $hmScanned, $HermesSkillsRoot)
}

# 汇总输出（SKIP = 已弃用端留痕，不计异常）
$bad = $results | Where-Object { $_.status -ne 'OK' -and $_.status -ne 'SKIP' }
$skipped = $results | Where-Object { $_.status -eq 'SKIP' }
if ($Json) {
    $out = @{ schema = 'fenjue-junction-check-v1'; total = $results.Count;
              broken = ($bad | Measure-Object).Count; junctions = $results;
              hm = @{ state = $hmState; scanned = $hmScanned; root = $HermesSkillsRoot } }
    $out | ConvertTo-Json -Depth 4 -Compress | Write-Output
} else {
    Write-Output "===== 焚诀 junction 断裂探活 ====="
    foreach ($r in $results) {
        $flag = if ($r.status -eq 'OK') { 'OK  ' } elseif ($r.status -eq 'SKIP') { 'SKIP' } else { 'FAIL' }
        $detailStr = ''
        if ($r.detail) { $detailStr = "`n      说明: " + $r.detail }
        Write-Output ("[{0}] {1}`n      预期={2} 实际={3}{4}" -f
            $flag, $r.mount, $r.expected, $r.actual, $detailStr)
        if ($r.repair) { Write-Output ("      修复: " + $r.repair) }
    }
    Write-Output ("`n总计 {0} 个 junction，异常 {1} 个，弃用留痕(SKIP) {2} 个" -f $results.Count, ($bad | Measure-Object).Count, ($skipped | Measure-Object).Count)
}

exit $(if ($bad) { 1 } else { 0 })
