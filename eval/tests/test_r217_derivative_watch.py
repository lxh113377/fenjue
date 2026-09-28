"""R216-02: derivative_watch 单元测试（tmp 注入路径，零生产污染）。

覆盖：快照→复检干净、漂移检出、缺失检出、manifest 缺失、fix() 调链。
结构计数（structure_counts）读真实产物，只读且廉价，作为 check() 附加面断言键存在。
"""
import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import derivative_watch as dw  # noqa: E402


def _mk(tmp_path, rel_content):
    """建 tmp 产物树，返回 (stable, domain)。stable/domain 各 2 文件。"""
    stable_dir = tmp_path / 'stable'
    domain_dir = tmp_path / 'domains'
    stable_dir.mkdir()
    domain_dir.mkdir()
    stable, domain = [], []
    for name, content in rel_content['stable'].items():
        p = stable_dir / name
        p.write_text(content, encoding='utf-8')
        stable.append(str(p))
    for name, content in rel_content['domain'].items():
        p = domain_dir / name
        p.write_text(content, encoding='utf-8')
        domain.append(str(p))
    return stable, domain


CONTENTS = {
    'stable': {'a.json': '{"n": 1}', 'b.npy': 'binary-ish'},
    'domain': {'memory.json': '{"skills": []}', 'code.json': '{"skills": []}'},
}


def test_snapshot_check_clean(tmp_path):
    stable, domain = _mk(tmp_path, CONTENTS)
    mp = str(tmp_path / 'manifest.json')
    dw.snapshot(paths=(stable, domain), manifest_path=mp)
    rep = dw.check(manifest_path=mp, paths=(stable, domain))
    assert rep['ok'] is True and rep['drifted'] == [] and rep['missing'] == []
    assert 'structure' in rep


def test_check_detects_drift(tmp_path):
    stable, domain = _mk(tmp_path, CONTENTS)
    mp = str(tmp_path / 'manifest.json')
    dw.snapshot(paths=(stable, domain), manifest_path=mp)
    (tmp_path / 'stable' / 'a.json').write_text('{"n": 2}', encoding='utf-8')
    rep = dw.check(manifest_path=mp, paths=(stable, domain))
    assert rep['ok'] is False
    assert any('a.json' in r for r in rep['drifted'])


def test_check_detects_missing(tmp_path):
    stable, domain = _mk(tmp_path, CONTENTS)
    mp = str(tmp_path / 'manifest.json')
    dw.snapshot(paths=(stable, domain), manifest_path=mp)
    os.remove(stable[0])
    rep = dw.check(manifest_path=mp, paths=(stable, domain))
    assert rep['ok'] is False and len(rep['missing']) == 1


def test_check_manifest_missing(tmp_path):
    rep = dw.check(manifest_path=str(tmp_path / 'nope.json'))
    assert rep['ok'] is False and 'manifest 缺失' in rep.get('error', '')


def test_fix_invokes_rebuild_chain(tmp_path, monkeypatch):
    calls = {}

    def fake_run(cmd, **kw):
        calls['cmd'] = cmd
        class R:
            returncode = 0
            stderr = ''
        return R()

    monkeypatch.setattr(dw.subprocess, 'run', fake_run)
    monkeypatch.setattr(dw, 'snapshot', lambda: {'artifacts': {}})
    monkeypatch.setattr(dw, 'check', lambda: {'schema': dw.SCHEMA, 'ok': True, 'drifted': []})
    rep = dw.fix()
    assert rep.get('fixed') is True and rep['ok'] is True
    assert calls['cmd'][-1] == '--apply' and 'build_indexes.py' in calls['cmd'][1]


# ── D-120：守恒 ≠ 新鲜（派生件可以完全自洽，却是用几小时前的 SKILL.md 编的）──


def _touch(path, mtime):
    os.utime(path, (mtime, mtime))


def test_stale_pairs_flags_sources_newer_than_artifact(tmp_path):
    art = tmp_path / "emb.npy"
    art.write_bytes(b"x")
    src = tmp_path / "sk" / "A-skill"
    src.mkdir(parents=True)
    s = src / "SKILL.md"
    s.write_text("v1", encoding="utf-8")
    base = 1_800_000_000.0
    _touch(str(art), base)
    _touch(str(s), base - 10)
    assert dw.stale_pairs([str(art)], [str(s)]) == []          # 正向：产物比源新
    _touch(str(s), base + 60)
    hits = dw.stale_pairs([str(art)], [str(s)])
    assert len(hits) == 1 and hits[0]["source"] == "A-skill"   # 反向：源改过就点名
    assert 59 <= hits[0]["lag_s"] <= 61


def test_stale_pairs_grace_window_absorbs_same_run_jitter(tmp_path):
    art = tmp_path / "emb.npy"
    art.write_bytes(b"x")
    s = tmp_path / "SKILL.md"
    s.write_text("v", encoding="utf-8")
    base = 1_800_000_000.0
    _touch(str(art), base)
    _touch(str(s), base + 1.0)     # 同一次 --apply 里的毫秒级抖动
    assert dw.stale_pairs([str(art)], [str(s)]) == []


def test_no_face_returns_none_not_fresh(tmp_path):
    """取不到数不许冒充"新鲜"（R247：空面不是零违规）。"""
    art = tmp_path / "emb.npy"
    art.write_bytes(b"x")
    assert dw.stale_pairs([str(art)], []) is None
    assert dw.stale_pairs([], [str(art)]) is None


def test_stale_baseline_is_embedding_artifact_not_the_whole_face(tmp_path, monkeypatch):
    """回归锁：内容未变就不重写的 registry 件（实测停在 23 小时前）不得当基准。

    首版拿"全部产物的最旧 mtime"当基准，把 45 个正常编辑过的 SKILL.md 误报成过期；
    改成只看编码件（npy/npz）后与 disk_manifest 的 sha 通道 4/4 全等。
    """
    old_json = tmp_path / "unified-skills-index.json"
    old_json.write_text("{}", encoding="utf-8")
    emb = tmp_path / "bge_fullbody_embeddings.npy"
    emb.write_bytes(b"x")
    src = tmp_path / "d" / "one-skill"
    src.mkdir(parents=True)
    md = src / "SKILL.md"
    md.write_text("v", encoding="utf-8")
    base = 1_800_000_000.0
    _touch(str(old_json), base - 90000)     # 比编码件旧 25 小时（但内容未变 ⇒ 合法）
    _touch(str(emb), base)
    _touch(str(md), base - 300)             # 源比编码件旧 ⇒ 新鲜
    monkeypatch.setattr(dw, "collect_artifacts",
                        lambda: ([str(old_json), str(emb)], []))
    monkeypatch.setattr(dw, "skill_source_files", lambda root=None: [str(md)])
    assert dw.stale_sources() == []
    _touch(str(md), base + 400)             # 源在编码之后被改 ⇒ 必须点名
    hits = dw.stale_sources()
    assert [h["source"] for h in hits] == ["one-skill"]
    # 反证：若仍按"全部产物最旧 mtime"算，这里会多报 0 条但 lag 大 25 小时 —— 基准取错就失真
    assert dw.stale_pairs([str(old_json), str(emb)], [str(md)])[0]["lag_s"] > 90000


def test_skill_source_files_empty_root_is_empty_list(tmp_path):
    assert dw.skill_source_files(str(tmp_path / "不存在")) == []
