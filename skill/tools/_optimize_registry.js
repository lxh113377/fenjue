/**
 * 锋(Feng) — Registry Optimization v1.0
 * 2026-07-05
 * 
 * 自动执行：新增 skill → 写入注册表（无需审批）
 * 需审批：删除/清理（报告差异）
 */

const fs = require('fs');
const path = require('path');

const REGISTRY_DIR = path.resolve(__dirname, 'registry');
const UNIFIED_PATH = path.join(REGISTRY_DIR, 'unified-skills-index.json');
const CROSS_MAP_PATH = path.join(REGISTRY_DIR, 'cross_platform_map.json');
const GLOBAL_SKILLS_DIR = '<SKILLS_ROOT>';

const FORCE = process.argv.includes('--force');
const REPORT_ONLY = process.argv.includes('--report');

// === Domain Classification ===
// 2026-09-22 第 10 轮：原实现返回旧数字前缀域（01-memory-knowledge / 06-frontend-ui /
// 09-dev-tools 等 16 域体系，2026-08-16 已软删除）。按 build_registry._infer_domain 的明令
// 「禁止再生成」，此处**去掉整套名前映射**，统一落 general_utils；
// 真实域判定唯一权威 = eval/build_registry.py → domain_classifier.classify_domain。
function getSkillDomain(name) {
    return 'general_utils';
}

// === Main ===
function stripBOM(content) {
    if (content.charCodeAt(0) === 0xFEFF || content.charCodeAt(0) === 0xEFBBBF) {
        return content.slice(1);
    }
    return content;
}

function main() {
    console.log('============================================');
    console.log(' 锋(Feng) - Registry Optimization v1.0     ');
    console.log('============================================\n');

    // Load unified index
    const unified = JSON.parse(stripBOM(fs.readFileSync(UNIFIED_PATH, 'utf-8')));
    const crossMap = JSON.parse(stripBOM(fs.readFileSync(CROSS_MAP_PATH, 'utf-8')));

    // Scan global skills
    const globalSkills = fs.readdirSync(GLOBAL_SKILLS_DIR, { withFileTypes: true })
        .filter(d => d.isDirectory())
        .map(d => d.name)
        .sort();

    const registryNames = Object.keys(unified.skills).sort();

    console.log(`Registry skills: ${registryNames.length}`);
    console.log(`Global skills:   ${globalSkills.length}\n`);

    // === Find differences ===
    const toAdd = globalSkills.filter(s => !registryNames.includes(s)).sort();
    const orphaned = registryNames.filter(s => !globalSkills.includes(s)).sort();

    const orphanedUserCreated = orphaned.filter(s => unified.skills[s]?.user_created);
    const orphanedCommunity = orphaned.filter(s => !unified.skills[s]?.user_created);

    console.log(`[TO ADD] Missing from registry: ${toAdd.length}`);
    console.log(`[ORPHANED] In registry, not on disk: ${orphaned.length}`);
    console.log(`  - User-created (sensitive): ${orphanedUserCreated.length}`);
    orphanedUserCreated.forEach(s => console.log(`    ${s}`));
    console.log(`  - Community (safe to clean): ${orphanedCommunity.length}`);
    orphanedCommunity.forEach(s => console.log(`    ${s}`));

    if (REPORT_ONLY) {
        console.log('\nReport-only mode. No changes made.');
        console.log('Run with --force to apply additions.');
        return;
    }

    if (!FORCE) {
        console.log('\nDry run. Run with --force to apply.');
        return;
    }

    // === Phase 4: Update unified-skills-index.json ===
    console.log('\n[Phase A] Updating unified-skills-index.json...');
    let addedCount = 0;

    for (const skillName of toAdd) {
        if (unified.skills[skillName]) {
            console.log(`  SKIP ${skillName} (exists)`);
            continue;
        }

        const isUserCreated = skillName === '_my-skills';
        const source = isUserCreated ? 'user-created' : 'community';
        const domain = getSkillDomain(skillName);

        unified.skills[skillName] = {
            name: skillName,
            display_name: skillName.replace(/-/g, ' '),
            domain: domain,
            compatible_platforms: ['oc', 'wb', 'cc', 'tc'],
            source: source,
            user_created: isUserCreated
        };

        console.log(`  ADD ${skillName} -> ${domain} [${source}]`);
        addedCount++;
    }

    unified.last_updated = new Date().toISOString();
    fs.writeFileSync(UNIFIED_PATH, JSON.stringify(unified, null, 4), 'utf-8');
    console.log(`\n  unified-skills-index.json updated (${addedCount} new)`);

    // === Phase 5: Update cross_platform_map.json ===
    console.log('\n[Phase B] Updating cross_platform_map.json install states...');
    let mapAdded = 0;

    for (const skillName of toAdd) {
        if (crossMap.skills[skillName]) {
            console.log(`  SKIP ${skillName} (exists in map)`);
            continue;
        }

        crossMap.skills[skillName] = {
            name: skillName,
            qc_equivalent: null,
            install_state: { oc: true, wb: true, cc: true, tc: true, qc: false, mv: null }
        };
        console.log(`  ADD ${skillName} -> install_state`);
        mapAdded++;
    }

    // Fix cross_platform_map oc_only_skills list
    const junctionSkills = Object.entries(crossMap.skills)
        .filter(([_, v]) => v.install_state?.oc === true)
        .map(([k, _]) => k);

    crossMap.cross_platform_mapping.oc_only_skills = junctionSkills.filter(
        s => !s.startsWith('skill_') && s !== '_my-skills'
    ).sort();

    crossMap.last_updated = new Date().toISOString();
    fs.writeFileSync(CROSS_MAP_PATH, JSON.stringify(crossMap, null, 4), 'utf-8');
    console.log(`\n  cross_platform_map.json updated (${mapAdded} new, oc_only_skills refreshed)`);

    // === Summary ===
    console.log('\n============================================');
    console.log(' Summary');
    console.log('============================================');
    console.log(`✅ Auto-added: ${addedCount} skills to registry\n`);

    if (orphanedUserCreated.length > 0) {
        console.log('⚠️  PENDING APPROVAL (orphaned user-created skills):');
        console.log('   These exist in registry but NOT on disk:');
        orphanedUserCreated.forEach(s => console.log(`    - ${s} (${unified.skills[s]?.display_name || 'unknown'})`));
        console.log('');
    }

    if (orphanedCommunity.length > 0) {
        console.log('⚠️  PENDING APPROVAL (orphaned community skills):');
        orphanedCommunity.forEach(s => console.log(`    - ${s}`));
        console.log('');
    }

    console.log('QC platform: Path <USER_HOME>\\.qclaw\\skills does NOT exist.');
    console.log('All QC platform data in registry is stale/dead.');
    console.log('\nNext: Run sync-skills-bridge.ps1 -Force to regenerate platform-*.json');
}

main();
