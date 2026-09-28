# -*- coding: utf-8 -*-
"""verify_checks.data_layer — 检查函数族（P1-16 拆包，2026-09-23）。

状态/助手经 `_root.<name>` 晚绑定（ctx 单例 = verify_truth_consistency），
monkeypatch(vtc, <state>/<check>) 契约不变。
"""
import glob
import json
import os
import re
import subprocess
import sys

import verify_truth_consistency as _root  # noqa: E402  # ctx 单例


def check_c2_bge_vs_registry(skip_external=False):
    """C2: BGE 索引 skill 集 == 注册表（集合相等 + npy 行数一致）。

    R193: BGE 三件套入库，CI 全量跑，不再 SKIP。
    """
    import numpy as np
    bge_npy = os.path.join(_root.EVAL_DIR, 'bge_fullbody_embeddings.npy')
    bge_json = os.path.join(_root.EVAL_DIR, 'bge_fullbody_skills.json')
    if not os.path.exists(bge_npy) or not os.path.exists(bge_json):
        return ('FAIL', 'BGE 索引文件不存在：先运行 python eval/build_indexes.py --apply 重建')
    try:
        arr = np.load(bge_npy, mmap_mode='r')  # P1-2: 只读 mmap，免全量驻留内存
        skills = _root.load_json(bge_json)
        uni = _root.load_registry_uni()  # P1-2: 单次加载缓存（原 5 处重复 json.load）
        reg_skills = set(uni.get('skills', {}).keys())
        if arr.shape[0] != len(skills):
            return ('FAIL', f'npy 行数({arr.shape[0]}) != skills.json({len(skills)})')
        bge_names = {s.get('name', s) if isinstance(s, dict) else s for s in skills}
        if bge_names != reg_skills:
            missing = sorted(reg_skills - bge_names)[:5]
            extra = sorted(bge_names - reg_skills)[:5]
            return ('FAIL', f'BGE 集合 != 注册表 ({len(bge_names)} vs {len(reg_skills)}) '
                    f'缺:{missing} 多:{extra}')
        return ('PASS', f'BGE 索引 == 注册表 ({len(bge_names)} skills, shape={arr.shape})')
    except Exception as e:
        return ('FAIL', f'BGE 校验异常: {e}')


def check_c10_three_way_data_layer(skip_external=False):
    """C10: 注册表 == BGE == skill_content 三方集合相等。

    + eval/skill_ids.json 零残留
    + npy/tfidf 形状校验（213 行 / 域 JSON 24 桶 / disk_manifest 213 条）
    本地跑；CI（skill_content 不可达）保持 SKIP。
    """
    if skip_external or not _root.external_root_reachable(_root.SKILL_CONTENT):
        return ('SKIP', 'skill_content 不可达（CI 环境，C10 保持本地）')
    import numpy as np
    from scipy import sparse

    try:
        uni = _root.load_registry_uni()  # P1-2: 单次加载缓存（原 5 处重复 json.load）
        reg_names = set(uni.get('skills', {}))
        if not reg_names:
            return ('FAIL', '注册表 skills 为空')

        # eval 侧 BGE
        bge_npy = os.path.join(_root.EVAL_DIR, 'bge_fullbody_embeddings.npy')
        bge_json = os.path.join(_root.EVAL_DIR, 'bge_fullbody_skills.json')
        if not os.path.exists(bge_npy) or not os.path.exists(bge_json):
            return ('FAIL', 'eval BGE 三件套缺失：先运行 build_indexes.py --apply')
        arr = np.load(bge_npy, mmap_mode='r')  # P1-2: 只读 mmap，免全量驻留内存
        bge_skills = _root.load_json(bge_json)
        bge_names = {s.get('name') for s in bge_skills}
        if bge_names != reg_names:
            return ('FAIL', f'BGE 集合 != 注册表 ({len(bge_names)} vs {len(reg_names)})')
        if arr.shape[0] != len(bge_names):
            return ('FAIL', f'eval BGE npy 行数 {arr.shape[0]} != {len(bge_names)}')

        # skill_content 侧
        sc_ids_path = os.path.join(_root.SKILL_CONTENT, 'skill_ids.json')
        sc_ids = _root.load_json(sc_ids_path)
        sc_names = {s.get('name') for s in sc_ids}
        if sc_names != reg_names:
            return ('FAIL', f'skill_content skill_ids 集合 != 注册表 ({len(sc_names)} vs {len(reg_names)})')
        sc_arr = np.load(os.path.join(_root.SKILL_CONTENT, 'bge_embeddings.npy'), mmap_mode='r')  # P1-2
        if sc_arr.shape != arr.shape:
            return ('FAIL', f'skill_content BGE shape {sc_arr.shape} != eval {arr.shape}')

        # 域 JSON 分桶：文件数 == 注册表 domain 数，总数 == 213
        domain_files = [f for f in os.listdir(_root.SKILL_CONTENT)
                        if f.endswith('.json')
                        and f not in ('skill_ids.json', 'index_manifest.json')]
        domain_names = {f[:-5] for f in domain_files}
        reg_domains = {v.get('domain') or '99-other' for v in uni['skills'].values()}
        if domain_names != reg_domains:
            return ('FAIL', f'域 JSON 桶 != 注册表 domain 集 ({len(domain_names)} vs {len(reg_domains)})')
        total_sc = 0
        for fn in domain_files:
            data = _root.load_json(os.path.join(_root.SKILL_CONTENT, fn))
            total_sc += len(data.get('skills', []))
        if total_sc != len(reg_names):
            return ('FAIL', f'skill_content 域 JSON 总数 {total_sc} != 注册表 {len(reg_names)}')

        # TF-IDF 双端形状
        eval_ids = _root.load_json(os.path.join(_root.EVAL_DIR, 'tfidf_skill_ids.json'))
        if len(eval_ids) != len(reg_names):
            return ('FAIL', f'eval tfidf_skill_ids {len(eval_ids)} != {len(reg_names)}')
        for base, label in ((_root.EVAL_DIR, 'eval'), (_root.SKILL_CONTENT, 'skill_content')):
            m = sparse.load_npz(os.path.join(base, 'tfidf_matrix.npz'))
            if m.shape[0] != len(reg_names):
                return ('FAIL', f'{label} tfidf 行数 {m.shape[0]} != {len(reg_names)}')

        # eval/skill_ids.json 零残留
        if os.path.exists(os.path.join(_root.EVAL_DIR, 'skill_ids.json')):
            return ('FAIL', 'eval/skill_ids.json 退役残留（应删除，R193）')

        # disk_manifest 入库清单
        dm_path = os.path.join(_root.REGISTRY, 'disk_manifest.json')
        if not os.path.exists(dm_path):
            return ('FAIL', 'disk_manifest.json 缺失')
        dm = _root.load_json(dm_path)
        dm_names = {s['name'] for s in dm.get('skills', [])}
        if dm_names != reg_names or dm.get('count') != len(reg_names):
            return ('FAIL', f'disk_manifest 与注册表不一致 ({len(dm_names)} vs {len(reg_names)})')

        return ('PASS', f'三方集合相等 ({len(reg_names)} skills / {len(domain_files)} 域 / '
                        f'BGE {arr.shape} / TF-IDF {m.shape})')
    except Exception as e:
        return ('FAIL', f'C10 校验异常: {e}')

