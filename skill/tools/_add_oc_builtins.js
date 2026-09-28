const fs = require('fs');
const path = require('path');

const REG_DIR = '<USER_HOME>\\Desktop\\焚诀\\skill\\registry';
const UNI = path.join(REG_DIR, 'unified-skills-index.json');
const CROSS = path.join(REG_DIR, 'cross_platform_map.json');
const NPM_SKILLS = '<NPM_GLOBAL>\\node_modules\\openclaw\\skills';

function stripBOM(s) { return s.charCodeAt(0) === 0xFEFF ? s.slice(1) : s; }

const unified = JSON.parse(stripBOM(fs.readFileSync(UNI, 'utf-8')));
const crossMap = JSON.parse(stripBOM(fs.readFileSync(CROSS, 'utf-8')));

const npmDirs = fs.readdirSync(NPM_SKILLS, { withFileTypes: true })
    .filter(d => d.isDirectory()).map(d => d.name);

const existing = Object.keys(unified.skills);
const toAdd = npmDirs.filter(s => !existing.includes(s));

console.log('New skills to register: ' + toAdd.length);

// Domain classification
// 2026-09-22 第 10 轮：原实现硬编码旧数字前缀域（09-dev-tools / 06-frontend-ui /
// 02-skill-ecosystem，2026-08-16 已软删除）。按 build_registry._infer_domain 的明令「禁止再生成」，
// 此处**去掉整套名→域映射**，统一落 general_utils；
// 真实域判定唯一权威 = eval/build_registry.py → domain_classifier.classify_domain。
function getDomain(name) {
    return 'general_utils';
}

// Update unified index
let added = 0;
for (const name of toAdd) {
    const domain = getDomain(name);
    unified.skills[name] = {
        name: name,
        display_name: name.replace(/-/g, ' '),
        domain: domain,
        compatible_platforms: ['oc', 'wb', 'cc', 'tc', 'qc'],
        source: 'community',
        user_created: false
    };
    console.log('  ADD ' + name + ' -> ' + domain);
    added++;
}

unified.last_updated = new Date().toISOString();
unified.version = '1.5';
fs.writeFileSync(UNI, JSON.stringify(unified, null, 4), 'utf-8');
console.log('unified index: +' + added);

// Update cross_platform_map
added = 0;
for (const name of toAdd) {
    if (crossMap.skills[name]) continue;
    crossMap.skills[name] = {
        name: name,
        qc_equivalent: null,
        install_state: { oc: true, wb: true, cc: true, tc: true, qc: true, mv: null }
    };
    console.log('  MAP ' + name);
    added++;
}

crossMap.cross_platform_mapping.oc_only_skills = Object.entries(crossMap.skills)
    .filter(([_, v]) => v.install_state?.oc === true)
    .map(([k, _]) => k)
    .filter(s => s !== '_my-skills')
    .sort();

crossMap.last_updated = new Date().toISOString();
fs.writeFileSync(CROSS, JSON.stringify(crossMap, null, 4), 'utf-8');
console.log('cross_platform_map: +' + added);
console.log('oc_only_skills: ' + crossMap.cross_platform_mapping.oc_only_skills.length);
