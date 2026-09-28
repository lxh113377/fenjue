#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
functional_dim_checks.py - R166-U2 功能化检查（真实行为验证，禁止只查文件存在）
=============================================================================
为评分卡存在性维度提供"真能用、真一致"的机器实测：

  watcher      : 真实触发 watcher 三脚本安全模式
                 (detect-changes.ps1 全量检测 / auto-sync.ps1 -ReportOnly /
                  confirm-delete.ps1 -WhatIf)
  coverage     : 13 个域每域从 layered_testset 抽 query 真实路由命中（有 query 则至少 1 条）
  version      : regen_ic_parts.py --check SHA 一致性 + VERSION_LOCK TOC/part 双向一致
  dataintegrity: 数据层内容级自洽（域 JSON 可解析、条目字段完整、
                 注册表→路由索引覆盖、路由索引→磁盘 SKILL.md 存在）

用法:
  python functional_dim_checks.py          # 人类可读报告
  python functional_dim_checks.py --json   # 机器可读（scorecard.py 消费）
"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
sys.path.insert(0, EVAL_DIR)
from truth_constants import GLOBAL_MEMORY, GLOBAL_SKILLS, ROUTER_PLATFORMS as _ROUTER_EPS  # noqa: E402
from config import SYSTEM_DIRS  # noqa: E402  （单一真相源，原硬拷贝收口）
GM = GLOBAL_MEMORY
SKILLS_DIR = GLOBAL_SKILLS
SC_DIR = os.path.join(GM, 'skill_content')
WATCHER_DIR = os.path.join(PROJECT_DIR, 'skill', 'watcher')
# R-fix: powershell.exe 不在 PATH（本机 PATH 缺 System32\WindowsPowerShell\v1.0），
# 裸名 subprocess 抛 FileNotFoundError → rc=-1 → watcher 三脚本假失败。用全路径兜底。
PWSH = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                    'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe') \
    if os.path.exists(os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                                   'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')) \
    else 'powershell.exe'
# 路由消费平台映射：truth_constants 端点 ID → 注册表 install_state 键名
_EP_TO_REGKEY = {'wb': 'wb', 'tr': 'tc', 'cx': 'codex', 'oc': 'oc'}
ROUTER_PLATFORMS = tuple(_EP_TO_REGKEY.get(ep, ep) for ep in _ROUTER_EPS)  # ('wb','tc','codex')


def _run(cmd, timeout=300, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                           timeout=timeout, cwd=cwd or PROJECT_DIR, errors='replace')
        return r.returncode, r.stdout + r.stderr
    except Exception as e:
        return -1, str(e)


def _run_ps1(script_path, args=None, timeout=300):
    cmd = [PWSH, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script_path]
    if args:
        cmd.extend(args)
    return _run(cmd, timeout=timeout)


