# -*- coding: utf-8 -*-
"""D-97（对标轮十七）：CI 阻断闸 path-hygiene 的判据本体 0% 覆盖 —— 补棘轮语义反例。

一手实测（`python -m coverage json` 全量普查）：`eval/path_hygiene.py` 行覆盖 **0.0%（71 语句全缺）**，
而它在 CI `--expect` 名单里（`python -c "import sys;sys.path.insert(0,'eval');import faces;print('path-hygiene' in faces.ci_expect_slugs())"` = True）。
也就是说：拦"新增盘符字面量"的棘轮从来没被任何测试触达过 —— 它判红/判绿的每一条边界
都只是**注释里的承诺**。上游对照：pallets 系（flask / werkzeug）在 `[tool.coverage.run]`
里连 `branch = true` 都开，判据本体不测是不可想象的。

本文件把四条边界钉死：新文件计红、同文件超基线计红、只降不计、判据面不可读判失效（R247），
外加三条"不计数"的豁免出口（注释行 / 行内标记 / 白名单文件）与一条扫描面反证。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'eval'))

import path_hygiene as ph  # noqa: E402

BS = chr(92)                       # 反斜杠：显式构造，避免任何一层工具把转义吃掉（D-89 同族）
OFFENDING = 'ROOT = "D:%sglobal_memory"' % BS
CLEAN = 'from config import ROOT\n'


def _face(tmp_path, files):
    """在 tmp_path 下造 eval/ 与 scripts/ 面。"""
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
    return tmp_path


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    root = _face(tmp_path, {'eval/a.py': CLEAN, 'scripts/b.py': CLEAN})
    monkeypatch.setattr(ph, 'REPO_ROOT', str(root))
    monkeypatch.setattr(ph, 'BASELINE_PATH', str(root / 'eval' / 'baseline.json'))
    monkeypatch.setattr(sys, 'argv', ['path_hygiene.py'])
    return root


# ── scan：命中口径 ──

def test_scan_flags_only_files_with_drive_literals(sandbox):
    (sandbox / 'eval' / 'a.py').write_text(OFFENDING + '\n', encoding='utf-8')
    hits = ph.scan()
    assert list(hits) == ['eval/a.py'] and hits['eval/a.py'] == [1]


def test_comment_lines_do_not_count(sandbox):
    """豁免出口①：注释行不计数（否则"改掉一条注释"就判红）。"""
    (sandbox / 'eval' / 'a.py').write_text('# 例：%s\n' % OFFENDING, encoding='utf-8')
    assert ph.scan() == {}


def test_inline_marker_exempts_the_line(sandbox):
    """豁免出口②：行内 `path-hygiene:ok` 是人工裁定过的（R209 机器化）。"""
    (sandbox / 'eval' / 'a.py').write_text(OFFENDING + '  # path-hygiene:ok\n', encoding='utf-8')
    assert ph.scan() == {}


def test_whitelisted_definition_sites_are_out_of_face(sandbox):
    """豁免出口③：truth 常量定义点/本 lint 自身允许字面量，但它必须在扫描面内被跳过。"""
    (sandbox / 'eval' / 'truth_constants.py').write_text(OFFENDING + '\n', encoding='utf-8')
    (sandbox / 'eval' / 'z_other.py').write_text(OFFENDING + '\n', encoding='utf-8')
    assert list(ph.scan()) == ['eval/z_other.py']


def test_skip_dirs_are_really_skipped(sandbox):
    """覆盖面反证：tests/_cache/__pycache__ 里的命中不得进棘轮（否则夹具永远清不完）。"""
    for d in ('tests', '_cache', '__pycache__'):
        p = sandbox / 'eval' / d
        p.mkdir(parents=True, exist_ok=True)
        (p / 'x.py').write_text(OFFENDING + '\n', encoding='utf-8')
    assert ph.scan() == {}


# ── main：棘轮三态 + 判据面失效 ──

def test_new_file_with_literal_is_red(sandbox):
    (sandbox / 'eval' / 'a.py').write_text(OFFENDING + '\n', encoding='utf-8')
    (sandbox / 'eval' / 'baseline.json').write_text('{}', encoding='utf-8')
    assert ph.main() == 1


def test_growing_hits_in_a_baselined_file_is_red(sandbox, capsys):
    """同文件按**数量**棘轮：基线 1 处、现在 2 处 ⇒ 只报超出的那一条。"""
    (sandbox / 'eval' / 'a.py').write_text(OFFENDING + '\n' + OFFENDING + '\n', encoding='utf-8')
    (sandbox / 'eval' / 'baseline.json').write_text(json.dumps({'eval/a.py': [1]}),
                                                    encoding='utf-8')
    assert ph.main() == 1
    assert 'eval/a.py' in capsys.readouterr().out


def test_shrinking_hits_stays_green_and_zero_entry_is_clean(sandbox):
    """收口方向永远绿：基线 2 处现在 1 处 ⇒ PASS；基线改成 0 条目也 PASS（棘轮只进不退）。"""
    (sandbox / 'eval' / 'a.py').write_text(OFFENDING + '\n', encoding='utf-8')
    (sandbox / 'eval' / 'baseline.json').write_text(json.dumps({'eval/a.py': [1, 2]}),
                                                    encoding='utf-8')
    assert ph.main() == 0
    (sandbox / 'eval' / 'baseline.json').write_text(json.dumps({'eval/a.py': []}),
                                                    encoding='utf-8')
    assert ph.main() == 1        # 已收口到 0 却又留一处命中 ⇒ 必须红


def test_unreadable_baseline_is_failure_not_pass(sandbox):
    """R247：基线缺失/损坏 = 判据面塌了，退出码 2（既不是放行也不是普通违规）。"""
    (sandbox / 'eval' / 'baseline.json').write_text('{ 坏掉的 json', encoding='utf-8')
    assert ph.main() == 2
    os.remove(sandbox / 'eval' / 'baseline.json')
    assert ph.main() == 2


def test_update_baseline_is_idempotent(sandbox, monkeypatch):
    """写基线后立刻复跑必须绿；再跑一次基线内容不变（防止"每次跑都漂"）。"""
    (sandbox / 'eval' / 'a.py').write_text(OFFENDING + '\n', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['path_hygiene.py', '--update-baseline'])
    assert ph.main() == 0
    first = (sandbox / 'eval' / 'baseline.json').read_text(encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['path_hygiene.py'])
    assert ph.main() == 0
    monkeypatch.setattr(sys, 'argv', ['path_hygiene.py', '--update-baseline'])
    ph.main()
    assert (sandbox / 'eval' / 'baseline.json').read_text(encoding='utf-8') == first


# ── 真盘面（非夹具）：现状锁，防止判据面哪天自己坏掉 ──

def test_real_repo_face_is_green_against_real_baseline():
    rc = ph.main()
    assert rc == 0, '真盘面 path-hygiene 判 %d ⇒ 要么新增了盘符字面量，要么基线坏了' % rc


def test_real_baseline_file_is_nonempty_and_parseable():
    data = json.loads(open(ph.BASELINE_PATH, encoding='utf-8').read())
    assert isinstance(data, dict) and len(data) > 0, '基线为空 ⇒ 任何命中都会判红（R247）'
    assert all(isinstance(v, list) for v in data.values())
