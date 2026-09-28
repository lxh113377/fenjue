"""hardcoded_count_check.py — 注册表硬编码计数漂移检查（可复现计分脚本）。

背景（2026-09-08 R219 任务2）：
    注册表 JSON 中的 skills_count / user_created_count / count 等「计数字段」
    由 build_registry.py 等脚本动态生成，但本质是快照——若有人手工增删
    skills_list 而不重跑脚本，计数字段会静默过期。
    本脚本把「是否存在硬编码数字漂移」变成可机检项：逐文件比对
    「声明计数 vs 实际数据长度」，不一致即漂移。

口径：
    - platform-*.json : skills_count == len(skills_list)
                        user_created_count == len(user_created_skills)
    - disk_manifest.json : count == len(skills)
    - skill_content 域桶 : sum(len(skills)) == len(skill_ids.json)
    - 字段缺失 = 该文件已动态化/无此口径 → 跳过，不算漂移
      （D-109 收紧：**只有声明计数而清单缺失**不算「已动态化」——计数失去对照物即自由数字，
        按漂移记账；只有清单没有计数才是真动态化）

输出：JSON 到 stdout（供 scorecard_sync.py 消费），exit 0 = 无漂移，exit 1 = 有漂移。
用法：python eval/hardcoded_count_check.py [--json]
"""
import glob
import json
import os
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)
from config import PROJECT_DIR, SKILL_CONTENT  # noqa: E402

REGISTRY_DIR = os.path.join(PROJECT_DIR, 'skill', 'registry')


def check_platform_file(path):
    """platform-*.json：声明计数 vs skills_list 实长。"""
    drift = []
    with open(path, encoding='utf-8-sig') as f:
        d = json.load(f)
    pairs = [
        ('skills_count', 'skills_list'),
        ('user_created_count', 'user_created_skills'),
    ]
    for count_key, list_key in pairs:
        if count_key not in d and list_key not in d:
            continue  # 两边都没有 = 该口径已动态化，跳过
        if count_key in d and list_key not in d:
            # D-109：只有声明计数、没有清单 ⇒ 无从对账。旧实现把它和"已动态化"混为一谈直接跳过，
            # 于是「删掉 skills_list 只留 skills_count」可以静默过关——计数一旦没有对照物，
            # 它就是自由数字。现按漂移记账（actual=None 可诊断）。
            drift.append({'file': os.path.basename(path), 'field': count_key,
                          'declared': d[count_key], 'actual': None,
                          'why': '有声明计数但清单缺失，无从对账'})
            continue
        if count_key not in d:
            continue  # 只有清单没计数：本就是动态化的正常态
        declared, actual = d[count_key], len(d[list_key])
        if declared != actual:
            drift.append({'file': os.path.basename(path),
                          'field': count_key, 'declared': declared, 'actual': actual})
    return drift, 1


def check_disk_manifest(path):
    with open(path, encoding='utf-8-sig') as f:
        d = json.load(f)
    if 'count' not in d or 'skills' not in d:
        return [], 0
    declared, actual = d['count'], len(d['skills'])
    if declared != actual:
        return [{'file': os.path.basename(path), 'field': 'count',
                 'declared': declared, 'actual': actual}], 1
    return [], 1


def check_skill_content():
    """skill_content 域桶总数 vs skill_ids.json 注册表数。"""
    ids_path = os.path.join(SKILL_CONTENT, 'skill_ids.json')
    if not os.path.isfile(ids_path):
        return [], 0
    with open(ids_path, encoding='utf-8') as f:
        reg_n = len(json.load(f))
    total = 0
    for fp in glob.glob(os.path.join(SKILL_CONTENT, '*.json')):
        if os.path.basename(fp) in ('skill_ids.json', 'index_manifest.json'):
            continue
        try:
            with open(fp, encoding='utf-8') as _f:
                total += len(json.load(_f).get('skills', []))
        except Exception:
            continue
    if total != reg_n:
        return [{'file': 'skill_content/*.json', 'field': 'total_skills',
                 'declared': reg_n, 'actual': total}], 1
    return [], 1


def main():
    drift, checked = [], 0
    for fp in sorted(glob.glob(os.path.join(REGISTRY_DIR, 'platform-*.json'))):
        d, n = check_platform_file(fp)
        drift += d
        checked += n
    dm = os.path.join(REGISTRY_DIR, 'disk_manifest.json')
    if os.path.isfile(dm):
        d, n = check_disk_manifest(dm)
        drift += d
        checked += n
    d, n = check_skill_content()
    drift += d
    checked += n

    result = {
        'check': 'hardcoded_count_drift',
        'ok': not drift,
        'checked': checked,
        'drift_count': len(drift),
        'drift': drift,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not drift else 1


if __name__ == '__main__':
    sys.exit(main())