def check_watcher():
    """真实触发 watcher 三脚本的安全模式，校验可运行性与检测输出。"""
    sub = []

    # 1) detect-changes.ps1 全量检测（只读，输出 JSON 到临时文件）
    fd, tmp_path = tempfile.mkstemp(suffix='.json', prefix='func_detect_')
    os.close(fd)
    det = {'ok': False, 'detail': ''}
    try:
        rc, out = _run_ps1(os.path.join(WATCHER_DIR, 'detect-changes.ps1'),
                           ['-OutputPath', tmp_path], timeout=300)
        if rc == 0 and os.path.exists(tmp_path):
            with open(tmp_path, encoding='utf-8-sig') as f:
                data = json.load(f)
            ch = data.get('changes', {})
            det = {
                'ok': True,
                'detail': (
                    f"detect 全量检测 OK (workspace={data.get('workspace_count')}, "
                    f"registry={data.get('registry_count')}, "
                    f"new={len(ch.get('new', []))}, missing={len(ch.get('missing', []))}, "
                    f"ghost={len(ch.get('ghosts', []))})"),
                'workspace': data.get('workspace_count'),
                'registry': data.get('registry_count'),
                'new': len(ch.get('new', [])),
                'missing': len(ch.get('missing', [])),
                'ghosts': len(ch.get('ghosts', [])),
            }
        else:
            det = {'ok': False, 'detail': f'detect 运行失败 rc={rc}'}
    except Exception as e:
        det = {'ok': False, 'detail': f'detect 解析失败: {e}'}
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass  # 临时文件清理失败可忽略（OS 层竞态，R207 P2-1 留痕）
    sub.append(det)

    # 2) auto-sync.ps1 -ReportOnly（真实跑 detect + 差异汇总，不修改任何文件）
    rc, out = _run_ps1(os.path.join(WATCHER_DIR, 'auto-sync.ps1'), ['-ReportOnly'], timeout=300)
    ok2 = rc == 0 and 'FATAL' not in out and '仅报告模式' in out
    sub.append({'ok': ok2, 'detail': 'auto-sync -ReportOnly 真实执行' if ok2
                else f'auto-sync 未通过 (rc={rc})'})

    # 3) confirm-delete.ps1 -WhatIf（打印将执行的操作，无任何实际删除）
    rc, out = _run_ps1(os.path.join(WATCHER_DIR, 'confirm-delete.ps1'), ['-WhatIf'], timeout=120)
    ok3 = rc == 0 and 'DRY-RUN' in out
    sub.append({'ok': ok3, 'detail': 'confirm-delete -WhatIf 可执行' if ok3
                else f'confirm-delete 未通过 (rc={rc})'})

    ok_n = sum(1 for s in sub if s['ok'])
    det_extra = sub[0]['detail'] if sub[0]['ok'] else ''
    return {
        'ok_n': ok_n,
        'total': 3,
        'detail': f"功能实测 {ok_n}/3 脚本可跑 {det_extra}",
        'checks': sub,
    }


def _load_domain_skills():
    domains = {}
    for f in sorted(os.listdir(SC_DIR)):
        # index_manifest.json 是清单文件非真实域（R-fix: 此前计入分母虚增 total_domains=20）
        if not f.endswith('.json') or f in ('skill_ids.json', 'index_manifest.json'):
            continue
        try:
            with open(os.path.join(SC_DIR, f), encoding='utf-8') as fh:
                data = json.load(fh)
            skills = data.get('skills', []) if isinstance(data, dict) else data
            domains[data.get('domain', f[:-5]) if isinstance(data, dict) else f[:-5]] = {
                'file': f,
                'names': set(),
                'count': len(skills),
            }
            for s in skills:
                if isinstance(s, dict) and s.get('name'):
                    domains[data.get('domain', f[:-5]) if isinstance(data, dict) else f[:-5]]['names'].add(s['name'])
        except Exception:
            domains[f[:-5]] = {'file': f, 'names': set(), 'count': 0, 'broken': True}
    return domains


def _load_all_queries():
    with open(os.path.join(EVAL_DIR, 'layered_testset.json'), encoding='utf-8') as f:
        data = json.load(f)
    queries = []
    seen = set()
    for tier in data:
        for q in tier.get('queries', []):
            text = q.get('query', '')
            if not text or text in seen:
                continue
            seen.add(text)
            queries.append(q)
    return queries


def _expected_of(q):
    exp = q.get('expected_skill') or q.get('expected') or q.get('skill')
    if isinstance(exp, str):
        return {exp}
    if isinstance(exp, (list, tuple, set)):
        return set(exp)
    return set()


