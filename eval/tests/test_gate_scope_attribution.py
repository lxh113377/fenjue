#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享工作树红项归因测试（对标轮五 P0-23）。

这个机制的风险是**反向的**：给它太多豁免，就把第 1 闸掏空成新的 vacuous pass。
所以测试的重心全在"什么时候必须仍然拦"：认不出因、命中本次暂存面、连续豁免超限、
账本被写坏。放行反而是次要的一侧。
"""

import json
import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)
import gate_scope_attribution as g  # noqa: E402

C20_DETAIL = "1 项超基线: ican-frontend-design-system 计数上升 code 0->0 / inline 1->4"
STAGED = (["eval/stubs/stub_c33_memory_index.py", "eval/gate_stub_runner.py"],
          {"eval", "stubs", "gate_stub_runner.py", "stub_c33_memory_index.py",
           "gate_scope_attribution.py"})


def _r(cid, detail, status="FAIL"):
    return {"id": cid, "detail": detail, "status": status}


def test_all_pass_allows():
    allow, items, _ = g.classify([_r("C1", "ok", "PASS")], STAGED)
    assert allow and not items


def test_unrelated_skill_red_is_exempted(tmp_path):
    allow, items, banner = g.classify([_r("C20", C20_DETAIL)], STAGED)
    assert allow is True and "他人存量红" in items[0][1]
    assert "ican-frontend-design-system" in banner


def test_unattributable_detail_fails_closed():
    """detail 里什么都抽不出可归属标记 ⇒ 一律算我引入的（宁拦不误放）。"""
    allow, items, _ = g.classify([_r("C9", "发现残留")], STAGED)
    assert allow is False and "不可归因" in items[0][1]


def test_token_hitting_staged_path_is_related():
    d = "eval/stubs/stub_c33_memory_index.py 计数与注册表不符"
    allow, items, _ = g.classify([_r("C13", d)], STAGED)
    assert allow is False and "本次改动面命中" in items[0][1]


def test_exempt_cap_escalates_instead_of_punishing_bystanders():
    """超限后的**无因果**提交不再被连带阻断（原设计会被），但必须转成升级记账 + 债务可见。

    D-36 实测（2026-09-24 23:35→23:46）：旧写法的 block 行会被 streaks() 当成归零事件，
    上限实际只生效一次，随后豁免照流 ⇒ "防永久豁免"是纸面约束。
    """
    prior = {"C20": g.EXEMPT_CAP}
    allow, items, _ = g.classify([_r("C20", C20_DETAIL)], STAGED, prior=prior)
    assert allow is True and "升级" in items[0][1]


def test_owner_is_still_blocked_after_cap():
    """超限不削弱对"肇事者"的阻断：命中本次暂存面/认不出因 ⇒ 一律拦，与 prior 无关。"""
    prior = {"C20": g.EXEMPT_CAP * 3}
    d = "eval/stubs/stub_c33_memory_index.py 计数与注册表不符"
    allow, items, _ = g.classify([_r("C13", d)], STAGED, prior=prior)
    assert allow is False and "本次改动面命中" in items[0][1]
    allow, items, _ = g.classify([_r("C9", "发现残留")], STAGED, prior=prior)
    assert allow is False and "不可归因" in items[0][1]


def test_record_and_streak_reset(tmp_path):
    path = str(tmp_path / "ledger.jsonl")
    g.record([("C20", "与本次暂存面无因果 → 判为他人存量红，豁免并落账", C20_DETAIL)],
             ["eval/x.py"], ledger_path=path)
    assert g.streaks(path).get("C20") == 1
    g.record([("C20", "本次改动面命中或不可归因", C20_DETAIL)], ["eval/x.py"], ledger_path=path)
    assert g.streaks(path).get("C20") == 1, (
        "D-36 回归锁：block 不是修复，不得把连续豁免计数归零")


def test_escalate_rows_keep_counting(tmp_path):
    path = str(tmp_path / "ledger.jsonl")
    g.record([("C20", "连续豁免已达上限 5 → 升级为存量红债务（非本次改动面）", C20_DETAIL)],
             ["eval/x.py"], ledger_path=path)
    assert g.streaks(path).get("C20") == 1


def test_only_resolve_releases_the_streak(tmp_path):
    """唯一的释放口：该判据当前不再 FAIL 才允许销账（红还在 ⇒ 拒绝）。"""
    path = str(tmp_path / "ledger.jsonl")
    for _ in range(3):
        g.record([("C20", "与本次暂存面无因果 → 判为他人存量红，豁免并落账", C20_DETAIL)],
                 ["eval/x.py"], ledger_path=path)
    assert g.streaks(path).get("C20") == 3
    ok, why = g.resolve("C20", results=[_r("C20", C20_DETAIL)], ledger_path=path)
    assert ok is False and "仍 FAIL" in why and g.streaks(path).get("C20") == 3
    ok, _ = g.resolve("C20", results=[_r("C20", "棘轮正常", "PASS")], ledger_path=path)
    assert ok is True and g.streaks(path).get("C20") == 0


def test_corrupt_ledger_lines_tolerated(tmp_path):
    path = str(tmp_path / "ledger.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write("坏行 not json\n\n")
    assert g.streaks(path) == {}


def test_tokens_ignore_stop_words():
    toks = g.tokens_from_detail("count 0->0 inline 1->4 status baseline eval schema none")
    assert not (set(toks) & g.STOP_WORDS), toks


def test_real_run_produces_a_decision():
    """端到端：真跑一次（不写真账本，只验 classify 链路能出判定）。"""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(EVAL_DIR, "verify_truth_consistency.py"),
                        "--json"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=EVAL_DIR)
    data = json.loads(r.stdout)
    results = data.get("results") if isinstance(data, dict) else data
    assert isinstance(results, list) and results, "verify --json 结构变了，本机制会失效"
    allow, items, _ = g.classify(results, g.staged_paths())
    assert items == [] or all(c for c, _w, _d in items)
    if allow:
        assert all(("豁免" in w) or ("升级" in w) for _c, w, _d in items), "放行却夹着未豁免的红项"
    else:
        assert any(("豁免" not in w) for _c, w, _d in items), "阻断却说不出拦的是哪条"


# ---- D-106（对标轮十七续）：注入面余量薄时不给"再宽限 5 次" ----
# 一手实测：C25 今天两次判红（15:55 记 63767 > 基线 63336；16:3x 一度到 64604），
# 两次都走"他人存量红 → 豁免并落账"，账面看着没事，实际余量只剩 216B（0.34%）。

def _c25(total):
    return _r('C25', 'W4 总字节 %d > 棘轮基线 63336 → 精简或拆 references 侧车' % total)


def test_headroom_ratio_reads_measured_bytes():
    assert abs(g.headroom_ratio('W4 总字节 63120 棘轮基线 63336') - 216 / 63336) < 1e-9
    assert g.headroom_ratio('文案里一个数都没有') is None, '取不到数不得冒充"余量充足"'
    assert g.headroom_ratio('') is None


def test_headroom_goes_negative_when_over_baseline():
    assert g.headroom_ratio('W4 总字节 64604 棘轮基线 63336') < 0, '已超基线必须是负余量'


def test_thin_margin_escalates_without_waiting_for_the_cap():
    allow, items, _banner = g.classify([_c25(63120)], STAGED, prior={})
    assert allow is True, '升级=可见+落账，不夺他人提交权（阻断由硬顶 W3 负责）'
    assert '升级为存量红债务' in items[0][1] and '余量仅 0.3%' in items[0][1]
    assert g._action_of(items[0][1]) == 'escalate', '要记成升级账，不能又记一次 exempt'


def test_healthy_margin_still_takes_the_normal_exempt_path():
    _allow, items, _banner = g.classify([_c25(50000)], STAGED, prior={})
    assert '豁免并落账' in items[0][1] and g._action_of(items[0][1]) == 'exempt'


def test_margin_rule_does_not_leak_to_other_checks():
    _allow, items, _banner = g.classify(
        [_r('C10', 'W4 总字节 63120 > 棘轮基线 63336')], STAGED, prior={})
    assert g._action_of(items[0][1]) == 'exempt', '规则只作用于 THIN_MARGIN_CHECKS 名单内的判据'


def test_headroom_reads_both_wordings_and_the_text_fallback():
    """回退路径必须真能走：truth_constants 拿不到时，基线要从文案里读出来。

    首版这里我打了错字（`枠轮基线`），正则永远匹配不到 —— 回退分支不测就等于没有。
    """
    assert g.headroom_ratio('注入区 63120 B / 基线 63336 B（余量 216）') is not None
    assert abs(g.headroom_ratio('W4 总字节 63120 > 棘轮基线 63336', baseline=63336)
               - 216 / 63336) < 1e-12
    assert g.headroom_ratio('一段没有数的文案') is None
