# D11: 经验反哺审计
$lessonsPath = '<USER_HOME>\Desktop\workspace\焚诀\skill\LESSONS.md'

if (Test-Path $lessonsPath) {
    $content = Get-Content $lessonsPath -Raw -Encoding UTF8
    $size = [math]::Round((Get-Item $lessonsPath).Length/1KB, 1)
    Write-Host "LESSONS.md: $size KB"

    # Check for R4 lessons section
    $hasR4 = $content -match '2026-07-10.*R4|R4.*2026-07-10'
    Write-Host "R4 lessons: $hasR4"

    # Check for structured sections
    $hasOCLesson = $content -match 'OC.*误解|OC.*misunderstand|OC.*mistake'
    $hasVersionLesson = $content -match 'version.*覆盖率|version.*coverage'
    $hasFixRecord = $content -match '修复|fix|操作清单'
    $hasLessonsLearned = $content -match '教训|lesson|经验'

    Write-Host "OC misinterpretation note: $hasOCLesson"
    Write-Host "Version coverage note: $hasVersionLesson"
    Write-Host "Fix records: $hasFixRecord"
    Write-Host "Lessons learned: $hasLessonsLearned"

    # Check if content is substantive (not just placeholder)
    $lineCount = (Get-Content $lessonsPath | Where-Object { $_.Trim().Length -gt 20 } | Measure-Object).Count
    Write-Host "Substantive lines (>20 chars): $lineCount"

    $score = 0
    if ($hasR4) { $score += 1 }
    if ($lineCount -ge 10) { $score += 1 }

    Write-Host ""
    Write-Host "D11 Score: $score/2"
} else {
    Write-Host "LESSONS.md: MISSING"
    Write-Host "D11 Score: 0/2"
}