def check_coverage():
    """13 域每域从 layered_testset 抽 query 真实路由命中。"""
    os.environ['FENJUE_ROUTE_TRACE'] = '0'
    os.environ['TQDM_DISABLE'] = '1'
    sys.path.insert(0, EVAL_DIR)
    try:
        import unified_router
    except Exception as e:
        return {'hit_domains': 0, 'total_domains': 13, 'tested': 0, 'detail': f'路由不可用: {e}',
                'uncovered': [], 'domains': {}}

    domains = _load_domain_skills()
    queries = _load_all_queries()
    per_domain = {d: [] for d in domains}
    for q in queries:
        for d, info in domains.items():
            exp = _expected_of(q)
            if exp and exp & info['names']:
                per_domain[d].append(q)
                break

    res_domains = {}
    hit_domains = 0
    tested_total = 0
    uncovered = []
    for d, info in domains.items():
        pool = per_domain[d][:2]
        hits = 0
        for q in pool:
            tested_total += 1
            exp = _expected_of(q)
            try:
                top1 = unified_router.route(q['query'])['top1']
            except Exception:
                top1 = None
            if top1 in exp:
                hits += 1
        ok = len(pool) > 0 and hits >= 1
        if ok:
            hit_domains += 1
        if len(pool) == 0:
            uncovered.append(d)
        res_domains[d] = {'available': len(pool), 'tested': len(pool), 'hit': hits, 'ok': ok}

    detail = (f"每域实测路由命中 {hit_domains}/{len(domains)} 域 (测试 {tested_total} 条; "
              f"无实测query域: {','.join(uncovered) if uncovered else '无'})")
    return {
        'hit_domains': hit_domains,
        'total_domains': len(domains),
        'tested': tested_total,
        'detail': detail,
        'uncovered': uncovered,
        'domains': res_domains,
    }


def check_version():
    """regen --check SHA 一致性 + VERSION_LOCK TOC/part 双向一致。"""
    regen_ok = False
    rc, out = _run([sys.executable, os.path.join(GM, 'scripts', 'regen_ic_parts.py'), '--check'],
                   timeout=120)
    regen_ok = rc == 0 and 'PASS' in out

    toc_ok = False
    parts_n = 0
    meta_dir = os.path.join(GM, 'meta')
    vl_path = os.path.join(meta_dir, 'VERSION_LOCK.md')
    try:
        with open(vl_path, encoding='utf-8', errors='ignore') as f:
            vl = f.read()
        listed = set(re.findall(r'VERSION_LOCK\.part\d+\.md', vl))
        actual = {f for f in os.listdir(meta_dir)
                  if re.fullmatch(r'VERSION_LOCK\.part\d+\.md', f)}
        parts_n = len(actual)
        toc_ok = listed == actual and all(
            os.path.getsize(os.path.join(meta_dir, f)) > 0 for f in actual)
    except Exception:
        toc_ok = False

    ok = regen_ok and toc_ok
    detail = f"regen --check {'PASS' if regen_ok else 'FAIL'} | VERSION_LOCK {parts_n}卷 TOC双向{'一致' if toc_ok else '不一致'}"
    return {'ok': ok, 'regen_ok': regen_ok, 'toc_ok': toc_ok, 'parts_n': parts_n, 'detail': detail}


