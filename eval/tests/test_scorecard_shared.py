#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_scorecard_shared.py — scorecard_shared 计分基础设施单测（R208 O-5 补测）。

覆盖范围: run / _script_target / 缺失哨兵判定 / dead_script_part /
          mark_missing_if_dead / load_func_checks（本文件补测后 shared 50%→90%）。
注意: _FUNC_CACHE 为模块级缓存，load_func_checks 用例间必须重置，否则缓存污染。
"""
import sys
import types

import pytest

import scorecard_shared as ss


@pytest.fixture(autouse=True)
def reset_func_cache():
    """每个用例前重置模块级 _FUNC_CACHE（防跨用例缓存污染）。"""
    ss._FUNC_CACHE = None
    yield
    ss._FUNC_CACHE = None


# ============ _script_target 参数解析（纯函数） ============

def test_script_target_python_script():
    assert ss._script_target([sys.executable, 'eval/foo.py', '--json']) == 'eval/foo.py'


def test_script_target_skips_flags_and_module():
    # -m 后为模块名（无分隔符/脚本后缀），不判为脚本 → None
    assert ss._script_target([sys.executable, '-m', 'pytest']) is None


def test_script_target_powershell_file():
    cmd = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
           '-File', r'C:\repo\a.ps1']
    assert ss._script_target(cmd) == r'C:\repo\a.ps1'


def test_script_target_powershell_command():
    # -Command 为内联代码，无文件可检 → None
    assert ss._script_target(['powershell.exe', '-Command', 'Write-Host x']) is None


def test_script_target_empty_and_none():
    assert ss._script_target([]) is None
    assert ss._script_target(None) is None


# ============ 缺失哨兵判定 ============

def test_is_script_missing_true_and_name():
    out = '__SCRIPT_MISSING__:triple_diff.py'
    assert ss.is_script_missing(out)
    assert ss.missing_script_name(out) == 'triple_diff.py'


def test_is_script_missing_false():
    assert not ss.is_script_missing('正常输出 [PASS]')
    assert not ss.is_script_missing(None)


def test_dead_script_part():
    part = ss.dead_script_part(10, 'foo.py')
    # 关键语义断言（detail 为多行文案，不做整字典相等，避免脆测）
    assert part['score'] == 0 and part['max'] == 10 and part['unavailable']
    assert part['evidence'] == 'foo.py'
    assert part['evidence_fingerprint'] == 'dead-script:foo.py'
    assert 'DATA UNAVAILABLE' in part['detail']


def test_mark_missing_if_dead_marks_all():
    parts = {}
    mapping = {'a': 5, 'b': 10}
    marked = ss.mark_missing_if_dead('__SCRIPT_MISSING__:x.py', parts, mapping)
    assert marked
    assert parts['a']['unavailable'] and parts['b']['unavailable']
    assert parts['a']['max'] == 5 and parts['b']['max'] == 10


def test_mark_missing_if_dead_noop_on_normal():
    parts = {}
    assert not ss.mark_missing_if_dead('[PASS]', parts, {'a': 5})
    assert parts == {}


# ============ run（subprocess 包装，mock 外部调用） ============

def test_run_returns_stdout_plus_stderr(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured['cmd'] = cmd
        captured['kwargs'] = kwargs
        return types.SimpleNamespace(stdout='A', stderr='B')

    monkeypatch.setattr(ss.subprocess, 'run', fake_run)
    # target=None（-m 模块名）→ 不查磁盘直接 subprocess
    out = ss.run([sys.executable, '-m', 'pytest'])
    assert out == 'AB'
    assert captured['kwargs']['timeout'] == 180


def test_run_returns_missing_sentinel_when_script_absent(monkeypatch):
    monkeypatch.setattr(ss.os.path, 'exists', lambda p: False)

    def fake_run(cmd, **kwargs):
        raise AssertionError('存在性自检应拦截，不应到达 subprocess')

    monkeypatch.setattr(ss.subprocess, 'run', fake_run)
    out = ss.run([sys.executable, 'eval/ghost_script.py'])
    assert out == '__SCRIPT_MISSING__:ghost_script.py'


def test_run_fail_closed_on_exception(monkeypatch):
    def boom(cmd, **kwargs):
        raise FileNotFoundError('powershell not found')

    monkeypatch.setattr(ss.subprocess, 'run', boom)
    out = ss.run([sys.executable, '-m', 'pytest'])
    assert out.startswith('RUN_FAILED:')


# ============ load_func_checks（功能化检查，mock run 返回） ============

_JSON_OK = ('\n{ "schema": "fenjue-functional-dims-v1",'
            ' "watcher": {"ok_n": 3}, "coverage": {"hit_domains": 13, "total_domains": 13} }\n')


def test_load_func_checks_parses_json(monkeypatch):
    monkeypatch.setattr(ss, 'run', lambda *a, **k: _JSON_OK)
    cache = ss.load_func_checks()
    assert cache['schema'] == 'fenjue-functional-dims-v1'
    assert cache['watcher']['ok_n'] == 3


def test_load_func_checks_missing_script(monkeypatch):
    # R208 O-5 续修后：哨兵分支短路返回，reason 必须保留脚本名（此前被空输出分支覆盖为死代码）
    monkeypatch.setattr(ss, 'run',
                        lambda *a, **k: '__SCRIPT_MISSING__:functional_dim_checks.py')
    cache = ss.load_func_checks()
    assert cache.get('unavailable') is True
    assert 'functional_dim_checks.py' in cache['reason']


def test_load_func_checks_unparseable_json(monkeypatch):
    # schema 头匹配但 JSON 语法非法 → fail-closed unavailable
    # （注: NaN/Infinity 会被 Python json.loads 默认接受，须用真正的语法错误构造）
    monkeypatch.setattr(ss, 'run',
                        lambda *a, **k: '{"schema": "fenjue-functional-dims-v1", "broken": }')
    cache = ss.load_func_checks()
    assert cache.get('unavailable')
    assert 'JSON 解析失败' in cache['reason']


def test_load_func_checks_empty_output(monkeypatch):
    monkeypatch.setattr(ss, 'run', lambda *a, **k: '')
    cache = ss.load_func_checks()
    assert cache.get('unavailable')
    assert '无输出/不可用' in cache['reason']


def test_load_func_checks_cached_only_runs_once(monkeypatch):
    calls = []

    def fake_run(*a, **k):
        calls.append(a)
        return _JSON_OK

    monkeypatch.setattr(ss, 'run', fake_run)
    ss.load_func_checks()
    ss.load_func_checks()
    assert len(calls) == 1, '_FUNC_CACHE 应保证只执行一次'