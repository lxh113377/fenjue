#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""functional_dim_checks 纯函数冒烟（R209-2③ 补测簇：227 stmts 0%）。

覆盖: _expected_of 三态 / _load_domain_skills 结构与坏文件隔离 / _load_all_queries 去重。
"""
import json
import os
import sys

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)

import functional_dim_checks as fdcm


def test_expected_of_string():
    assert fdcm._expected_of({'expected_skill': 'skill-a'}) == {'skill-a'}


def test_expected_of_list():
    assert fdcm._expected_of({'expected': ['a', 'b']}) == {'a', 'b'}


def test_expected_of_missing():
    assert fdcm._expected_of({}) == set()


def test_load_domain_skills_structures(tmp_path, monkeypatch):
    good = {'domain': 'domain-a', 'skills': [{'name': 's1'}, {'name': 's2'}]}
    (tmp_path / 'domain-a.json').write_text(
        json.dumps(good, ensure_ascii=False), encoding='utf-8')
    (tmp_path / 'broken.json').write_text('{not-json', encoding='utf-8')
    (tmp_path / 'skill_ids.json').write_text('[]', encoding='utf-8')  # 清单文件应跳过
    (tmp_path / 'readme.txt').write_text('skip', encoding='utf-8')    # 非 json 跳过
    monkeypatch.setattr(fdcm, 'SC_DIR', str(tmp_path))
    domains = fdcm._load_domain_skills()
    assert 'skill_ids' not in domains
    assert domains['domain-a']['count'] == 2
    assert domains['domain-a']['names'] == {'s1', 's2'}
    assert domains['broken'].get('broken') is True
    assert domains['broken']['count'] == 0


def test_load_all_queries_dedup_and_skip_empty(tmp_path, monkeypatch):
    data = [
        {'queries': [{'query': 'q1', 'expected_skill': 'a'},
                     {'query': 'q2', 'expected_skill': 'b'}]},
        {'queries': [{'query': '', 'expected_skill': 'c'},   # 空 query 跳过
                     {'query': 'q1', 'expected_skill': 'a'}]},  # 重复跳过
    ]
    (tmp_path / 'layered_testset.json').write_text(
        json.dumps(data, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(fdcm, 'EVAL_DIR', str(tmp_path))
    queries = fdcm._load_all_queries()
    assert [q['query'] for q in queries] == ['q1', 'q2']