def check_dataintegrity():
    # 可用性标记（R193）：域 JSON / 注册表读失败 → unavailable 登记，禁止静默 0 分
    domain_read_failed = False
    reg_read_failed = False
    """数据层内容级自洽（与 triple_diff 的三集合对比互补，证据互斥）。"""
    domains = _load_domain_skills()
    domain_valid_n = sum(1 for d in domains.values() if d.get('count', 0) > 0 and not d.get('broken'))
    domain_valid_ratio = domain_valid_n / max(len(domains), 1)

    # 条目字段完整性（name + desc）
    total_entries = 0
    meta_ok = 0
    domain_entries = set()
    for f in sorted(os.listdir(SC_DIR)):
        # R276（2026-09-22）：补排除 index_manifest.json —— 同文件 L130 已排除它，
        # 此处只排了 skill_ids.json ⇒ 非域清单被当域文件读（无 skills 键退化为空，
        # 当前不致错值，但属判据不一致）。由 eval/consistency_consumers.py 锚点判据抓出。
        if not f.endswith('.json') or f in ('skill_ids.json', 'index_manifest.json'):
            continue
        try:
            with open(os.path.join(SC_DIR, f), encoding='utf-8') as fh:
                data = json.load(fh)
            for s in (data.get('skills', []) if isinstance(data, dict) else data):
                if not isinstance(s, dict):
                    continue
                total_entries += 1
                if s.get('name') and s.get('desc'):
                    meta_ok += 1
                if s.get('name'):
                    domain_entries.add(s['name'])
        except Exception:
            # R193 禁静默 0 分：读失败 → 登记 unavailable，由消费方隔离计分而非静默归零
            domain_read_failed = True
    entry_ratio = meta_ok / max(total_entries, 1)

    # 注册表→路由索引覆盖（install_state 任一"路由消费平台"true 的 skill 必须出现在域 JSON）
    # R168 决策: 排除 oc —— OC 注册表含 36 条插件专属 skill(1password/apple-notes 等)，
    # 它们经 OC 插件系统加载，天然不在 skill_content 路由索引作用域（145=四端全局共享集，R169 +hermes-installer）。
    # 全平台口径会把 36 条 OC-only 算进分母 → 恒 80% 假缺口；路由消费平台口径 = 145/145 = 100%。
    reg_path = os.path.join(PROJECT_DIR, 'skill', 'registry', 'cross_platform_map.json')
    reg_installed = set()
    try:
        with open(reg_path, encoding='utf-8') as f:
            reg = json.load(f)
        ROUTER_PLATFORMS_LOCAL = ROUTER_PLATFORMS  # 从 truth_constants 导入，走 skill_content 路由的端
        for name, info in (reg.get('skills') or {}).items():
            if '__skillhub' in name or name.startswith('_'):
                continue
            st = info.get('install_state', {}) if isinstance(info, dict) else {}
            if any(bool(st.get(k)) for k in ROUTER_PLATFORMS_LOCAL):
                reg_installed.add(name)
    except Exception:
        reg_read_failed = True
    route_cover = len(reg_installed & domain_entries) / max(len(reg_installed), 1)

    # 路由索引→磁盘 SKILL.md 存在（OC 内置插件目录作为合法例外）
    disk = set()
    for entry in os.listdir(SKILLS_DIR):
        full = os.path.join(SKILLS_DIR, entry)
        if os.path.isdir(full) and os.path.exists(os.path.join(full, 'SKILL.md')) \
                and entry not in SYSTEM_DIRS:
            disk.add(entry)
    plugins = set()
    plugin_root = r'<NPM_GLOBAL>\node_modules\openclaw\skills'
    if os.path.isdir(plugin_root):
        plugins = {e for e in os.listdir(plugin_root) if os.path.isdir(os.path.join(plugin_root, e))}
    disk_presence = len(domain_entries & (disk | plugins)) / max(len(domain_entries), 1)

    health = round((domain_valid_ratio + entry_ratio + route_cover + disk_presence) / 4 * 100, 1)
    detail = (f"内容级自洽 {health}% (域JSON {domain_valid_n}/{len(domains)} 可解析, "
              f"条目字段 {round(entry_ratio * 100)}%, 注册→索引 {round(route_cover * 100)}%, "
              f"索引→磁盘 {round(disk_presence * 100)}%)")
    return {
        'health': health,
        'domain_valid': domain_valid_n,
        'domain_total': len(domains),
        'entry_ratio': round(entry_ratio, 3),
        'route_cover': round(route_cover, 3),
        'disk_presence': round(disk_presence, 3),
        'unavailable': [src for src, bad in
                        (('domain_json', domain_read_failed),
                         ('cross_platform_map', reg_read_failed)) if bad],
        'detail': detail,
    }


def main():
    as_json = '--json' in sys.argv
    result = {
        'schema': 'fenjue-functional-dims-v1',
        'ts': datetime.datetime.now().isoformat(timespec='seconds'),
        'watcher': check_watcher(),
        'coverage': check_coverage(),
        'version': check_version(),
        'dataintegrity': check_dataintegrity(),
    }
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print('=' * 60)
    print('功能化检查 (functional_dim_checks)')
    print('=' * 60)
    w = result['watcher']
    print(f"[watcher] {w['detail']}")
    c = result['coverage']
    print(f"[coverage] {c['detail']}")
    v = result['version']
    print(f"[version] {v['detail']}")
    d = result['dataintegrity']
    print(f"[dataintegrity] {d['detail']}")
    print('=' * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
