#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aggregate_status.py — 从独立 session 状态报告聚合生成 STATUS.md
============================================================
取代多 session 直接竞态覆写 STATUS.md。各 session 写独立 report 文件，
本脚本聚合最新数据后生成 STATUS.md。

R197: 头条达标判定改由 verify_truth_consistency.py 门禁(C1~C12) 单一真相源驱动，
评分卡百分比(如 99.7%) 仅作明细参考，防止失真反复出现。

用法:
  python aggregate_status.py              # 聚合写入 STATUS.md
  python aggregate_status.py --dry-run     # 仅打印，不写入

报告格式 (reports/<日期>_<session>_status.json):
{
  "ts": "2026-07-30T23:30:00+08:00",
  "session": "HM-ms6bldk7",
  "scores": {
    "优化记忆": {"round": "R32","score": 135,"out_of": 150,"pass": 115},
    "skill_tree": {"round": "R17","score": 140,"out_of": 150,"pass": 115},
    "我的skill":  {"round": "R7", "score": 142,"out_of": 150,"pass": 115}
  },
  "notes": "核心变更描述"
}
"""
import os
import sys
import json
import glob

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
sys.path.insert(0, EVAL_DIR)
from truth_constants import (  # noqa: E402
    SCORECARD_ACTIVE_TOTAL, SCORECARD_ACTIVE_PASS_LINE, derive_max_gate_id,
)
REPORTS_DIR = os.path.join(PROJECT_DIR, 'reports')
STATUS_PATH = os.path.join(PROJECT_DIR, 'STATUS.md')
STATUS_PART1_PATH = os.path.join(PROJECT_DIR, 'STATUS.part1.md')
PROJECT_NAME = '焚诀'
# 2026-09-24 对标轮：原恒取 track_150（120/150），与 track_200 实测总分口径错配
# （status_report 已在 R213 修过同型缺陷，本文件是漏改的第二渲染入口）。
PASS_LINE = f'{SCORECARD_ACTIVE_PASS_LINE}/{SCORECARD_ACTIVE_TOTAL}'


def evidence_script_ok(path, label):
    """磁盘存在性自检：证据脚本缺失时打印 WARN 并优雅回退（return False）。
    避免静默引用失效脚本（如已被删除/迁移的评分或审计脚本）。"""
    if not os.path.exists(path):
        print('WARN: 证据脚本 %s 不存在于磁盘，跳过加载（%s）' % (os.path.basename(path), label),
              file=sys.stderr)
        return False
    return True


def load_reports():
    if not os.path.isdir(REPORTS_DIR):
        return []
    reports = []
    for fpath in glob.glob(os.path.join(REPORTS_DIR, '*_status.json')):
        try:
            with open(fpath, encoding='utf-8') as f:
                data = json.load(f)
                data['_file'] = os.path.basename(fpath)
                reports.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    return reports


def load_scorecard():
    """R24: 优先加载 scorecard.py --json 输出（融合评分卡 V2: 三主线机器实测）。
    存在即用，旧 reports 自评数据仅作回退。"""
    _p = os.path.join(EVAL_DIR, 'scorecard.py')
    if not evidence_script_ok(_p, '聚合评分卡'):
        return None
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, os.path.join(EVAL_DIR, 'scorecard.py'), '--json'],
            capture_output=True, text=True, encoding='utf-8', timeout=600,
            cwd=PROJECT_DIR, errors='replace')
        if r.returncode != 0:
            print('WARN: scorecard 运行失败, 回退旧 reports', file=sys.stderr)
            return None
        data = json.loads(r.stdout)
        # 兼容 v1（旧三线）、v2（融合三主线）、track200（六线全评）
        if data.get('schema') not in ('fenjue-scorecard-v1', 'fenjue-scorecard-v2',
                                      'fenjue-track200-v1'):
            return None
        return data
    except Exception as e:
        print('WARN: scorecard 加载失败 (%s), 回退旧 reports' % e, file=sys.stderr)
        return None


def load_gate():
    """R197: 单一真相源门禁（verify_truth_consistency.py --json, C1~C12）。
    失败时退出码 1 但 JSON 仍输出；解析 stdout 末尾 JSON 块。
    返回 {all_pass, results:[{id,desc,status,detail}]} 或 None（无 JSON 输出/异常）。"""
    try:
        import subprocess
        import re as _re
        _p = os.path.join(EVAL_DIR, 'verify_truth_consistency.py')
        if not evidence_script_ok(_p, '门禁 C1~C12'):
            return None
        r = subprocess.run(
            [sys.executable, _p, '--json'],
            capture_output=True, text=True, encoding='utf-8', timeout=900,
            cwd=PROJECT_DIR, errors='replace')
        out = r.stdout
        m = _re.search(r'(\{\s*"schema":\s*"fenjue-truth-consistency-v1".*\})', out, _re.S)
        if not m:
            print('WARN: 门禁(verify_truth_consistency)无 JSON 输出 (rc=%d)' % r.returncode, file=sys.stderr)
            return None
        data = json.loads(m.group(1))
        if not isinstance(data.get('results'), list):
            return None
        return data
    except Exception as e:
        print('WARN: 门禁加载失败 (%s)' % e, file=sys.stderr)
        return None


def pick_latest(reports):
    """按 (维度, 轮次) 取最新时间戳的报告条目"""
    latest = {}
    for r in reports:
        scores = r.get('scores', {})
        for dim, info in scores.items():
            if not isinstance(info, dict):
                continue
            key = (dim, info.get('round', ''))
            ts = r.get('ts', '')
            if key not in latest or ts > latest[key][0]:
                latest[key] = (ts, info, r.get('notes', ''), r.get('session', ''))
    return latest


def load_three_door():
    """R158: 三门审计已取消, 改读 Codex 独立评分（eval/codex_audit_scores.json）。
    返回 dict 或 None。"""
    p = os.path.join(EVAL_DIR, 'codex_audit_scores.json')
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print('WARN: three_door_scores.json 读取失败 (%s)' % e, file=sys.stderr)
        return None


def load_lessons_hitrate():
    """主线④: 读取 lessons 命中率（eval/lessons_hitrate.py --json 实跑）。
    返回 dict 或 None。"""
    try:
        import subprocess
        _p = os.path.join(EVAL_DIR, 'lessons_hitrate.py')
        if not evidence_script_ok(_p, 'lessons 命中率'):
            return None
        r = subprocess.run(
            [sys.executable, _p, '--json'],
            capture_output=True, text=True, encoding='utf-8', timeout=300,
            cwd=PROJECT_DIR, errors='replace')
        if r.returncode != 0:
            print('WARN: lessons_hitrate 运行失败', file=sys.stderr)
            return None
        # --json 输出在 stdout 末尾（非 JSON 行是打印报告）
        out = r.stdout
        # 提取最后一个完整的 {"schema": ...} JSON 块（正则匹配, 防报告行括号干扰; { 后允许换行缩进）
        import re
        m = re.search(r'(\{\s*"schema":\s*"fenjue-lessons-hitrate-v1".*\})', out, re.S)
        if not m:
            print('WARN: lessons_hitrate 无 JSON 输出 (stdout len=%d)' % len(out), file=sys.stderr)
            return None
        return json.loads(m.group(1))
    except Exception as e:
        print('WARN: lessons_hitrate 加载失败 (%s)' % e, file=sys.stderr)
        return None


def load_memory_recall():
    """主线②补强（P1E-1）: 记忆召回基准实跑（eval/memory_recall_eval.py --json）。
    纯 JSON 输出直接解析；失败返回 None 不阻断聚合。"""
    try:
        import subprocess
        _p = os.path.join(EVAL_DIR, 'memory_recall_eval.py')
        if not evidence_script_ok(_p, '记忆召回基准'):
            return None
        r = subprocess.run(
            [sys.executable, _p, '--json'],
            capture_output=True, text=True, encoding='utf-8', timeout=300,
            cwd=PROJECT_DIR, errors='replace')
        if r.returncode != 0:
            print('WARN: memory_recall_eval 运行失败', file=sys.stderr)
            return None
        data = json.loads(r.stdout)
        return data if data.get('schema') == 'fenjue-memory-recall-v1' else None
    except Exception as e:
        print('WARN: memory_recall_eval 加载失败 (%s)' % e, file=sys.stderr)
        return None


def load_cross_layer():
    """R115 跨端四层终检 —— R209 已退役：cross_layer_audit.py 归档至 archive/retired_R209/。

    职责由 verify_truth_consistency（C1-C13）与 routing_index_health 承接；
    保留函数返回 None 以维持 STATUS 结构稳定（渲染端 if cross_layer: 守卫自动跳过该节）。"""
    print('INFO: cross_layer_audit 已于 R209 退役归档，本项跳过', file=sys.stderr)
    return None


def load_pread():
    """R127: 开场预读门禁（eval/lessons_pread_audit.py --json 实跑）。"""
    try:
        import subprocess
        _p = os.path.join(EVAL_DIR, 'lessons_pread_audit.py')
        if not evidence_script_ok(_p, '开场预读门禁'):
            return None
        r = subprocess.run(
            [sys.executable, _p, '--days', '7', '--json'],
            capture_output=True, text=True, encoding='utf-8', timeout=60,
            cwd=PROJECT_DIR, errors='replace')
        if r.returncode != 0:
            print('WARN: lessons_pread_audit 运行失败', file=sys.stderr)
            return None
        return json.loads(r.stdout)
    except Exception as e:
        print('WARN: lessons_pread_audit 加载失败 (%s)' % e, file=sys.stderr)
        return None


def load_attention_sim():
    """主线⑤: 注意力税补充模拟（audit/attention_sim.py --json 实跑）。"""
    try:
        import subprocess
        _p = os.path.join(PROJECT_DIR, 'audit', 'attention_sim.py')
        if not evidence_script_ok(_p, '注意力税模拟'):
            return None
        r = subprocess.run(
            [sys.executable, _p, '--json'],
            capture_output=True, text=True, encoding='utf-8', timeout=300,
            cwd=PROJECT_DIR, errors='replace')
        if r.returncode != 0:
            print('WARN: attention_sim 运行失败', file=sys.stderr)
            return None
        return json.loads(r.stdout)
    except Exception as e:
        print('WARN: attention_sim 加载失败 (%s)' % e, file=sys.stderr)
        return None


def load_skill_usage_stats():
    """主线⑥: 前置使用率采样（eval/skill_usage_stats.py --json 实跑）。"""
    try:
        import subprocess
        _p = os.path.join(EVAL_DIR, 'skill_usage_stats.py')
        if not evidence_script_ok(_p, '使用率采样'):
            return None
        r = subprocess.run(
            [sys.executable, _p, '--json'],
            capture_output=True, text=True, encoding='utf-8', timeout=120,
            cwd=PROJECT_DIR, errors='replace')
        if r.returncode != 0:
            print('WARN: skill_usage_stats 运行失败', file=sys.stderr)
            return None
        return json.loads(r.stdout)
    except Exception as e:
        print('WARN: skill_usage_stats 加载失败 (%s)' % e, file=sys.stderr)
        return None


def load_defect_tracking():
    """R166-U4: 缺陷闭环台账（eval/defect_tracking.json, fenjue-defect-tracking-v1）。
    返回 dict 或 None（缺失/损坏时不阻断聚合，仅缺缺陷闭环行）。"""
    p = os.path.join(EVAL_DIR, 'defect_tracking.json')
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        if data.get('schema') != 'fenjue-defect-tracking-v1':
            print('WARN: defect_tracking.json schema 不识别', file=sys.stderr)
            return None
        return data
    except Exception as e:
        print('WARN: defect_tracking.json 读取失败 (%s)' % e, file=sys.stderr)
        return None



from status_report import generate_status  # R208 O-4: STATUS 正文生成模块


def gate_fingerprint(gate):
    """门禁结果指纹（all_pass + 每项 id/status/detail），供两遍回填比对。"""
    if not isinstance(gate, dict):
        return None
    items = tuple((r.get('id'), r.get('status'), r.get('detail'))
                  for r in gate.get('results', []) if isinstance(r, dict))
    return (bool(gate.get('all_pass')), items)


def emit_status(latest, dry, scorecard, three_door, lessons_hitrate, cross_layer,
                pread, tracking, gate, attention_sim, skill_usage, memory_recall=None):
    generate_status(latest, dry_run=dry, scorecard=scorecard, three_door=three_door,
                    lessons_hitrate=lessons_hitrate, cross_layer=cross_layer,
                    pread=pread, tracking=tracking, gate=gate,
                    attention_sim=attention_sim, skill_usage=skill_usage,
                    memory_recall=memory_recall)


if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    reports = load_reports()
    latest = pick_latest(reports)
    # P1-1: 九路独立数据源并行 fan-out —— 原全串行冷启动墙钟=各子进程之和，
    # 改后=最慢单项（各 loader 内部已自捕获异常返回 None，fan-out 不引入新失败面）
    from concurrent.futures import ThreadPoolExecutor
    loaders = {
        'scorecard': load_scorecard,
        'three_door': load_three_door,
        'lessons_hitrate': load_lessons_hitrate,
        'cross_layer': load_cross_layer,
        'pread': load_pread,
        'tracking': load_defect_tracking,
        'gate': load_gate,
        'attention_sim': load_attention_sim,
        'skill_usage': load_skill_usage_stats,
        'memory_recall': load_memory_recall,
    }
    with ThreadPoolExecutor(max_workers=len(loaders)) as _pool:
        _futs = {k: _pool.submit(fn) for k, fn in loaders.items()}
        _res = {k: f.result() for k, f in _futs.items()}
    scorecard = _res['scorecard']
    three_door = _res['three_door']
    lessons_hitrate = _res['lessons_hitrate']
    cross_layer = _res['cross_layer']
    pread = _res['pread']
    tracking = _res['tracking']
    gate = _res['gate']
    attention_sim = _res['attention_sim']
    skill_usage = _res['skill_usage']
    memory_recall = _res['memory_recall']
    # 门禁编号范围动态取（原硬编码 C1~C18：门禁已增到 C29 而此处从未回扫，同 generate_index R278 根因）
    _gmax = derive_max_gate_id()
    _gsfx = 'C1~C%d' % _gmax if _gmax else '门禁编号解析失败'
    src_label = '门禁(%s,唯一真相源)' % _gsfx
    if gate:
        src_label = '门禁(%s)' % _gsfx
    elif three_door:
        src_label = 'scorecard + Codex 独立审计'
    elif scorecard:
        src_label = 'scorecard(机器实测)'
    print('聚合 %d 份报告 → %d 条最新记录 | 数据源: %s' % (len(reports), len(latest), src_label))
    emit_status(latest, dry, scorecard, three_door, lessons_hitrate, cross_layer,
                pread, tracking, gate, attention_sim, skill_usage, memory_recall)
    if dry:
        print('\n[DRY RUN] 未实际写入 STATUS.md')
        sys.exit(0)
    # R272 两遍门禁回填：C16 的判据面是 STATUS 家族自身，单次生成只能拿到「上一版」的判定
    # （实测：第 N 版 STATUS 内嵌的 ❌ 实为第 N-1 版的 C16 结果，与当场 verify 不符 = 假失败）。
    # 写盘后重跑门禁，判定变化则以新结果重新生成；迭代上限 2 轮，防自指震荡。
    for _round in range(1, 3):
        gate2 = load_gate()
        if gate2 is None:
            print('WARN: 门禁二次核验无输出，保留首次判定（未回填）', file=sys.stderr)
            break
        if gate_fingerprint(gate2) == gate_fingerprint(gate):
            break
        print('门禁二次核验: 判定更新（第 %d 轮回填）→ %s' % (
            _round, 'PASS' if gate2.get('all_pass') else 'FAIL'))
        gate = gate2
        emit_status(latest, False, scorecard, three_door, lessons_hitrate, cross_layer,
                    pread, tracking, gate, attention_sim, skill_usage, memory_recall)
    else:
        print('WARN: 门禁两轮回填后仍与上一轮不同，保留最后一次结果（可能为自指残留）',
              file=sys.stderr)
