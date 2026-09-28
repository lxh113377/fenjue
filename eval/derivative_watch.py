#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
derivative_watch.py — C10 派生件 watcher（R216-02）
====================================================
背景：skill_content / BGE / TF-IDF 派生件被并行会话回退已三次发作
（R210-03、R214），每次靠人工 build_indexes --apply 复绿。本工具把
「发现回退 → 告警 → 自动重建」闭环机制化：

  python eval/derivative_watch.py --snapshot       # 建基线快照（build_indexes --apply 后自动调用）
  python eval/derivative_watch.py --check          # 快照比对 + 结构计数（漂移 exit 1）
  python eval/derivative_watch.py --check --json   # JSON 报告
  python eval/derivative_watch.py --fix            # 检出漂移 → build_indexes --apply → 重建快照 → 复检

产物清单 = verify_truth_consistency C2/C10 消费面（单一权威来源）：
  eval/{bge_fullbody_embeddings.npy, bge_fullbody_skills.json,
        tfidf_skill_ids.json, tfidf_matrix.npz}
  SKILL_CONTENT/{skill_ids.json, bge_embeddings.npy, tfidf_matrix.npz, <域 JSON>}
  registry/{unified-skills-index.json, disk_manifest.json}
排除：*.json.prev（备份残留，非消费面）。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import EVAL_DIR, SKILL_CONTENT, PROJECT_DIR, GLOBAL_SKILLS  # noqa: E402

REGISTRY = os.path.join(PROJECT_DIR, 'skill', 'registry')
MANIFEST_PATH = os.path.join(EVAL_DIR, 'derivative_manifest.json')
BUILD_INDEXES = os.path.join(EVAL_DIR, 'build_indexes.py')

SCHEMA = 'fenjue-derivative-watch-v1'
# 容差：同一次 --apply 里"先读源后写产物"的毫秒级抖动不算过期
FRESH_GRACE_S = 5.0


def collect_artifacts():
    """返回 (stable_paths, domain_paths)：稳定产物 + 域 JSON 动态集（以注册表 domain 为准）。"""
    stable = [
        os.path.join(EVAL_DIR, 'bge_fullbody_embeddings.npy'),
        os.path.join(EVAL_DIR, 'bge_fullbody_skills.json'),
        os.path.join(EVAL_DIR, 'tfidf_skill_ids.json'),
        os.path.join(EVAL_DIR, 'tfidf_matrix.npz'),
        # Tag 层运行时输入（tag_layer.py 直读）。2026-09-26 前不在观测集内，导致它
        # 停在 09-21 达 5 天、覆盖 144/167 无一处报警；C30 判的是源表而非本件。
        # 注意：本项进 stable 只纳入 hash/size 漂移观测，不进新鲜度基准 ——
        # stale_sources() 有意只取 .npy/.npz（见其 docstring，避免 45 个正常
        # 编辑的 SKILL.md 被误报为过期）。
        os.path.join(EVAL_DIR, 'skill_tags.json'),
        os.path.join(SKILL_CONTENT, 'skill_ids.json'),
        os.path.join(SKILL_CONTENT, 'bge_embeddings.npy'),
        os.path.join(SKILL_CONTENT, 'tfidf_matrix.npz'),
        os.path.join(REGISTRY, 'unified-skills-index.json'),
        os.path.join(REGISTRY, 'disk_manifest.json'),
    ]
    domain_paths = []
    dom_dir = SKILL_CONTENT
    if os.path.isdir(dom_dir):
        for f in sorted(os.listdir(dom_dir)):
            if f.endswith('.json') and f not in ('skill_ids.json', 'index_manifest.json') \
                    and not f.endswith('.prev'):
                domain_paths.append(os.path.join(dom_dir, f))
    return stable, domain_paths


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _key(p):
    """manifest 键：同盘用相对路径；跨盘（C: 工作区 vs D: skill_content）回退绝对路径。"""
    try:
        return os.path.relpath(p, PROJECT_DIR)
    except ValueError:
        return os.path.abspath(p).replace('\\', '/')


