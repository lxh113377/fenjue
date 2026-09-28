# -*- coding: utf-8 -*-
"""verify_checks.doc_layer — 检查函数族（P1-16 拆包，2026-09-23）。

状态/助手经 `_root.<name>` 晚绑定（ctx 单例 = verify_truth_consistency），
monkeypatch(vtc, <state>/<check>) 契约不变。
"""
import glob
import json
import os
import re
import subprocess
import sys

import verify_truth_consistency as _root  # noqa: E402  # ctx 单例


def check_c5_shell_docs_no_stale_literals():
    """C5: 壳文档含与真相源不符的端数/主线数硬编码字面量。
    端数/主线数由 truth_constants 动态派生（P0-1 收口，2026-09-23）：在役端数变化时
    判据自动跟随，杜绝「六端（应为四端）」式过期误判；历史留痕行经
    historical_markers 豁免，不强制改写历史。
    排除 deliverables/ 和 archive/（历史报告，保留原样）。"""
    stale_patterns = []
    # 端数：只拦「高于真相源」（端数只增轨迹上的未来漂移）与「最近两档旧真值」
    # （三端/二端等低数字常指镜像数、日志面等无关语境，实测 2026-09-23，不拦防误报）
    for k, cn in _root._CN_NUMS.items():
        if k > _root.ENDPOINT_COUNT or (_root.ENDPOINT_COUNT - 2) <= k < _root.ENDPOINT_COUNT:
            stale_patterns.append((rf'{cn}端', f'{cn}端（应为{_root.EP_CN_LABEL}）'))
            stale_patterns.append((rf'{cn}向', f'{cn}向（应为{_root.EP_CN_LABEL}）'))
            stale_patterns.append((rf'(?<!\d){k}\s*端', f'{k} 端（应为{_root.EP_CN_LABEL}）'))
    # 主线数：全量对账（主线只增不减，无低数字无关语境用法）
    for k, cn in _root._CN_NUMS.items():
        if k != _root.MAINLINE_COUNT:
            stale_patterns.append((rf'{cn}大主线', f'{cn}大主线（应为{_root.ML_CN_LABEL}）'))
    # 仅检查活 workspace 根级壳文档 + AGENTS.md 分卷，不扫 deliverables/archive
    shell_files = [
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md'),
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md.part1.md'),
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md.part2.md'),
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md.part3.md'),
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md.part4.md'),
        os.path.join(_root.PROJECT_DIR, 'AGENTS.md.part5.md'),
        os.path.join(_root.PROJECT_DIR, 'STATUS.md'),
        os.path.join(_root.PROJECT_DIR, 'STATUS.part1.md'),
        os.path.join(_root.PROJECT_DIR, '.hermes.md'),
        os.path.join(_root.PROJECT_DIR, '.hermes.md.part1.md'),
        os.path.join(_root.PROJECT_DIR, '.hermes.md.part2.md'),
        os.path.join(_root.PROJECT_DIR, 'index.md'),
    ]
    for pattern in ('skill/README*.md', 'skill/docs/*.md',
                    'skill/checklist/*.md', 'skill/workflows/*.md'):
        shell_files.extend(glob.glob(os.path.join(_root.PROJECT_DIR, pattern)))
    issues = []
    # 历史注解标记：含这些词的行视为历史记录，不判为违规（历史留痕不强制改写）
    historical_markers = ('现已', '已卸载', '已下线', '原为', '历史', '过时',
                          '原文保留', '重建于', '整理轮', 'Version:', '当时')
    # 文件名例外：含这些词的行视为文件名引用，不判为违规
    file_name_exceptions = ('六端桥接路由',)  # 实际文件名，非废弃计数
    for fpath in shell_files:
        if not os.path.exists(fpath):
            continue
        with open(fpath, encoding='utf-8', errors='ignore') as f:
            for line_no, line in enumerate(f, 1):
                if any(m in line for m in historical_markers):
                    continue  # 历史记录行，跳过
                if any(fn in line for fn in file_name_exceptions):
                    continue  # 文件名引用，跳过
                for pattern, desc in stale_patterns:
                    if re.search(pattern, line):
                        issues.append(f'{os.path.basename(fpath)}:L{line_no} 含 "{desc}"')
    if issues:
        return ('FAIL', '; '.join(issues))
    return ('PASS', '壳文档无废弃口径字面量')


def check_c7_no_bare_constants():
    """C7: 生成器无裸常量（须 import truth_constants）。
    2026-09-22 扩面：status_report.py 加入扫描清单 —— 其「系统状态」表曾长期硬编码
    `| behavior_core | V30（44锚点/42有效） |`（实测真值 V41/22锚点），而 scorecard/aggregate_status
    两个文件的旧扫描面**看不到它**，属「门禁覆盖不全致假通过」。
    """
    scripts = [
        os.path.join(_root.EVAL_DIR, 'scorecard.py'),
        os.path.join(_root.EVAL_DIR, 'aggregate_status.py'),
        os.path.join(_root.EVAL_DIR, 'status_report.py'),
    ]
    issues = []
    for fpath in scripts:
        if not os.path.exists(fpath):
            continue
        with open(fpath, encoding='utf-8') as f:
            src = f.read()
        fname = os.path.basename(fpath)
        # 检查是否有 import truth_constants
        if 'from truth_constants import' not in src and 'import truth_constants' not in src:
            issues.append(f'{fname}: 未 import truth_constants')
        # 检查是否仍有裸常量（TOTAL = 150 等，但不含注释行和 truth_constants 引用行）
        bare_patterns = [
            (r'^TOTAL\s*=\s*\d+', 'TOTAL 裸常量'),
            (r'^PASS_LINE\s*=\s*\d+', 'PASS_LINE 裸常量'),
            (r'^LINE_PASS\s*=\s*\d+', 'LINE_PASS 裸常量'),
            # 2026-09-22 扩面：系统状态表写死 behavior_core 版本 / 锚点数
            (r'\|\s*behavior_core\s*\|\s*V\d+', 'behavior_core 版本硬编码（须从 truth_constants 派生）'),
            (r'\|\s*behavior_core\s*\|[^\']*\d+锚点', 'behavior_core 锚点/有效数硬编码（须从 truth_constants 派生）'),
        ]
        for line_no, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            for pattern, desc in bare_patterns:
                # search 与 match 对单行 + 带 ^ 的旧模式等价；新扩面模式需非行首匹配
                if re.search(pattern, stripped):
                    issues.append(f'{fname}:L{line_no} 仍有 {desc}: {stripped}')
    if issues:
        return ('FAIL', '; '.join(issues))
    return ('PASS', 'scorecard/aggregate_status/status_report 均从 truth_constants import，无裸常量')

