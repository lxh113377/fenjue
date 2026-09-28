# -*- coding: utf-8 -*-
"""C20 隔离桩 —— 技能可移植性棘轮（包装桩，转发被包装脚本的 --selftest）。

三要素（正例 / 违规样本 / 边界）内置于 `eval/portability_ratchet.py` 的 `_selftest()`：
  正例     —— 恰等于基线不报
  违规样本 —— 新增技能含绝对路径 / 既有技能 inline 计数上升 / 代码块内计数上升
  边界     —— 基线缺失 / 扫描面为空 / 基线 skills 为空

桩自身不接触真实 <SKILLS_ROOT>（自检在临时目录造夹具），故可安全复跑。

**gate_stub_runner 契约**：末行必须是**无缩进**的 `<passed>/<total>`。
被包装脚本的明细行带两级缩进转发，汇总行单独原样输出（v1 曾因汇总行也缩进 ⇒ runner
报「未解析到 N/M 汇总（末行=  8/8）」）。
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(os.path.dirname(HERE), "portability_ratchet.py")


def main():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPYCACHEPREFIX"] = os.path.join(os.environ.get("TEMP", "."), "pycache_stub_c20")
    p = subprocess.run([sys.executable, "-B", TARGET, "--selftest"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    out = (p.stdout or "").strip()
    summary = ""
    for ln in out.splitlines():
        print("  " + ln)
        if re.fullmatch(r"\s*\d+/\d+", ln):
            summary = ln.strip()
    if p.stderr:
        print("  stderr: " + p.stderr.strip()[-400:], file=sys.stderr)
    # runner 正则要求带 label 冒号前缀：`:\\s*(\\d+)/(\\d+)`
    if not summary:
        print("{0}: 0/0".format(os.path.basename(__file__)))
        return 1
    print("{0}: {1}".format(os.path.basename(__file__), summary))
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
