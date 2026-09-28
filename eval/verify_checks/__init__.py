"""verify_checks — verify_truth_consistency 检查函数包（P1-16 拆包，2026-09-23）。

状态与助手仍以 verify_truth_consistency 为 ctx 单例（各模块 `_root.<name>` 晚绑定）；
本 __init__ 刻意空壳：族模块由 vtc.__getattr__ 按需 import_module，避免导入环。
"""
