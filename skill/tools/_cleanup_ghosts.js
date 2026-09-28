/**
 * ⚠️ DEPRECATED — 2026-07-05 标记
 * 
 * 此脚本已作废！原因：
 * 1. 引用的 7 个幽灵条目（chat-analyzer, pyautogui-automation, 5个skill_*）
 *    已在先前的清理中全部从注册表移除
 * 2. QC 数据已更新为 QoderWork CN（junction 互通）
 * 3. cross_platform_map 中的 qc install_state 统一修正已在计划中
 *
 * 执行此脚本不会有任何效果（目标条目不存在）。
 * 保留此文件不移除，等辉哥确认后删除。
 * 
 * 如需清理操作，请使用 sync/sync-skills-bridge.ps1 -Force
 *   它会自动检测新增并写入注册表，检测缺失则报告差异。
 */

// 原脚本内容保留不动（已无实际效果）

const fs = require('fs');
const path = require('path');

const REGISTRY_DIR = path.resolve(__dirname, '..', 'registry');
const UNIFIED_PATH = path.join(REGISTRY_DIR, 'unified-skills-index.json');
const CROSS_MAP_PATH = path.join(REGISTRY_DIR, 'cross_platform_map.json');
const SYNC_SCRIPT_PATH = path.resolve(__dirname, '..', 'sync', 'sync-skills-bridge.ps1');

// Ghost entries to DELETE
const GHOSTS_TO_DELETE = [
    'chat-analyzer',                     // community, no disk
    'pyautogui-automation',              // community, no disk
    'skill_2053082396193849344',         // user_created, no disk (minimax-docx)
    'skill_2053082401071824896',         // user_created, no disk (minimax-xlsx)
    'skill_2053082401866706944',         // user_created, no disk (minimax-pdf)
    'skill_2053082488497897472',         // user_created, no disk (nuwa-skill)
    'skill_2053083681353162752',         // user_created, no disk (yourself-skill)
];

// === 1. Strip BOM ===
function stripBOM(content) {
    if (content.charCodeAt(0) === 0xFEFF) return content.slice(1);
    return content;
}

// === 2. Update unified-skills-index.json ===
console.log('[1/4] Cleaning unified-skills-index.json...');
const unified = JSON.parse(stripBOM(fs.readFileSync(UNIFIED_PATH, 'utf-8')));

let removedFromUnified = 0;
for (const name of GHOSTS_TO_DELETE) {
    if (unified.skills[name]) {
        delete unified.skills[name];
        console.log(`  REMOVED: ${name}`);
        removedFromUnified++;
    } else {
        console.log(`  SKIP: ${name} (not found)`);
    }
}

// Update the unified index version
unified.last_updated = new Date().toISOString();
unified.version = '1.3';
fs.writeFileSync(UNIFIED_PATH, JSON.stringify(unified, null, 4), 'utf-8');
console.log(`  unified-skills-index.json: removed ${removedFromUnified} entries, version -> 1.3`);

// === 3. Update cross_platform_map.json ===
console.log('\n[2/4] Cleaning cross_platform_map.json...');
const crossMap = JSON.parse(stripBOM(fs.readFileSync(CROSS_MAP_PATH, 'utf-8')));

// Remove ghost entries from skills
let removedFromMap = 0;
for (const name of GHOSTS_TO_DELETE) {
    if (crossMap.skills[name]) {
        delete crossMap.skills[name];
        console.log(`  REMOVED from skills: ${name}`);
        removedFromMap++;
    }
}

// Remove QC platform data
console.log('\n  QC platform cleanup:');
delete crossMap.platforms.qc;
delete crossMap.cross_platform_mapping.equivalents;
delete crossMap.cross_platform_mapping.qc_only_skills;
console.log('  Removed: platforms.qc, cross_platform_mapping.equivalents, cross_platform_mapping.qc_only_skills');

// Update oc_only_skills list (recalculate from installed skills)
const junctionSkills = Object.entries(crossMap.skills)
    .filter(([_, v]) => v.install_state?.oc === true)
    .map(([k, _]) => k)
    .filter(s => !s.startsWith('_my-') && s !== '_my-skills' && !s.startsWith('skill_'))
    .sort();

crossMap.cross_platform_mapping.oc_only_skills = junctionSkills;
console.log(`  Updated oc_only_skills: ${junctionSkills.length} skills`);

