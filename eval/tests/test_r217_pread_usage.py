"""R216-03: lessons_pread_audit 机器落账数据源（jsonl）单元测试。

覆盖：scan_usage 容错（注释头/坏行/日期过滤/缺失文件）、--json 向后兼容键、
declared_missing 断链旗标自洽。jsonl 路径经参数注入，零生产污染。
"""
import json
import os
import subprocess
import sys

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

from lessons_pread_audit import scan_usage  # noqa: E402
import truth_constants as t  # noqa: E402
import verify_truth_consistency as vtc  # noqa: E402

TODAY = '2026-09-06'

# 真实使用台账住在 GM（外盘 + gitignored 语义），干净签出/CI 上必然不在场 ⇒ 「今日实账 ≥1」
# 这一面**不可测**。P0-31：缺面即 skip 并写明理由，禁止把「量具不在」跑成真缺陷红。
_USAGE_FACE = os.path.join(t.GLOBAL_MEMORY_ROOT, 'meta', 'lessons_usage.jsonl')
_needs_usage_ledger = pytest.mark.skipif(
    not (vtc.external_root_reachable(t.GLOBAL_MEMORY_ROOT) and os.path.isfile(_USAGE_FACE)),
    reason='真实使用台账（GM meta/lessons_usage.jsonl）不在本环境，本机实账面不可测（P0-31）')


def _write(tmp_path, lines):
    p = tmp_path / 'lessons_usage.jsonl'
    p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(p)


def test_scan_usage_tolerates_header_and_bad_lines(tmp_path):
    p = _write(tmp_path, [
        '# schema_v=1  (data source header)',
        json.dumps({'date': TODAY, 'session': 's1', 'loaded': ['a'], 'used': ['a']}, ensure_ascii=False),
        'THIS IS NOT JSON',
        json.dumps({'date': TODAY, 'session': 's2', 'loaded': [], 'used': []}, ensure_ascii=False),
    ])
    rows, bad, ok = scan_usage(path=p, cutoff='2026-09-01')
    assert ok is True and bad == 1 and len(rows) == 2
    assert rows[0]['session'] == 's1'


def test_scan_usage_cutoff_and_missing_date(tmp_path):
    p = _write(tmp_path, [
        json.dumps({'date': '2026-08-01', 'session': 'old', 'loaded': ['x']}),
        json.dumps({'session': 'nodate', 'loaded': ['y']}),
        json.dumps({'date': TODAY, 'session': 'new', 'loaded': ['z']}),
    ])
    rows, bad, ok = scan_usage(path=p, cutoff='2026-09-01')
    assert [r['session'] for r in rows] == ['new'] and bad == 0 and ok is True


def test_scan_usage_missing_file(tmp_path):
    rows, bad, ok = scan_usage(path=str(tmp_path / 'nope.jsonl'))
    assert (rows, bad, ok) == ([], 0, False)


@_needs_usage_ledger
def test_audit_json_v2_backward_compat_and_flag():
    r = subprocess.run(
        [sys.executable, os.path.join(EVAL_DIR, 'lessons_pread_audit.py'),
         '--days', '7', '--json'],
        capture_output=True, text=True, encoding='utf-8',
        cwd=EVAL_DIR, errors='replace', timeout=120)
    assert r.returncode == 0
    d = json.loads(r.stdout)
    # 旧键全保留（aggregate_status.load_pread 消费面不破）
    for k in ('pread_declared', 'pread_avg_hits', 'skill_declared',
              'skill_avg', 'memory_declared', 'memory_avg', 'rows'):
        assert k in d
    # v2 新键；今日实账（本会话 record 过 ≥1 条）
    assert d['schema'] == 'fenjue-lessons-pread-audit-v2'
    assert d['usage_source_ok'] is True
    assert isinstance(d['usage_events'], int) and d['usage_events'] >= 1
    assert d['usage_bad_lines'] == 0
    # 断链旗标与底层逻辑自洽（不硬编码实时值，防并行会话写声明行导致 flake）
    assert d['declared_missing'] == (d['pread_declared'] == 0 and d['usage_events'] > 0)
