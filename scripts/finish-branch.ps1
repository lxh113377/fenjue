#!/usr/bin/env pwsh
<#
finish-branch.ps1 — 分支收尾可执行脚本（deliverables/finish-branch.md 的同构实现）
流程：验测试 → 探环境 → 定基线 → 三选一菜单 → 执行 → 清理。集成决策权在人。
用法：
  pwsh scripts/finish-branch.ps1 [-Base <基线分支>] [-TestCommand <测试命令>]
  非交互环境（CI）只跑探环境：pwsh scripts/finish-branch.ps1 -ProbeOnly
退出码：0 收尾完成或保持原样；1 测试红/合并红/用户中断；2 用法错误。
注：输出点 ≤25（noise_guard F6 门禁上限），合并多行输出为单次 Write-Output。
#>
param(
    [string]$Base = "",
    [string]$TestCommand = "",
    [switch]$ProbeOnly
)

$ErrorActionPreference = "Stop"

function Invoke-Git($Arguments) {
    $out = & git @Arguments 2>&1
    return @{ Code = $LASTEXITCODE; Out = ($out | Out-String).Trim() }
}

function Get-WorktreeState {
    $gitDir = (Invoke-Git @("rev-parse", "--git-dir")).Out
    $gitCommon = (Invoke-Git @("rev-parse", "--git-common-dir")).Out
    $top = (Invoke-Git @("rev-parse", "--show-toplevel")).Out
    $super = (Invoke-Git @("rev-parse", "--show-superproject-working-tree")).Out
    $branch = (Invoke-Git @("branch", "--show-current")).Out
    $inSubmodule = -not [string]::IsNullOrWhiteSpace($super)
    return @{
        GitDir = $gitDir; GitCommon = $gitCommon; Top = $top; Branch = $branch
        IsWorktree = ($gitDir -ne $gitCommon) -and (-not $inSubmodule)
        Detached = [string]::IsNullOrWhiteSpace($branch)
    }
}

function Get-DefaultTestCommand($ProjectRoot) {
    if ($TestCommand) { return $TestCommand }
    if (Test-Path (Join-Path $ProjectRoot "package.json")) { return "npm test" }
    if (Test-Path (Join-Path $ProjectRoot "go.mod")) { return "go test ./..." }
    if (Test-Path (Join-Path $ProjectRoot "pom.xml")) { return "mvn -q test" }
    return "python -m pytest -q"
}

function Invoke-Tests($Command, $WorkDir) {
    $p = Start-Process -FilePath "pwsh" -ArgumentList @("-NoProfile", "-Command", $Command) `
        -WorkingDirectory $WorkDir -Wait -PassThru -NoNewWindow
    return $p.ExitCode
}

function Get-MainRoot($State) {
    if (-not $State.IsWorktree) { return $State.Top }
    $r = Invoke-Git @("-C", (Join-Path $State.GitCommon ".."), "rev-parse", "--show-toplevel")
    if ($r.Code -eq 0) { return $r.Out }
    return (Split-Path -Parent $State.GitCommon)
}

function Clear-Worktree($State) {
    if (-not $State.IsWorktree) { return 0 }
    $p = $State.Top
    $owned = ($p -match "[\\/]\.worktrees([\\/]|$)") -or ($p -match "[\\/]worktrees([\\/]|$)")
    if (-not $owned) { return 0 }
    if ((Invoke-Git @("worktree", "remove", $p)).Code -eq 0) {
        Invoke-Git @("worktree", "prune") | Out-Null
        return 0
    }
    $st = Invoke-Git @("-C", $p, "status", "--porcelain", "-uall")
    Write-Output ("[finish] 删被拒（禁--force，有未提交内容）：`n{0}`n1.提交进分支后清理 / 2.搬回主仓 / 3.删除（不可恢复，二次确认delete）" -f $st.Out)
    $pick = (Read-Host "请选择 1/2/3").Trim()
    if ($pick -eq "1") {
        if ((Invoke-Git @("-C", $p, "add", "-A")).Code -ne 0) { return 1 }
        $m = Read-Host "提交说明"
        if ((Invoke-Git @("-C", $p, "commit", "-m", $m)).Code -ne 0) { return 1 }
    } elseif ($pick -eq "3") {
        if ((Read-Host "输入 'delete' 确认永久删除").Trim() -cne "delete") { return 1 }
    } else {
        return 1
    }
    if ((Invoke-Git @("worktree", "remove", $p)).Code -ne 0) { return 1 }
    Invoke-Git @("worktree", "prune") | Out-Null
    return 0
}

# ── 主流程 ──
$st = Get-WorktreeState
$br = if ($st.Branch) { $st.Branch } else { "(detached)" }
Write-Output ("我正在用 finish-branch 收尾当前分支。分支={0} worktree={1} detached={2} 路径={3}" -f $br, $st.IsWorktree, $st.Detached, $st.Top)
if ($ProbeOnly) { exit 0 }

$testCmd = Get-DefaultTestCommand $st.Top
if ((Invoke-Tests $testCmd $st.Top) -ne 0) { Write-Output "[finish] 测试红，先修再收尾。停止。"; exit 1 }

if ([string]::IsNullOrWhiteSpace($Base)) {
    $up = Invoke-Git @("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    $guess = ""
    if ($up.Code -eq 0) { $guess = ($up.Out -split "/", 2)[-1] }
    if ([string]::IsNullOrWhiteSpace($guess)) {
        if ((Invoke-Git @("show-ref", "--verify", "--quiet", "refs/heads/master")).Code -eq 0) { $guess = "master" }
        else { $guess = "main" }
    }
    $ans = (Read-Host ("分支从 [{0}] 切出，对吗？(Y/n)" -f $guess)).Trim()
    if ($ans -match "^[nN]") {
        $Base = (Read-Host "请输入正确基线分支").Trim()
        if ([string]::IsNullOrWhiteSpace($Base)) { exit 2 }
    } else {
        $Base = $guess
    }
}

if ($st.Detached) {
    Write-Output "实现完成（detached HEAD，外部托管工作区）。`n1. 推送为新分支并建 Pull Request`n2. 保持原样（稍后我自己处理）"
} else {
    Write-Output ("实现完成。怎么处理？（基线 {0}）`n1. 本地合并回基线`n2. 推送并建 Pull Request`n3. 保持原样（稍后我自己处理）" -f $Base)
}
$choice = (Read-Host "请选择").Trim()

