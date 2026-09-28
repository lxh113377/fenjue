# -*- coding: utf-8 -*-
"""verify_checks.workflow_layer — 检查函数族（P1-16 拆包，2026-09-23）。

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


def check_c11_workflow_consistency(skip_external=False):
    """C11(R195): workflow 共享规范存在、版本一致、在役端脚本路径合法。"""
    if skip_external:
        return ('SKIP', 'workflow 规范不可达（CI 环境，C11 保持本地）')
    if not os.path.exists(_root.WORKFLOW_DOC_PATH):
        return ('FAIL', f'workflow 规范缺失: {_root.WORKFLOW_DOC_PATH}')
    try:
        with open(_root.WORKFLOW_DOC_PATH, encoding='utf-8') as f:
            head = f.read(800)
        m = re.search(r'版本[:：]\s*V?(\d+\.\d+)', head)
        if not m:
            return ('FAIL', 'workflow 规范头部缺少「版本: Vx.y」')
        if m.group(1) != _root.WORKFLOW_VERSION:
            return ('FAIL', f'workflow 规范版本 {m.group(1)} != truth_constants {_root.WORKFLOW_VERSION}')
        if set(_root.WORKFLOW_PLATFORMS) != set(_root.ENDPOINTS):
            return ('FAIL', f'workflow.platforms {sorted(_root.WORKFLOW_PLATFORMS)} != _root.ENDPOINTS {sorted(_root.ENDPOINTS)}')
        # R209-3: _root.WORKFLOW_SCRIPTS 值为 Windows 反斜杠风格；Linux 上 os.path.join
        # 把反斜杠当文件名字符 → 必然「缺失」。先归一到 os.sep（Windows 无操作）。
        missing_scripts = [rel for rel in _root.WORKFLOW_SCRIPTS.values()
                           if not os.path.exists(os.path.join(_root.PROJECT_DIR, rel.replace('\\', os.sep)))]
        if missing_scripts:
            return ('FAIL', f'wf_*.ps1 脚本缺失: {missing_scripts}')
        if not os.path.exists(os.path.join(_root.PROJECT_DIR, _root.WORKFLOW_GATE_SCRIPT.replace('\\', os.sep))):
            return ('FAIL', f'gate 脚本缺失: {_root.WORKFLOW_GATE_SCRIPT}')
        return ('PASS', f'workflow 规范 V{_root.WORKFLOW_VERSION} 存在，{_root.EP_CN_LABEL}脚本齐全，platforms 与 _root.ENDPOINTS 一致')
    except Exception as e:
        return ('FAIL', f'C11 校验异常: {e}')


def check_c12_task_card_fields(skip_external=False):
    """C12(R196): workflow 规范任务卡字段 == workflow_gate.TASK_CARD_HEADERS。"""
    if skip_external:
        return ('SKIP', 'workflow 规范不可达（CI 环境，C12 保持本地）')
    if not os.path.exists(_root.WORKFLOW_DOC_PATH):
        return ('FAIL', f'workflow 规范缺失: {_root.WORKFLOW_DOC_PATH}')
    try:
        sys.path.insert(0, _root.EVAL_DIR)
        import workflow_gate as wg  # noqa: PLC0415
        with open(_root.WORKFLOW_DOC_PATH, encoding='utf-8') as f:
            text = f.read()
        fields = []
        for line in text.splitlines():
            s = line.strip()
            m = re.match(r'^-\s*##\s+([^（(]+)', s)
            if m:
                fields.append('## ' + m.group(1).strip())
        expected = sorted(wg.TASK_CARD_HEADERS)
        got = sorted(fields)
        if got != expected:
            missing = [h for h in expected if h not in got]
            extra = [h for h in got if h not in expected]
            return ('FAIL', f'任务卡字段漂移: 缺 {missing} 多 {extra}')
        return ('PASS', f'workflow 规范任务卡字段 == gate TASK_CARD_HEADERS（{len(expected)} 区）')
    except Exception as e:
        return ('FAIL', f'C12 校验异常: {e}')