def snapshot(paths=None, manifest_path=None):
    """写基线快照：{relpath: {size, sha256, mtime}}。返回 manifest dict。"""
    stable, domain = collect_artifacts() if paths is None else paths
    all_paths = list(stable) + list(domain)
    arts = {}
    for p in all_paths:
        if not os.path.exists(p):
            continue
        rel = _key(p)
        arts[rel] = {'size': os.path.getsize(p), 'sha256': _digest(p),
                     'mtime': os.path.getmtime(p)}
    manifest = {'schema': SCHEMA, 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'artifacts': arts}
    mp = manifest_path or MANIFEST_PATH
    Path(mp).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def structure_counts():
    """轻量结构计数（集合/形状级，与 C10 同源口径；失败不抛，记 error）。"""
    import numpy as np
    try:
        from scipy import sparse
    except ImportError:
        sparse = None
    out = {}
    try:
        bge = json.loads(Path(os.path.join(EVAL_DIR, 'bge_fullbody_skills.json')).read_text(encoding='utf-8'))
        bge_n = len(bge)
        arr = np.load(os.path.join(EVAL_DIR, 'bge_fullbody_embeddings.npy'))
        tfidf_n = len(json.loads(Path(os.path.join(EVAL_DIR, 'tfidf_skill_ids.json')).read_text(encoding='utf-8')))
        uni = json.loads(Path(os.path.join(REGISTRY, 'unified-skills-index.json')).read_text(encoding='utf-8'))
        reg_n = len(uni.get('skills', {}))
        sc_n = None
        ids_p = os.path.join(SKILL_CONTENT, 'skill_ids.json')
        if os.path.exists(ids_p):
            sc_n = len(json.loads(Path(ids_p).read_text(encoding='utf-8')))
        out.update({'bge_skills': bge_n, 'bge_rows': int(arr.shape[0]),
                    'tfidf_ids': tfidf_n, 'registry': reg_n, 'skill_content_ids': sc_n})
        counts = {bge_n, int(arr.shape[0]), tfidf_n, reg_n} | ({sc_n} if sc_n is not None else set())
        out['counts_equal'] = (len(counts) == 1)
        if sparse is not None:
            m = sparse.load_npz(os.path.join(EVAL_DIR, 'tfidf_matrix.npz'))
            out['tfidf_rows'] = int(m.shape[0])
            out['counts_equal'] = out['counts_equal'] and out['tfidf_rows'] == reg_n
    except Exception as e:  # noqa: BLE001 — 结构探查失败不阻断 hash 比对主路径
        out['error'] = repr(e)
        out['counts_equal'] = False
    return out


def stale_pairs(artifact_paths, source_paths, grace_s=FRESH_GRACE_S):
    """纯函数：任一输入的 mtime 晚于"最早的那个产物" ⇒ 产物是用过期输入编出来的。

    取不到可比对象（产物或输入一边为空）时返回 **None** 而不是 []：
    没有数就不许下"新鲜"的结论（R247 同族）。
    """
    arts = [p for p in artifact_paths if os.path.isfile(p)]
    srcs = [p for p in source_paths if os.path.isfile(p)]
    if not arts or not srcs:
        return None
    oldest = min(arts, key=os.path.getmtime)
    built = os.path.getmtime(oldest)
    hits = []
    for s in srcs:
        lag = os.path.getmtime(s) - built
        if lag > grace_s:
            hits.append({'source': os.path.basename(os.path.dirname(s)),
                         'artifact': os.path.basename(oldest), 'lag_s': round(lag, 1)})
    return sorted(hits, key=lambda h: -h['lag_s'])


def skill_source_files(skills_root=None):
    root = skills_root or GLOBAL_SKILLS
    if not os.path.isdir(root):
        return []
    return [os.path.join(root, n, 'SKILL.md') for n in sorted(os.listdir(root))
            if os.path.isfile(os.path.join(root, n, 'SKILL.md'))]


def stale_sources(skills_root=None):
    """守恒（行数/名册）不等于新鲜：产物可以完全自洽，却是用几小时前的 SKILL.md 编的。

    基线取**编码类产物**（npy/npz）的最新 mtime = 编码流水线最后一次真跑的时间。
    不能拿全部产物的最旧 mtime：`unified-skills-index.json` 等内容未变时不重写，
    mtime 会停在 23 小时前 —— 拿它当基准会把 45 个正常编辑过的 SKILL.md 全误报成过期。
    """
    stable, _domain = collect_artifacts()
    embed = [p for p in stable if p.endswith(('.npy', '.npz'))]
    return stale_pairs(embed or list(stable), skill_source_files(skills_root))