crossMap.last_updated = new Date().toISOString();
fs.writeFileSync(CROSS_MAP_PATH, JSON.stringify(crossMap, null, 4), 'utf-8');
console.log(`  cross_platform_map.json: removed ${removedFromMap} entries, QC data cleaned`);

// === 4. Update sync script to remove QC scanning ===
console.log('\n[3/4] Updating sync-skills-bridge.ps1...');
let syncScript = fs.readFileSync(SYNC_SCRIPT_PATH, 'utf-8');

// Comment out QC scanning section
syncScript = syncScript.replace(
    /\$qcSkills = Get-DirectorySkills \$QCSkillsPath \| Sort-Object/,
    '$qcSkills = @()  # [QC REMOVED] QClaw was uninstalled'
);

syncScript = syncScript.replace(
    /Write-Status "OK" \("QC 独立 skills: \{0\} 个skill" -f \$qcSkills\.Count\)/,
    'Write-Status "INFO" "QC 已卸载，跳过扫描"'
);

// Remove Step 4 and Step 5d (QC analysis and QC sync)
// Replace Step 4 section
const step4Pattern = /Write-Section "Step 4: QC 平台技能分析"[\s\S]*?Write-Section "Step 4b: Marvis 平台概览"/;
syncScript = syncScript.replace(step4Pattern, 'Write-Section "Step 4: QC 平台技能分析"\nWrite-Status "INFO" "QC 已卸载，跳过扫描"\n\nWrite-Section "Step 4b: Marvis 平台概览"');

// Replace Step 5d section
const step5dPattern = /Write-Section "Step 5d: 同步 QC 安装状态[\s\S]*?Write-Status "OK" \("QC 安装状态同步完成/;
const step5dReplacement = `Write-Section "Step 5d: QC 安装状态同步"
Write-Status "INFO" "QC 已卸载，跳过同步"`;
syncScript = syncScript.replace(step5dPattern, step5dReplacement);

// Remove QC-related configuration variables and KnownMapTable entries
// Remove $QCSkillsPath line
syncScript = syncScript.replace(
    /\$QCSkillsPath = "<USER_HOME>\\.qclaw\\skills"/,
    '# $QCSkillsPath = "<USER_HOME>\\.qclaw\\skills"  # QClaw was uninstalled'
);

fs.writeFileSync(SYNC_SCRIPT_PATH, syncScript, 'utf-8');
console.log('  sync-skills-bridge.ps1 updated: QC scanning removed');

// === 5. Regenerate platform JSONs ===
console.log('\n[4/4] Regenerating platform JSONs...');
const platformKeys = ['oc', 'wb', 'cc', 'tc', 'qc', 'mv'];

for (const key of platformKeys) {
    const platformInfo = crossMap.platforms[key];
    if (!platformInfo) {
        console.log(`  SKIP platform-${key}.json (no platform config)`);
        continue;
    }

    const platformSkills = Object.entries(crossMap.skills)
        .filter(([_, v]) => v.install_state?.[key] === true)
        .map(([k, _]) => k)
        .sort();

    const userCreatedSkills = Object.entries(crossMap.skills)
        .filter(([k, v]) => v.install_state?.[key] === true && unified.skills[k]?.user_created)
        .map(([k, _]) => k)
        .sort();

    const platformDoc = {
        schema_version: '1.0',
        last_updated: crossMap.last_updated,
        platform: key,
        platform_name: platformInfo.name,
        skills_count: platformSkills.length,
        user_created_count: userCreatedSkills.length,
        skills_list: platformSkills,
        user_created_skills: userCreatedSkills,
        sync_type: platformInfo.sync_type,
        note: '安装状态来自 cross_platform_map.json，元数据来自 unified-skills-index.json'
    };

    const platformPath = path.join(REGISTRY_DIR, `platform-${key}.json`);
    fs.writeFileSync(platformPath, JSON.stringify(platformDoc, null, 4), 'utf-8');
    console.log(`  platform-${key}.json: ${platformSkills.length} skills`);
}

// === Summary ===
console.log('\n============================================');
console.log(' Ghost Cleanup Complete');
console.log('============================================');
console.log(`Removed from unified index:   ${removedFromUnified}`);
console.log(`Removed from cross_platform:  ${removedFromMap}`);
console.log(`QC platform data:             cleared`);
console.log(`Platform JSONs regenerated:   ${platformKeys.length}`);

const finalCount = Object.keys(unified.skills).length;
console.log(`\nRegistry now has: ${finalCount} skills`);
console.log(`(matches <SKILLS_ROOT>: ${finalCount === 68 ? '✅' : '❌'})`);
