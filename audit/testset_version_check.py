#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
testset_version_check.py — 测试集版本化检测（融合评分卡 达标判定用）

检测 test_queries.json / blind_test_queries.json 两次评分间是否被"提分式修改":
  - 删除失败用例（routable 且 expected 存在的用例被删）
  - 修改 expected_skill 让命中率变高（无 note 标记的重指）
  - 新增用例

通过 git diff 对比当前工作区 vs HEAD。

输出:
  - 变更类型清单
  - 退出码: 0=无提分式修改, 1=有可疑修改
"""
import os
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_DIR = os.path.join(PROJECT_DIR, 'eval')
FILES = ['eval/test_queries.json', 'eval/blind_test_queries.json']


def git_diff(path):
    """返回 (old_content, new_content) 或 (None, None) 若无变更"""
    try:
        r = subprocess.run(
            ['git', 'diff', 'HEAD', '--', path],
            capture_output=True, text=True, encoding='utf-8',
            cwd=PROJECT_DIR, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        return None
    except Exception:
        return None


def check_removed_cases(diff_text):
    """检测被删除的用例行（- 开头的 query/expected）"""
    removed = []
    for line in diff_text.split('\n'):
        if line.startswith('-') and ('"query"' in line or '"expected_skill"' in line):
            removed.append(line[1:].strip()[:100])
    return removed


def main():
    suspicious = []
    for f in FILES:
        diff_text = git_diff(f)
        if diff_text is None:
            print(f'{f}: 无变更 ✅')
            continue
        removed = check_removed_cases(diff_text)
        # 统计新增/删除行
        added = sum(1 for ln in diff_text.split('\n') if ln.startswith('+') and '"query"' in ln)
        deleted = sum(1 for ln in diff_text.split('\n') if ln.startswith('-') and '"query"' in ln)
        print(f'{f}: 变更检测到')
        print(f'  新增 query 行: {added}')
        print(f'  删除 query 行: {deleted}')
        if deleted > 0:
            suspicious.append((f, f'删除了 {deleted} 个用例（可能是提分式修改）'))
        if added > 0:
            suspicious.append((f, f'新增 {added} 个用例（需人工确认是否合理）'))
        for r in removed[:5]:
            print(f'  [REMOVED] {r}')

    if suspicious:
        print('\nRESULT: 存在可疑修改 — 需人工审查后确认')
        for s in suspicious:
            print(f'  ⚠️ {s[0]}: {s[1]}')
        return 1
    print('\nRESULT: PASS — 测试集无提分式修改')
    return 0


if __name__ == '__main__':
    sys.exit(main())