def check(manifest_path=None, paths=None, with_freshness: bool = False):
    """比对快照：漂移（hash/size）+ 缺失 + 多出 + 结构计数。

    `with_freshness` 只**附加**读数、不参与 ok —— 新指标先量误报率再接线（advisory）。
    """
    mp = manifest_path or MANIFEST_PATH
    if not os.path.exists(mp):
        return {'schema': SCHEMA, 'ok': False, 'error': 'manifest 缺失（先 --snapshot）'}
    manifest = json.loads(Path(mp).read_text(encoding='utf-8'))
    old = manifest.get('artifacts', {})
    stable, domain = collect_artifacts() if paths is None else paths
    current = {}
    for p in list(stable) + list(domain):
        if os.path.exists(p):
            rel = _key(p)
            current[rel] = {'size': os.path.getsize(p), 'sha256': _digest(p)}
    drifted = [r for r in sorted(set(old) & set(current))
               if old[r].get('sha256') != current[r]['sha256']
               or old[r].get('size') != current[r]['size']]
    missing = sorted(set(old) - set(current))
    extra = sorted(set(current) - set(old))
    out = {'schema': SCHEMA, 'ok': not (drifted or missing or extra),
           'drifted': drifted, 'missing': missing, 'extra': extra,
           'structure': structure_counts(),
           'snapshot_at': manifest.get('generated_at')}
    if with_freshness:
        out['freshness'] = stale_sources()
    return out


def fix():
    """漂移自愈：build_indexes --apply → 重建快照 → 复检。"""
    try:
        r = subprocess.run([sys.executable, BUILD_INDEXES, '--apply'],
                           capture_output=True, text=True, encoding='utf-8',
                           cwd=PROJECT_DIR, errors='replace', timeout=1800)
    except subprocess.TimeoutExpired:
        return {'schema': SCHEMA, 'ok': False, 'fixed': False,
                'error': 'build_indexes --apply 超时 (1800s) 被终止'}
    if r.returncode != 0:
        return {'schema': SCHEMA, 'ok': False, 'fixed': False,
                'error': f'build_indexes --apply 失败 (exit {r.returncode})',
                'stderr_tail': (r.stderr or '')[-500:]}
    snapshot()
    return check() | {'fixed': True}


def main(argv=None):
    ap = argparse.ArgumentParser(description='C10 派生件 watcher（R216-02）')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--snapshot', action='store_true', help='建/刷新基线快照')
    g.add_argument('--check', action='store_true', help='快照比对 + 结构计数')
    g.add_argument('--fix', action='store_true', help='漂移自动重建（build_indexes --apply）')
    ap.add_argument('--json', action='store_true', help='JSON 输出')
    args = ap.parse_args(argv)

    if args.snapshot:
        m = snapshot()
        report = {'schema': SCHEMA, 'ok': True, 'snapshotted': len(m['artifacts']),
                  'snapshot_at': m['generated_at']}
    elif args.check:
        report = check(with_freshness=True)
    else:
        report = check()
        if not report.get('ok') and 'error' not in report:
            report = fix()
        elif 'error' in report and report.get('error') == 'manifest 缺失（先 --snapshot）':
            report = fix()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.check:
        # 新鲜度只报告不改退出码：守恒≠新鲜，但"源刚被改过"不等于产物坏了（advisory）
        st = report.get('freshness')
        if st is None:
            print('[derivative-watch] 新鲜度 UNVERIFIED（输入面或产物面取不到数）')
        elif st:
            print('[derivative-watch] 新鲜度：%d 个 SKILL.md 比派生件新 ⇒ 派生件已过期，'
                  '跑 build_indexes.py --apply（最早滞后 %.0fs：%s）'
                  % (len(st), st[0]['lag_s'], ', '.join(x['source'] for x in st[:5])))
        else:
            print('[derivative-watch] 新鲜度：无输入比产物新')
    if args.check or args.fix:
        sys.exit(0 if report.get('ok') else 1)


if __name__ == '__main__':
    main()