if ($choice -eq "discard") {
    $commits = (Invoke-Git @("log", "--oneline", ("{0}..HEAD" -f $Base))).Out
    Write-Output ("将永久删除：分支={0} / 工作区={1}`n提交：{2}`n输入 'discard' 确认：" -f $br, $st.Top, $commits)
    if ((Read-Host "确认").Trim() -cne "discard") { exit 1 }
    Set-Location -LiteralPath (Get-MainRoot $st)
    if ((Clear-Worktree $st) -ne 0) { exit 1 }
    if (-not $st.Detached) { Invoke-Git @("branch", "-D", $st.Branch) | Out-Null }
    exit 0
}

if ($choice -eq "1" -and (-not $st.Detached)) {
    $mainRoot = Get-MainRoot $st
    Set-Location -LiteralPath $mainRoot
    if ((Invoke-Git @("checkout", $Base)).Code -ne 0) { exit 1 }
    if ((Invoke-Git @("pull")).Code -ne 0) { Write-Output "[finish] pull 失败，先解远端分歧再重跑。"; exit 1 }
    if ((Invoke-Git @("merge", "--no-ff", $st.Branch)).Code -ne 0) { Write-Output "[finish] 合并冲突，停在原地解冲突。"; exit 1 }
    if ((Invoke-Tests $testCmd $mainRoot) -ne 0) { Write-Output "[finish] 合后测试红：分支与worktree原位保留，排查后再收尾。"; exit 1 }
    if ((Clear-Worktree $st) -ne 0) { exit 1 }
    Invoke-Git @("branch", "-d", $st.Branch) | Out-Null
    Write-Output ("[finish] 已合并入 {0} 并清理。" -f $Base)
    exit 0
} elseif ($choice -eq "2") {
    if ($st.Detached) {
        $nb = (Read-Host "新分支名").Trim()
        if ([string]::IsNullOrWhiteSpace($nb)) { exit 2 }
        if ((Invoke-Git @("push", "origin", ("HEAD:refs/heads/{0}" -f $nb))).Code -ne 0) { Write-Output "[finish] push 被拒，先查远端（禁自行force-push）。"; exit 1 }
    } else {
        if ((Invoke-Git @("push", "-u", "origin", $st.Branch)).Code -ne 0) { Write-Output "[finish] push 被拒，先查远端（禁自行force-push）。"; exit 1 }
    }
    Write-Output "[finish] 已推送，按仓库模板建PR后回URL。worktree 保留供改PR反馈。"
    exit 0
} elseif (($choice -eq "3") -or ($st.Detached -and ($choice -eq "2"))) {
    Write-Output ("[finish] 保持原样。分支={0}，工作区保留于 {1}。" -f $br, $st.Top)
    exit 0
} else {
    exit 2
}
