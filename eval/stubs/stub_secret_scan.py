#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离桩（包装层）：global_memory 仓的 `secret_scan.py` 入库前敏感串扫描闸

被包装对象：`<MEMORY_ROOT>/scripts/secret_scan.py`（R272，2026-09-22）
本包装桩存在的原因：`gate_stub_runner.py` 只解析 `焚诀/eval/` 下的桩路径，
故此处 subprocess 转发被包装脚本的 `--selftest`（其内置正例/违规样本/边界三要素）。

登记：eval/stubs/registry.json → id=GATE-secret-scan
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # = <仓>/eval
from config import GLOBAL_MEMORY  # noqa: E402
TARGET = os.path.join(GLOBAL_MEMORY, 'scripts', 'secret_scan.py')

if not os.path.exists(TARGET):
    print('被包装脚本缺失: %s' % TARGET)
    print('stub_secret_scan: 0/1')
    sys.exit(1)

r = subprocess.run([sys.executable, TARGET, '--selftest'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=60)   # 实测 --selftest 0.12s；60s 已是 500x 余量（D-104 真收口）
for line in (r.stdout or '').strip().splitlines():
    print(line)

m = re.search(r'secret_scan_selftest:\s*(\d+)/(\d+)', r.stdout or '')
if not m:
    print('stub_secret_scan: 0/1（未能解析被包装脚本的自检汇总）')
    sys.exit(1)

n, d = int(m.group(1)), int(m.group(2))
print('stub_secret_scan: %d/%d (rc=%d)' % (n, d, r.returncode))
sys.exit(0 if (d > 0 and n == d and r.returncode == 0) else 1)
