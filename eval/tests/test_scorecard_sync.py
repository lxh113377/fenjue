#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_scorecard_sync.py — 主线① score_sync 计分逻辑单测（R208 O-5）。

策略: mock scorecard_shared.run 按调用序列喂输出 + load_func_checks 返回可控 dict；
accuracy 维度用 tmp 目录构造 cross_platform_map.json / 磁盘 SKILL.md 做真实验证。
"""
import json
import os

import pytest

import scorecard_sync as syn


def make_runner(outs):
    """按调用序返回 mock 输出的 run 工厂（超出即断言失败）。"""
    it = iter(outs)
    calls = []

    def fab(*args, **kwargs):
        calls.append(args)
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(f'run 被调用次数超过提供的输出数: {len(outs)}')

    fab.calls = calls
    return fab


def setup_accuracy_env(monkeypatch, tmp_path):
    """构造 D1-3 accuracy 可控环境：注册表 1 端 + 磁盘 1 skill → 满分 8。"""
    reg_dir = tmp_path / 'skill' / 'registry'
    reg_dir.mkdir(parents=True)
    (reg_dir / 'cross_platform_map.json').write_text(
        json.dumps({"skills": {"skill_a": {"install_state": {"oc": True}}}}),
        encoding='utf-8')
    disk = tmp_path / 'disk_skills'
    (disk / 'skill_a').mkdir(parents=True)
    (disk / 'skill_a' / 'SKILL.md').write_text('---\nname: skill_a\n---\n', encoding='utf-8')
    monkeypatch.setattr(syn, 'PROJECT_DIR', str(tmp_path))
    monkeypatch.setattr(syn, 'SKILLS_DIR', str(disk))
    monkeypatch.setattr(syn, 'PLUGIN_SKILLS_DIR', str(tmp_path / 'no_such_oc_plugin'))


def test_score_sync_full_pass(monkeypatch, tmp_path):
    """六维正常输出 → 确定性总分。"""
    monkeypatch.setattr(syn, 'load_func_checks', lambda: {
        'watcher': {'ok_n': 3},
        'dataintegrity': {'health': 100},
    })
    # ① triple_diff '三方一致: 1'  ② sync-skills-bridge（无 ERROR）
    # ③ R219 新增 hardcoded_count_check（无漂移，保持满分）
    monkeypatch.setattr(syn, 'run', make_runner([
        '三方一致: 1',
        'sync OK 0 ERROR',
        json.dumps({'ok': True, 'checked': 6, 'drift_count': 0, 'drift': []}),
    ]))
    setup_accuracy_env(monkeypatch, tmp_path)

    # D1-1 junction：单端经 son 判定通过
    jp = str(tmp_path / 'ep_skills')
    os.makedirs(jp, exist_ok=True)
    monkeypatch.setattr(syn, 'JUNCTION_PATHS', [jp])
    monkeypatch.setattr(syn.os.path, 'islink', lambda p: True)

    # D1-2 基准 _base：DOMAIN json 含 2 个 skill → min(1,2)/2*10 = 5.0
    content = tmp_path / 'content'
    content.mkdir()
    (content / 'domain.json').write_text(json.dumps({"skills": [1, 2]}), encoding='utf-8')
    import config
    monkeypatch.setattr(config, 'SKILL_CONTENT', str(content))

    res = syn.score_sync()
    assert res['line'] == '主线① 跨平台skill互通同步'
    assert res['parts']['junction']['score'] == 12.0
    assert res['parts']['registry']['score'] == 5.0
    assert res['parts']['accuracy']['score'] == 8
    assert res['parts']['watcher']['score'] == 6
    assert res['parts']['sync']['score'] == 6
    assert res['parts']['dataintegrity']['score'] == 8
    assert res['total'] == pytest.approx(45.0)


def test_score_sync_script_missing_isolates_registry(monkeypatch, tmp_path):
    """triple_diff 证据脚本缺失 → registry 隔离计分（不静默 0 分）。"""
    monkeypatch.setattr(syn, 'load_func_checks', lambda: {
        'watcher': {'ok_n': 0},
        'dataintegrity': {'health': 0},
    })
    monkeypatch.setattr(syn, 'run', make_runner(
        ['__SCRIPT_MISSING__:triple_diff.py', '普通 sync 输出']))
    setup_accuracy_env(monkeypatch, tmp_path)
    content = tmp_path / 'content'
    content.mkdir()
    (content / 'd.json').write_text(json.dumps({"skills": [1]}), encoding='utf-8')
    import config
    monkeypatch.setattr(config, 'SKILL_CONTENT', str(content))

    res = syn.score_sync()
    assert res['parts']['registry']['unavailable'] is True
    assert res['parts']['registry']['score'] == 0
    assert 'DATA UNAVAILABLE' in res['parts']['registry']['detail']
    # 其余维度不受哨兵影响
    assert res['parts']['accuracy']['score'] == 8