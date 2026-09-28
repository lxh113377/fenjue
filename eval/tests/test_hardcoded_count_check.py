# -*- coding: utf-8 -*-
"""D-107/D-109（对标轮十七续）：注册表硬编码计数漂移检查此前 0% 覆盖。

一手实测（覆盖率普查 `python -m coverage json`）：`eval/hardcoded_count_check.py` 64 条语句全缺，
而它的产出被 scorecard 消费（"声明计数 vs 实际清单长度"的对账）。
D-109 修的是它的**跳过口径**：旧实现 `if count_key not in d or list_key not in d: continue`
把「有声明计数、清单却被删了」也一并跳过 ⇒ 计数失去对照物就成了自由数字，还能静默过关。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'eval'))

import hardcoded_count_check as hc  # noqa: E402


def _w(tmp_path, name, payload):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return str(p)


# ---- platform-*.json 口径 ----

def test_consistent_counts_produce_no_drift(tmp_path):
    p = _w(tmp_path, 'platform-wb.json',
           {'skills_count': 3, 'skills_list': ['a', 'b', 'c'],
            'user_created_count': 1, 'user_created_skills': ['a']})
    drift, checked = hc.check_platform_file(p)
    assert drift == [] and checked == 1


def test_mismatched_declared_count_is_named(tmp_path):
    p = _w(tmp_path, 'platform-wb.json', {'skills_count': 9, 'skills_list': ['a', 'b']})
    drift, _ = hc.check_platform_file(p)
    assert len(drift) == 1
    d = drift[0]
    assert (d['field'], d['declared'], d['actual']) == ('skills_count', 9, 2)
    assert d['file'] == 'platform-wb.json'


def test_both_fields_absent_is_dynamic_not_drift(tmp_path):
    """两边都没有 = 该口径已动态化 ⇒ 跳过（这是合法态，不是漏判）。"""
    p = _w(tmp_path, 'platform-qd.json', {'version': 'v2', 'skills': {}})
    assert hc.check_platform_file(p) == ([], 1)


def test_list_without_declared_count_is_fine(tmp_path):
    p = _w(tmp_path, 'platform-qd.json', {'skills_list': ['a']})
    assert hc.check_platform_file(p)[0] == []


def test_declared_count_without_list_is_drift_not_skip(tmp_path):
    """D-109 回归锁：只留计数、删掉清单，不得当成"已动态化"静默过关。"""
    p = _w(tmp_path, 'platform-hm.json', {'skills_count': 167})
    drift, _ = hc.check_platform_file(p)
    assert len(drift) == 1 and drift[0]['actual'] is None
    assert '无从对账' in drift[0]['why']


def test_user_created_field_is_checked_too(tmp_path):
    p = _w(tmp_path, 'platform-tc.json',
           {'skills_count': 2, 'skills_list': ['a', 'b'],
            'user_created_count': 5, 'user_created_skills': ['a']})
    drift, _ = hc.check_platform_file(p)
    assert [d['field'] for d in drift] == ['user_created_count']


# ---- disk_manifest.json ----

def test_disk_manifest_consistent_and_drift(tmp_path):
    ok = _w(tmp_path, 'disk_manifest.json', {'count': 2, 'skills': ['a', 'b']})
    assert hc.check_disk_manifest(ok) == ([], 1)
    bad = _w(tmp_path, 'disk_manifest2.json', {'count': 3, 'skills': ['a']})
    drift, checked = hc.check_disk_manifest(bad)
    assert checked == 1 and drift[0]['field'] == 'count'
    assert (drift[0]['declared'], drift[0]['actual']) == (3, 1)


def test_disk_manifest_without_count_keys_is_skipped(tmp_path):
    p = _w(tmp_path, 'disk_manifest3.json', {'skills': ['a']})
    assert hc.check_disk_manifest(p) == ([], 0)


# ---- skill_content 域桶 ----

def _content(tmp_path, monkeypatch, ids, domains):
    root = tmp_path / 'skill_content'
    root.mkdir(exist_ok=True)
    (root / 'skill_ids.json').write_text(json.dumps(ids, ensure_ascii=False), encoding='utf-8')
    for name, items in domains.items():
        (root / (name + '.json')).write_text(
            json.dumps({'skills': items}, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(hc, 'SKILL_CONTENT', str(root))
    return root


def test_skill_content_totals_match(tmp_path, monkeypatch):
    _content(tmp_path, monkeypatch, ['a', 'b', 'c'],
             {'routing': ['a', 'b'], 'misc': ['c']})
    assert hc.check_skill_content() == ([], 1)


def test_skill_content_domain_less_than_registry_is_drift(tmp_path, monkeypatch):
    _content(tmp_path, monkeypatch, ['a', 'b', 'c'], {'routing': ['a']})
    drift, checked = hc.check_skill_content()
    assert checked == 1 and drift[0]['field'] == 'total_skills'
    assert (drift[0]['declared'], drift[0]['actual']) == (3, 1)


def test_missing_registry_means_zero_checked(tmp_path, monkeypatch):
    """派生面不存在（CI/异机没有 skill_content）= 无对象可判，checked 记 0 而非判漂移。"""
    monkeypatch.setattr(hc, 'SKILL_CONTENT', str(tmp_path / 'nowhere'))
    assert hc.check_skill_content() == ([], 0)


def test_broken_domain_json_is_skipped_not_fatal(tmp_path, monkeypatch):
    root = _content(tmp_path, monkeypatch, ['a'], {})
    (root / 'bad.json').write_text('{ 半截', encoding='utf-8')
    (root / 'good.json').write_text(json.dumps({'skills': ['a']}), encoding='utf-8')
    assert hc.check_skill_content() == ([], 1)


# ---- main 聚合 + 真实面 ----

def test_main_aggregates_and_reports_json(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(hc, 'REGISTRY_DIR', str(tmp_path))
    _w(tmp_path, 'platform-a.json', {'skills_count': 1, 'skills_list': ['a']})
    _w(tmp_path, 'platform-b.json', {'skills_count': 7, 'skills_list': ['a']})
    monkeypatch.setattr(hc, 'check_skill_content', lambda: ([], 1))
    assert hc.main() == 1                      # 有漂移 → exit 1
    out = json.loads(capsys.readouterr().out)
    assert out['ok'] is False and out['drift_count'] == 1
    assert out['checked'] == 3                 # 2 个 platform + 1 个 skill_content


def test_main_exit_zero_when_everything_consistent(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(hc, 'REGISTRY_DIR', str(tmp_path))
    _w(tmp_path, 'platform-a.json', {'skills_count': 1, 'skills_list': ['a']})
    monkeypatch.setattr(hc, 'check_skill_content', lambda: ([], 1))
    assert hc.main() == 0
    assert json.loads(capsys.readouterr().out)['ok'] is True


def test_real_registry_face_has_no_count_drift():
    """现状锁：本轮把"有计数无清单"也判成漂移之后，真实注册表面必须仍然全对得上。"""
    rc = hc.main()
    assert rc == 0, '真实注册表出现计数漂移（先跑 build_registry/build_indexes 再重测）'
