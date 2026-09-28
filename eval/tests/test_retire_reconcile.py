# -*- coding: utf-8 -*-
"""D-101/D-102（对标轮十七）：第 9 闸「退役防回滚对账」的瞎眼面 —— fail-closed 化并补测。

一手实测（本轮覆盖率普查）：`eval/retire_reconcile.py` 115 条语句 **0% 覆盖**，而它是本地
第 9 道闸（`python -c "import sys;sys.path.insert(0,'eval');import pre_commit_hooks as p;print('retire-reconcile' in p.GATE_NAMES)"` = True）。
读源码即发现形状缺陷：注册表/索引读不到时 `except Exception: return set()` ⇒ 对账面变成空集 ⇒
"零回滚" ⇒ **判 PASS**（R247 反例：面塌了被当成干净）。本文件同时钉住修复后的行为与旧洞的边界。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'eval'))

import retire_reconcile as rr  # noqa: E402


def _sources(monkeypatch, tmp_path, retired=('old-skill',), registry=('live-skill',),
             index=('live-skill',), policy=None):
    """把三方数据源全部换成 tmp 夹具（不碰真实注册表与派生索引）。"""
    tc = tmp_path / 'truth_constants.json'
    tc.write_text(json.dumps({'retired_skills': list(retired),
                              'retire_policy': policy or {}}, ensure_ascii=False),
                  encoding='utf-8')
    reg = tmp_path / 'unified-skills-index.json'
    reg.write_text(json.dumps({'skills': {n: {'path': f'skill/{n}'} for n in registry}},
                              ensure_ascii=False), encoding='utf-8')
    content = tmp_path / 'skill_content'
    content.mkdir(exist_ok=True)
    (content / 'skill_ids.json').write_text(json.dumps(list(index), ensure_ascii=False),
                                            encoding='utf-8')
    monkeypatch.setattr(rr, 'TC_JSON', str(tc))
    monkeypatch.setattr(rr, 'REGISTRY_FILE', str(reg))
    monkeypatch.setattr(rr, 'SKILL_CONTENT', str(content))
    return tc, reg, content


# ── 正例 ──

def test_clean_three_way_passes(monkeypatch, tmp_path):
    _sources(monkeypatch, tmp_path)
    r = rr.reconcile()
    assert r['passed'] is True and r['rollback_total'] == 0
    assert r['retired_count'] == 1 and r['index_available'] is True


def test_registry_rollback_is_named_and_blocks(monkeypatch, tmp_path):
    _sources(monkeypatch, tmp_path, registry=('live-skill', 'old-skill'))
    r = rr.reconcile()
    assert r['registry_rollback'] == ['old-skill'] and r['passed'] is False
    assert r['block_ingest'] is True and r['rollback_total'] == 1


def test_index_rollback_counted_separately(monkeypatch, tmp_path):
    _sources(monkeypatch, tmp_path, index=('live-skill', 'old-skill'))
    r = rr.reconcile()
    assert r['index_rollback'] == ['old-skill'] and r['registry_rollback'] == []
    assert r['passed'] is False


def test_threshold_tolerates_declared_transitions(monkeypatch, tmp_path):
    _sources(monkeypatch, tmp_path, registry=('old-skill',), policy={'threshold': 1})
    r = rr.reconcile()
    assert r['threshold'] == 1 and r['rollback_total'] == 1 and r['passed'] is True


# ── D-102：面塌了不得冒充"零回滚"（R247）──

def test_unreadable_registry_is_fail_closed_not_zero_rollback(monkeypatch, tmp_path):
    _sources(monkeypatch, tmp_path)
    reg = tmp_path / 'unified-skills-index.json'
    reg.write_text('{ 半截 JSON', encoding='utf-8')
    r = rr.reconcile()
    assert r['passed'] is False and r['retired_count'] == -1
    assert '注册表' in r['error']


def test_empty_registry_face_is_fail_closed(monkeypatch, tmp_path):
    """`skills: {}` 与"读不到"同形：黑名单对账没有任何对象 ⇒ 瞎，不是干净。"""
    _sources(monkeypatch, tmp_path)
    (tmp_path / 'unified-skills-index.json').write_text('{"skills": {}}', encoding='utf-8')
    with pytest.raises(rr.TruthSourceError):
        rr.get_registry_skills()


def test_missing_registry_file_is_fail_closed(monkeypatch, tmp_path):
    _sources(monkeypatch, tmp_path)
    os.remove(tmp_path / 'unified-skills-index.json')
    with pytest.raises(rr.TruthSourceError):
        rr.get_registry_skills()


def test_unreadable_truth_source_is_fail_closed(monkeypatch, tmp_path):
    _sources(monkeypatch, tmp_path)
    (tmp_path / 'truth_constants.json').write_text('nope', encoding='utf-8')
    r = rr.reconcile()
    assert r['passed'] is False and r['retired_count'] == -1 and '真相源' in r['error']


def test_missing_index_face_is_declared_not_silently_clean(monkeypatch, tmp_path):
    """CI/异机没有 skill_content 是合法态，但必须写进 index_available，不许与"索引干净"同形。"""
    _sources(monkeypatch, tmp_path)
    os.remove(tmp_path / 'skill_content' / 'skill_ids.json')
    r = rr.reconcile()
    assert r['index_available'] is False and r['passed'] is True


# ── 索引面解析形状（覆盖面反证：三种历史形状都要能数出来）──

@pytest.mark.parametrize('payload,expect', [
    (['a', 'b'], {'a', 'b'}),
    ([{'id': 'a'}, {'name': 'b'}, {'other': 'x'}], {'a', 'b', ''}),
    ({'a': {}, 'b': {}}, {'a', 'b'}),
])
def test_index_face_accepts_all_three_shapes(monkeypatch, tmp_path, payload, expect):
    _sources(monkeypatch, tmp_path)
    (tmp_path / 'skill_content' / 'skill_ids.json').write_text(
        json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    assert rr.get_index_skills() == expect


# ── 退出码：passed / block_ingest 两维都要判（策略分叉不许糊）──

def _run_main(monkeypatch, tmp_path, result):
    monkeypatch.setattr(rr, 'reconcile', lambda: result)
    monkeypatch.setattr(sys, 'argv', ['retire_reconcile.py'])
    return rr.main()


def test_exit_zero_when_clean(monkeypatch, tmp_path):
    assert _run_main(monkeypatch, tmp_path, {
        'retired_count': 3, 'registry_rollback': [], 'index_rollback': [],
        'rollback_total': 0, 'threshold': 0, 'block_ingest': True,
        'frequency': 'monthly', 'index_available': True, 'passed': True}) == 0


def test_exit_one_when_rollback_and_block(monkeypatch, tmp_path):
    assert _run_main(monkeypatch, tmp_path, {
        'retired_count': 3, 'registry_rollback': ['x'], 'index_rollback': [],
        'rollback_total': 1, 'threshold': 0, 'block_ingest': True,
        'frequency': 'monthly', 'index_available': True, 'passed': False}) == 1


def test_warn_only_policy_does_not_block(monkeypatch, tmp_path):
    """block_ingest=False 是 owner 明示的"只告警"档：红要报出来，但不拦入库。"""
    assert _run_main(monkeypatch, tmp_path, {
        'retired_count': 3, 'registry_rollback': ['x'], 'index_rollback': ['y'],
        'rollback_total': 2, 'threshold': 0, 'block_ingest': False,
        'frequency': 'weekly', 'index_available': True, 'passed': False}) == 0


# ── 真盘面现状锁：这台机器上三方对账确实干净 ──

def test_real_three_way_face_is_currently_clean():
    r = rr.reconcile()
    assert r['passed'] is True, f'真实对账判红：{r["registry_rollback"][:5]} {r["index_rollback"][:5]}'
    assert r['retired_count'] > 0, '黑名单为空 = 对账面无对象，本闸形同虚设（R247）'
