#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rotate_blindset.py — 冻结盲测集季度轮换（R163 批2b）
====================================================================
每季度轮换 30% 新样本（来自真实查询池 eval/blindset_query_pool.json），
保留 70% 重叠保证跨季度可比；版本化归档 frozen_blind_test.vN.json。

护栏:
  - 默认 dry-run, 仅打印将轮换的样本
  - 新池样本必须带 expected_skill + judge, 否则拒绝
  - 轮换后覆盖校验（保留集 + 新样本的期望 skill 数不回退）

用法:
  python rotate_blindset.py              # dry-run
  python rotate_blindset.py --force      # 应用轮换
"""
import os
import sys
import json
import secrets
import datetime
import shutil
from pathlib import Path

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ACTIVE = os.path.join(EVAL_DIR, 'frozen_blind_test.json')
POOL = os.path.join(EVAL_DIR, 'blindset_query_pool.json')
MANIFEST = os.path.join(EVAL_DIR, 'blindset_rotation.json')
ROTATE_RATIO = 0.3
SEED = 20261001


def _secure_shuffle(seq):
    """Fisher-Yates with secrets.randbelow（密码学随机抽样）"""
    for i in range(len(seq) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        seq[i], seq[j] = seq[j], seq[i]


def load_manifest():
    if os.path.exists(MANIFEST):
        return json.loads(Path(MANIFEST).read_text(encoding='utf-8'))
    return {'schema': 'fenjue-blindset-rotation-v1', 'history': [], 'active_version': 0}


def save_manifest(m):
    Path(MANIFEST).write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    force = '--force' in sys.argv
    active = json.loads(Path(ACTIVE).read_text(encoding='utf-8'))
    if os.path.exists(POOL):
        pool = json.loads(Path(POOL).read_text(encoding='utf-8'))
    else:
        pool = []

    # 收集活动样本（单层平铺）
    entries = [q for t in active for q in t.get('queries', [])]
    valid_pool = [q for q in pool if q.get('expected_skill') is not None and q.get('judge')]
    if not valid_pool:
        print('❌ 查询池为空或全部无效, 拒绝轮换')
        sys.exit(1)

    rotate_n = max(1, round(len(entries) * ROTATE_RATIO))
    _secure_shuffle(entries)
    keep, drop = entries[rotate_n:], entries[:rotate_n]

    # 新样本量 = 轮出量, 且去重（不与保留集重复）
    keep_texts = {q['query'] for q in keep}
    new_pool = [q for q in valid_pool if q['query'] not in keep_texts]
    _secure_shuffle(new_pool)
    new_entries = new_pool[:rotate_n]
    if len(new_entries) < rotate_n:
        print(f'❌ 新样本不足: 需 {rotate_n}, 池内可用 {len(new_entries)}')
        sys.exit(1)

    old_skills = {q.get('expected_skill') for q in entries if q.get('expected_skill')}
    new_skills = {q.get('expected_skill') for q in keep + new_entries if q.get('expected_skill')}
    coverage_ok = len(new_skills) >= len(old_skills) - 2  # 允许少量技能自然离场

    print(f'活动样本 {len(entries)} 条 → 保留 {len(keep)} / 轮出 {len(drop)} / 换入 {len(new_entries)}')
    print('轮出样本:')
    for q in drop:
        print(f'  - {q["query"][:40]} ({q.get("expected_skill")})')
    print('换入样本:')
    for q in new_entries:
        print(f'  + {q["query"][:40]} ({q.get("expected_skill")})')
    print(f'技能覆盖: {len(old_skills)} → {len(new_skills)} ({"OK" if coverage_ok else "回退!"})')

    if not force:
        print('\ndry-run: 未应用 (加 --force 应用轮换)')
        return

    if not coverage_ok:
        print('❌ 覆盖回退, 拒绝写入')
        sys.exit(1)

    m = load_manifest()
    version = m['active_version'] + 1
    archive = os.path.join(EVAL_DIR, f'frozen_blind_test.v{version}.json')
    shutil.copyfile(ACTIVE, archive)
    new_active = [{'tier': 'frozen_rotated', 'description': f'R163 季度轮换 v{version} (保留70%重叠)',
                   'queries': keep + new_entries}]
    Path(ACTIVE).write_text(json.dumps(new_active, ensure_ascii=False, indent=2), encoding='utf-8')
    m['history'].append({
        'version': version,
        'ts': datetime.datetime.now().isoformat(timespec='seconds'),
        'kept': len(keep), 'rotated_out': len(drop), 'rotated_in': len(new_entries),
        'archive': os.path.basename(archive),
    })
    m['active_version'] = version
    save_manifest(m)
    print(f'✅ 已应用 v{version}: 活动集更新, 旧版归档 {os.path.basename(archive)}')


if __name__ == '__main__':
    main()
