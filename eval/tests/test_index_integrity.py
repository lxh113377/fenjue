#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""index_integrity 契约测试：manifest 引导/校验/篡改 fail-closed。"""

import os
import sys

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import index_integrity as ii  # noqa: E402


def _write_file(path, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


@pytest.fixture
def env(monkeypatch, tmp_path):
    sc = tmp_path / "skill_content"
    sc.mkdir()
    monkeypatch.setattr(ii, "_SKILL_CONTENT", str(sc))
    monkeypatch.setattr(ii, "manifest_path", lambda: str(sc / "index_manifest.json"))
    for name in ii.ARTIFACT_KEYS:
        _write_file(sc / name, name.encode())
    return sc


def test_bootstrap_dry_run_writes_nothing(env) -> None:
    assert ii._bootstrap(False) == 0
    assert not os.path.exists(ii.manifest_path())


def test_bootstrap_force_then_check(env) -> None:
    assert ii._bootstrap(True) == 0
    assert ii._check() == 0


def test_missing_manifest_fails_closed(env) -> None:
    with pytest.raises(ii.IndexIntegrityError):
        ii.verify_pickle_hash(str(env / "tfidf_vectorizer.pkl"), "tfidf_vectorizer.pkl")


def test_verify_pickle_hash_tamper_raises(env) -> None:
    ii._bootstrap(True)
    _write_file(env / "tfidf_vectorizer.pkl", b"tampered")
    with pytest.raises(ii.IndexIntegrityError):
        ii.verify_pickle_hash(str(env / "tfidf_vectorizer.pkl"), "tfidf_vectorizer.pkl")


def test_vectorizer_structure_rejects_bad_object(env) -> None:
    with pytest.raises(ii.IndexIntegrityError):
        ii.verify_vectorizer_structure(object(), 5, "tfidf_vectorizer.pkl")
