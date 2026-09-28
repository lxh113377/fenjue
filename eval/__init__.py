# -*- coding: utf-8 -*-
"""eval —— 记忆焚诀对外子集的运行时包（路由评估、门禁、三个入口）。

为什么仓内与包内两种导入都要能用：
  仓内跑（`python eval/hitrate_cli.py`）时本文件不在导入路径上，模块名是 `hitrate_cli`；
  装成 wheel 后（`fenjue-hitrate`）模块名是 `eval.hitrate_cli`。兄弟模块之间一律写成
  「先试相对导入，失败退回绝对导入」，因为只用绝对导入会靠 sys.path 注入造出
  **同一个模块的两个实例**（两份全局状态），只用相对导入则直接跑脚本会炸。

`eval/tests/` 与 `eval/verify_checks/` 刻意不进包（见 pyproject 的 packages=["eval"]）：
它们是仓内验证面，不是运行时产物。
"""

__version__ = "1.1.0"
