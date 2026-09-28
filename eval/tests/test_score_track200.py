#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_score_track200.py — track_200 六线全评模块单测（R198.10）"""
import sys
import os

import pytest
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from score_track200 import (  # noqa: E402
    LINE_TOTAL, TOTAL, PASS_LINE, run_json, scale_legacy,
    score_line4, score_line5, score_line6, run_track200,
)

# D-66（对标轮十）：**默认链一个真实资产子进程都不许留**。
# `score_line4/5` 与 `run_track200()` 内部都会 `subprocess` 调重脚本（lessons_hitrate /
# attention_sim 冷态 240 s），预算 90 s 而 pytest 每例天花板 120 s ⇒ 机器空闲时刚好过、
# 并发负载时刚好不过。实证：同一棵树直跑 `pre_commit_hooks.py` rc=0（16/16 PASS），
# 而在 `git commit` 上下文里两次跑出 `pre-commit FAIL: pytest` —— **判据结果随执行上下文
# 翻转即判据自身失效**，验收条件因此改为"在提交上下文内连跑通过"，不再承认"直跑绿"。
_heavy_face = pytest.mark.skipif(
    os.environ.get("FENJUE_RUN_INTEGRATION") != "1",
    reason="真实资产子进程档（冷态分钟级、耗时随负载漂移），默认链不跑；"
           "FENJUE_RUN_INTEGRATION=1 显式开启（D-66）")


class TestScaleLegacy:
    def test_normal_scale(self):
        r = scale_legacy({'total': 50.0}, 'sync')
        assert r['score'] == 33.0
        assert r['max'] == 33

    def test_zero_total(self):
        r = scale_legacy({'total': 0}, 'sync')
        assert r['score'] == 0.0

    def test_none_result(self):
        r = scale_legacy(None, 'sync')
        assert r['score'] == 0.0
        assert r['unavailable'] is True


class TestScoreLine4:
    @_heavy_face
    def test_normal_rate(self):
        # 11/17 → 64.7% → 21.4
        r = score_line4()
        assert r['max'] == LINE_TOTAL
        assert 0 <= r['score'] <= LINE_TOTAL
        assert 'evidence' in r and 'evidence_fingerprint' in r


class TestScoreLine5:
    def test_normal_composite(self, monkeypatch):
        """主线⑤合成算分逻辑（**无外部资产档**，对标 graphiti `no external dependencies`）。

        边界值实测（R236 补注③，2026-09-25 本机）：`audit/attention_sim.py --json` 冷态
        **240 s**（rc=0）、热态 <120 s；而 `run_json` 子进程预算 180 s、pytest 全局
        `--timeout=120`（pyproject addopts）⇒ 冷态机器（CI / 换机 / 清缓存）**必被 kill**，
        表现为「本地绿、钩子红」。真实子进程面另走 `test_real_attention_sim`（integration 档，
        默认跳过），此处只验被注资的纯逻辑面。
        """
        import score_track200 as s5
        canned = {"dilution": {"sessions": 3}, "hit_top1": 0.8, "hit_top10": 0.9}
        monkeypatch.setattr(s5, "run_json", lambda cmd: (canned, None))
        r = s5.score_line5()
        assert r['max'] == LINE_TOTAL
        assert 0 <= r['score'] <= LINE_TOTAL
        assert 'unavailable' not in r

    def test_unavailable_face_degrades_not_inflates(self, monkeypatch):
        """对照组：资产不可用时必须显式置 `unavailable` 且给 0 分，不得静默计分（R247）。"""
        import score_track200 as s5
        monkeypatch.setattr(s5, "run_json", lambda cmd: (None, 'exit=124: timeout'))
        r = s5.score_line5()
        assert r['score'] == 0.0 and r['unavailable'] is True

    @pytest.mark.integration
    @pytest.mark.timeout(420)
    def test_real_attention_sim(self):
        """真实面（integration 档）：冷态 240 s，只在显式开启时跑，不进默认链。"""
        if os.environ.get("FENJUE_RUN_INTEGRATION") != "1":
            pytest.skip("真实资产档需显式开启（FENJUE_RUN_INTEGRATION=1）；冷态 240s 超默认 120s 上限")
        r = score_line5()
        assert r['max'] == LINE_TOTAL


class TestScoreLine6:
    @_heavy_face
    def test_normal_usage(self):
        r = score_line6()
        assert r['max'] == LINE_TOTAL
        assert 0 <= r['score'] <= LINE_TOTAL


class TestIntegration:
    """整档评分面（含真实子进程）：默认链不跑，见文件头 D-66 说明。"""

    @_heavy_face
    def test_full_track200(self):
        res = run_track200(no_legacy=True)  # 只跑度量线，快
        assert res['total'] == TOTAL
        assert res['pass_line'] == PASS_LINE
        assert res['overall'] >= 0
        # lines 为 list（aggregate_status 兼容），lines_map 为 dict 详表
        assert isinstance(res['lines'], list) and len(res['lines']) == 6
        assert set(res['lines_map'].keys()) == {'line1', 'line2', 'line3', 'line4', 'line5', 'line6'}
        assert 'ts' in res and 'verdict' in res
        # JSON 可序列化
        json.dumps(res, ensure_ascii=False)

    @_heavy_face
    def test_full_track200_with_legacy(self, monkeypatch):
        # R198.10 修复（2026-08-16）：mock legacy 子进程（scorecard.score_* 内部
        # 会调 functional_dim_checks/fenjue_measure 等重脚本，subprocess 嵌套环境
        # 下可挂起 >15s 拖垮 pre-commit 门禁）；本测试只验证 legacy 路径的结构兼容。
        import scorecard
        fake = {'total': 50.0, 'max': LINE_TOTAL, 'detail': 'mock'}
        monkeypatch.setattr(scorecard, 'score_sync', lambda: fake)
        monkeypatch.setattr(scorecard, 'score_memory', lambda: fake)
        monkeypatch.setattr(scorecard, 'score_routing', lambda: fake)
        res = run_track200()
        assert res['lines_map']['line1']['max'] == LINE_TOTAL
        assert res['lines_map']['line4']['max'] == LINE_TOTAL
        json.dumps(res, ensure_ascii=False)

    @_heavy_face
    def test_json_serializable_everywhere(self):
        res = run_track200(no_legacy=True)
        s = json.dumps(res, ensure_ascii=False)
        assert '"schema": "fenjue-track200-v1"' in s


class TestRunJson:
    def test_bad_command(self):
        data, err = run_json([sys.executable, '-c', 'import sys; sys.exit(1)'])
        assert data is None
        assert err is not None

    def test_good_json(self):
        data, err = run_json([sys.executable, '-c', 'import json; print(json.dumps({"a": 1}))'])
        assert data == {'a': 1}
        assert err is None


if __name__ == '__main__':
    failures = 0
    for name, cls in sorted(globals().items()):
        if name.startswith('Test') and hasattr(cls, '__call__'):
            for mname in dir(cls):
                if mname.startswith('test'):
                    try:
                        getattr(cls(), mname)()
                        print('PASS %s.%s' % (name, mname))
                    except AssertionError as e:
                        failures += 1
                        print('FAIL %s.%s: %s' % (name, mname, e))
    print('\n%s' % ('ALL PASS' if failures == 0 else '%d FAILURES' % failures))
    sys.exit(1 if failures else 0)
