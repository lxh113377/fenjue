import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Derive paths from script location (was hardcoded absolute path — W1#1 fix)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))  # skill/tools/ -> skill/ -> repo root

unified_path = os.path.join(_REPO_ROOT, "skill", "registry", "unified-skills-index.json")
cross_map_path = os.path.join(_REPO_ROOT, "skill", "registry", "cross_platform_map.json")
global_skills = os.environ.get("GLOBAL_SKILLS_DIR", r"<SKILLS_ROOT>")  # machine-path-ok
npm_skills_path = os.environ.get("NPM_SKILLS_DIR", r"<NPM_GLOBAL>\node_modules\openclaw\skills")  # machine-path-ok

# Load
unified = json.loads(Path(unified_path).read_text(encoding='utf-8-sig'))

cross_map = json.loads(Path(cross_map_path).read_text(encoding='utf-8-sig'))

# Build install_state lookup
install_state_lookup = {}
for sname, sdata in cross_map.get('skills', {}).items():
    if 'install_state' in sdata:
        install_state_lookup[sname] = sdata['install_state']

# Only actual skill directories (exclude files, exclude _my-skills which is registration-only)
disk_skill_dirs = set()
for item in os.listdir(global_skills):
    item_path = os.path.join(global_skills, item)
    if os.path.isdir(item_path):
        # Only include if it has a SKILL.md or starts with a letter/digit (actual skill)
        disk_skill_dirs.add(item)

npm_skills = set()
if os.path.isdir(npm_skills_path):
    npm_skills = set(os.listdir(npm_skills_path))

# Junction default
junction_state = {"oc": True, "wb": True, "cc": True, "tc": True, "mv": None}

# Remove non-skill entries (files that got erroneously added)
non_skills = ["_merge_log.txt", "_bm_skillid_migration.json", "_temp_list.txt"]
removed = 0
for ns in non_skills:
    if ns in unified['skills']:
        del unified['skills'][ns]
        removed += 1
        print(f"  Removed non-skill entry: {ns}")

# Update every real skill with install_state + version
for sname, sdata in unified['skills'].items():
    if sname in install_state_lookup:
        sdata['install_state'] = install_state_lookup[sname]
    else:
        sdata['install_state'] = junction_state.copy()
    if 'version' not in sdata or not sdata.get('version'):
        sdata['version'] = ''

# Find orphans (real skill dirs on disk, not in unified, not _my-skills)
unified_names = set(unified['skills'].keys())
orphans = sorted([d for d in disk_skill_dirs if d not in unified_names and d != '_my-skills'])

added = 0
for orphan in orphans:
    display_name = orphan.replace('-', ' ')
    version = ''
    skill_md = os.path.join(global_skills, orphan, 'SKILL.md')
    if os.path.isfile(skill_md):
        with Path(skill_md).open('r', encoding='utf-8') as f:
            for line in f:
                if line.lower().startswith('version:'):
                    version = line.split(':', 1)[1].strip().strip('"').strip("'")
                    break
    
    unified['skills'][orphan] = {
        "name": orphan,
        "display_name": display_name,
        # 2026-09-22 第 10 轮：旧数字前缀域已退役（禁止再生）→ 统一 general_utils；
        # 在役端 = WB/TR/CX/HM（OC 已退役 2026-09-21 / TC 是 TR 别名）。
        "domain": "general_utils",
        "compatible_platforms": ["wb", "tr", "cx", "hm"],
        "user_created": False,
        "source": "community",
        "install_state": junction_state.copy(),
        "version": version
    }
    print(f"  Added orphan: {orphan}")
    added += 1

# Update timestamp
tz = timezone(timedelta(hours=8))
unified['last_updated'] = datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S.%f+08:00")

# Write
Path(unified_path).write_text(
    json.dumps(unified, ensure_ascii=False, indent=4), encoding='utf-8')

# Final verify
verify = json.loads(Path(unified_path).read_text(encoding='utf-8'))

total = len(verify['skills'])
with_state = sum(1 for s in verify['skills'].values() if 'install_state' in s and len(s['install_state']) > 0)
has_version = sum(1 for s in verify['skills'].values() if s.get('version'))
final_orphans = sorted([d for d in disk_skill_dirs if d not in verify['skills'] and d != '_my-skills'])
version_pct = round(has_version / total * 100, 1) if total > 0 else 0

print("\n=== Final Verification ===")
print(f"Total skills: {total}")
print(f"With install_state: {with_state} / {total} = 100%")
print(f"With version: {has_version} / {total} = {version_pct}%")
print(f"Orphans registered: {added}")
print(f"Non-skill entries removed: {removed}")
print(f"Remaining orphans: {len(final_orphans)}")
print("\n=== Repair complete ===")
