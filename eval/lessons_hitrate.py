#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lessons_hitrate.py — lessons 命中率度量（主线④核心）
=====================================================================
把"记住教训"升级为"用上教训"：对每条行为指纹(lessons_fingerprints.json)
扫描目标文件做机械断言，命中=该教训真的在产物/行为中体现。

用法:
  python eval/lessons_hitrate.py                # 全量扫描
  python eval/lessons_hitrate.py --json        # JSON 输出(仅JSON, 供 aggregate_status 消费)
  python eval/lessons_hitrate.py --fingerprint FP-01   # 只扫单条

输出:
  每条指纹: 命中/未命中 + 具体证据行
  总体: 命中率 = 命中条数 / 可判定条数
"""
import json
import os
import sys
import glob
import datetime

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
GM = r'<MEMORY_ROOT>'
FP_PATH = os.path.join(EVAL_DIR, 'lessons_fingerprints.json')

# 默认目标文件集（每条指纹 target_files 里的 glob 相对此根解析）
# R272（2026-09-22）：评分派发池迁出系统临时目录。原指向 %TEMP%\fenjue_prompts，
# 系统清理 Temp 后 FP-05/FP-14 的判据目标消失 → 自动转「需人工确认」且不计入分母
# ⇒ 命中率随系统清理行为浮空（判据面易失）。现落在受管根之外的持久目录。
PROMPT_POOL = r'<USER_HOME>\.fenjue\prompt_pool'

TARGET_ROOTS = {
    '<MEMORY_ROOT>\\scripts\\': r'<MEMORY_ROOT>\scripts',
    '<MEMORY_ROOT>\\lessons\\': r'<MEMORY_ROOT>\lessons',
    'PROJECT': PROJECT_DIR,
    'PROMPTS': PROMPT_POOL,
}


def resolve_targets(patterns):
    """把 target_files glob 模式解析为实际文件路径列表"""
    files = []
    for pat in patterns:
        pat = pat.replace('\\', os.sep)
        if pat.startswith('D:' + os.sep):
            files.extend(glob.glob(pat))
        elif pat.startswith('PROMPTS'):
            files.extend(glob.glob(os.path.join(PROMPT_POOL,
                                                pat.replace('PROMPTS/', '', 1))))
        else:
            files.extend(glob.glob(os.path.join(PROJECT_DIR, pat)))
            files.extend(glob.glob(os.path.join(GM, pat)))
    # 去重 + 只留存在的
    seen = set()
    out = []
    for f in files:
        if f not in seen and os.path.exists(f):
            seen.add(f)
            out.append(f)
    return out


from io_utils import read_text_safe as _read_text_safe  # P1-5: 读写原语唯一实现


def read_text(path, max_kb=200):
    """读文件文本（截断防大文件，fail-open 与历史等价）"""
    return _read_text_safe(path, errors='replace', max_kb=max_kb)


def run_check(check, text, path):
    """执行单条 check, 返回 (通过?, 证据)"""
    ctype = check.get('type', '')
    if ctype == 'contains_any':
        for p in check.get('patterns', []):
            if p in text:
                return True, f'含 "{p}"'
        return False, f'未含任何 {check.get("patterns")}'
    elif ctype == 'contains_all':
        missing = [p for p in check.get('patterns', []) if p not in text]
        if not missing:
            return True, f'含全部 {check.get("patterns")}'
        return False, f'缺 {missing}'
    elif ctype == 'not_contains_any':
        hits = [p for p in check.get('patterns', []) if p in text]
        if not hits:
            return True, '未含禁用模式'
        return False, f'含禁用模式 {hits}'
    elif ctype == 'context_evidence':
        # 上下文证据类: 无法纯机械判定, 标记为"需人工确认"
        return None, '上下文证据类(需收尾报告人工确认)'
    elif ctype == 'npy_shape_matches':
        # 机械判定: npy 行数 == 技能表条数（FP-13: 注册 skill 后必须重建 BGE 嵌入矩阵）
        npy_pat = check.get('npy')
        json_pat = check.get('json')
        npy_files = resolve_targets([npy_pat]) if npy_pat else []
        json_files = resolve_targets([json_pat]) if json_pat else []
        if not npy_files or not json_files:
            return None, f'目标缺失 npy={npy_files} json={json_files}'
        try:
            import numpy as np
            npy_rows = int(np.load(npy_files[0], mmap_mode='r').shape[0])
        except Exception as e:
            return None, f'npy 读取失败: {e}'
        try:
            with open(json_files[0], encoding='utf-8') as fh:
                jdata = json.load(fh)
            jlen = len(jdata) if isinstance(jdata, list) else len(jdata.get('skills', []))
        except Exception as e:
            return None, f'json 读取失败: {e}'
        if npy_rows == jlen:
            return True, f'npy行数={npy_rows} == 技能表={jlen}'
        return False, f'npy行数={npy_rows} != 技能表={jlen}'
    elif ctype == 'json_count_equal':
        # 机械判定: 两个 json 列表长度一致（FP-16: 同名单文件禁止双源漂移）
        a_pat = check.get('a')
        b_pat = check.get('b')
        a_files = resolve_targets([a_pat]) if a_pat else []
        b_files = resolve_targets([b_pat]) if b_pat else []
        if not a_files or not b_files:
            return None, f'目标缺失 a={a_files} b={b_files}'
        try:
            with open(a_files[0], encoding='utf-8') as fh:
                ad = json.load(fh)
            with open(b_files[0], encoding='utf-8') as fh:
                bd = json.load(fh)
            alen = len(ad) if isinstance(ad, list) else len(ad.get('skills', []))
            blen = len(bd) if isinstance(bd, list) else len(bd.get('skills', []))
        except Exception as e:
            return None, f'json 读取失败: {e}'
        if alen == blen:
            return True, f'{os.path.basename(a_files[0])}={alen} == {os.path.basename(b_files[0])}={blen}'
        return False, f'{os.path.basename(a_files[0])}={alen} != {os.path.basename(b_files[0])}={blen}'
    elif ctype == 'version_toc_consistent':
        # 机械判定: 版本锁 TOC 双向一致（FP-08: 修改带版本声明的文件后必须同步引用面）
        # 索引文件引用的 part 卷全部存在，且引用卷数 == 实际 part 文件数。
        index_pat = check.get('index')
        part_glob = check.get('parts')
        index_files = resolve_targets([index_pat]) if index_pat else []
        if not index_files:
            return None, f'索引缺失 index={index_files}'
        try:
            import re as _re
            text = read_text(index_files[0])
            refs = set(_re.findall(check.get('part_pattern', r'\.part(\d+)\.'), text))
            part_files = glob.glob(os.path.join(os.path.dirname(index_files[0]), part_glob)) if part_glob else []
            actual = {_re.search(r'\.part(\d+)\.', os.path.basename(p)).group(1)
                      for p in part_files if _re.search(r'\.part(\d+)\.', os.path.basename(p))}
            missing = refs - actual
            if missing:
                return False, f'索引引用 {len(refs)} 卷, 缺失 {sorted(missing)}'
            if len(refs) != len(actual):
                return False, f'索引引用 {len(refs)} 卷 != 实际 part {len(actual)}'
            return True, f'索引 {len(refs)} 卷 == 实际 part {len(actual)}, 0 缺失'
        except Exception as e:
            return None, f'版本锁检查失败: {e}'
    elif ctype == 'count_matches_source':
        # 机械判定: 文档内声明的计数 == 真相源实测。
        # R263 判据升级（2026-09-22）：原 FP-15 用 not_contains_any 硬编码
        # 「总计：151」——那是 2026-08-02 漂移当时的症状值；该值现已是注册表正确值，
        # 且与 build_indexes 的注入行（**总计：N 个 skill / M 个领域**）互斥 ⇒
        # 恒判未命中（假失败）。改为动态比对：保留 lesson 本体（路由表计数必须与
        # 数据层一致），去掉过期字面量。
        index_pat = check.get('index')
        src_pat = check.get('source')
        cnt_re = check.get('pattern', r'\*\*总计：(\d+)\s*个 skill\s*/\s*(\d+)\s*个领域\*\*')
        index_files = resolve_targets([index_pat]) if index_pat else []
        src_files = resolve_targets([src_pat]) if src_pat else []
        if not index_files:
            return None, f'索引缺失 index={index_files}'
        if not src_files:
            return None, f'真相源缺失 source={src_files}'
        try:
            import re as _re2
            # 判据必须只消费「传入样本」text（首版误写成 read_text(index_files[0]) 重读文件 →
            # 对照桩注入违规样本无效，判据不可测：4 例全部返回同一结论。R263 教训）
            itext = text
            m = _re2.search(cnt_re, itext)
            if not m:
                return False, '未解析到计数行（零命中，输入不可信）'
            doc_n, doc_d = int(m.group(1)), int(m.group(2))
            with open(src_files[0], encoding='utf-8') as fh:
                reg = json.load(fh)
            skills = reg.get('skills', reg) if isinstance(reg, dict) else reg
            reg_n = len(skills)
            reg_d = len({v.get('domain') for v in skills.values()
                         if isinstance(v, dict) and v.get('domain')}) if isinstance(skills, dict) else 0
        except Exception as e:
            return None, f'计数比对失败: {e}'
        # 领域数仅作观测、不判 FAIL：注册表 skills[].domain 去重 = 13，而 skill_content
        # 域桶 = 14（口径分歧尚未裁决），拿它当判据会制造假失败（R263：假失败先修判据）。
        if doc_n == reg_n:
            return True, f'文档计数 {doc_n}/{doc_d} == 注册表实测 {reg_n}/{reg_d}（领域数口径分歧见 note）'
        return False, f'计数过期: 文档={doc_n} vs 注册表={reg_n}'
    elif ctype == 'verify_scripts_exist':
        # 机械判定: 验证/审计脚本已机制化（FP-09: 修复根因后必须写验证脚本跑断言）
        # 目标目录含 >=min 个 verify/audit 脚本 = 验证实践已制度化。
        dirs = check.get('dirs', [])
        min_n = int(check.get('min', 3))
        pat = check.get('pattern', r'(verify|audit|check|test)')
        import re as _re
        found = []
        for d in dirs:
            d = d.replace('\\', os.sep)
            base = r'<MEMORY_ROOT>' if d.startswith('D:') else PROJECT_DIR
            full = d if os.path.isabs(d) else os.path.join(base, d)
            if not os.path.isdir(full):
                continue
            for name in os.listdir(full):
                if name.endswith('.py') and _re.search(pat, name):
                    found.append(os.path.join(full, name))
        if len(found) >= min_n:
            return True, f'验证脚本 {len(found)} 个 >= {min_n} ({os.path.basename(found[0])} 等)'
        return False, f'验证脚本 {len(found)} 个 < {min_n}'
    return None, f'未知 check 类型 {ctype}'


def evaluate_fingerprint(fp, verbose=True):
    """对一条指纹评分, 返回 (可判定?, 命中?, 明细)"""
    files = resolve_targets(fp.get('target_files', []))
    if not files:
        return False, False, {'reason': '无目标文件', 'files': []}
    checks = fp.get('checks', [])
    results = []
    passed = 0
    manual = 0
    for ch in checks:
        ch_ok = None  # None=需人工, True=过, False=不过
        evidence = ''
        for f in files:
            text = read_text(f)
            r, ev = run_check(ch, text, f)
            if r is not None:  # 机械可判定
                ch_ok = r
                evidence = f'{os.path.basename(f)}: {ev}'
                if r:
                    break
                # 未命中继续看其他文件
            else:
                manual += 1
                evidence = ev
                break
        results.append({'check': ch.get('note', ''), 'ok': ch_ok, 'evidence': evidence})
        if ch_ok is True:
            passed += 1
    # 命中规则: 全部机械 check 通过 = 命中; 有需人工的按通过数占比
    mech = [r for r in results if r['ok'] is not None]
    if not mech:
        return False, False, {'reason': '全需人工', 'results': results}
    hit = all(r['ok'] for r in mech) and len(mech) == len([c for c in checks if c.get('type') != 'context_evidence'])
    return True, hit, {'results': results, 'files': [os.path.basename(f) for f in files[:3]]}


def main():
    is_json = '--json' in sys.argv
    with open(FP_PATH, encoding='utf-8') as _f:
        fps = json.load(_f)['fingerprints']
    out_json = {'schema': 'fenjue-lessons-hitrate-v1',
                'ts': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                'total': len(fps), 'hit': 0, 'miss': 0, 'manual': 0, 'no_target': 0,
                'details': []}
    if not is_json:
        print('═' * 60)
        print('  lessons 命中率度量 (主线④) — 行为指纹扫描')
        print('═' * 60)
    for fp in fps:
        decid, hit, detail = evaluate_fingerprint(fp)
        tag = fp['id']
        if not decid:
            out_json['manual'] += 1
            _why = detail.get('reason', '')
            if _why == '无目标文件':
                # R272 显式记账：判据面缺失不得静默 —— 单列计数，让「分母不可信」可见
                out_json['no_target'] += 1
            if not is_json:
                print(f'  [{tag}] ⚪ 需人工确认 ({_why})')
            out_json['details'].append({'id': tag, 'status': 'manual', 'note': _why})
            continue
        if hit:
            out_json['hit'] += 1
            if not is_json:
                print(f'  [{tag}] ✅ 命中 — {fp["lesson"][:40]}')
        else:
            out_json['miss'] += 1
            if not is_json:
                print(f'  [{tag}] ❌ 未命中 — {fp["lesson"][:40]}')
                for r in detail.get('results', []):
                    if r['ok'] is False:
                        print(f'        ↳ {r["check"]}: {r["evidence"]}')
        out_json['details'].append({'id': tag, 'status': 'hit' if hit else 'miss',
                                    'lesson': fp['lesson']})

    decid_total = out_json['hit'] + out_json['miss']
    rate = out_json['hit'] / decid_total * 100 if decid_total else 0
    out_json['hit_rate'] = round(rate, 1)
    if is_json:
        # --json 模式: 只输出 JSON, 不打印报告
        print(json.dumps(out_json, ensure_ascii=False, indent=1))
        return
    print('─' * 60)
    print(f"  可判定 {decid_total} 条 | 命中 {out_json['hit']} | 未命中 {out_json['miss']} | "
          f"人工 {out_json['manual']}（其中无目标文件 {out_json['no_target']} —— 判据面缺失，"
          f"不计入分母；该数越大命中率分母越不可信）")
    print(f"  命中率: {rate:.1f}%")
    print('─' * 60)


if __name__ == '__main__':
    main()
