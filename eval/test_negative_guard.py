#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_negative_guard.py — CI 可移植负样本护栏（R202 新增）

背景：<MEMORY_ROOT>/tests/run_negative_test.py 依赖本机 skill_content/*.json，
CI（ubuntu）无法访问 D 盘 → 本脚本在仓库内可移植运行：

1) schema 校验：负样本集（仓库内副本 tests/fixtures/skill_hit_test_negative.json）
   每条目含 msg / not_expect / cat / note，not_expect 语义合法（"*" 或 skill 名列表）；
2) skill 名引用一致性：not_expect 中所有非 "*" 名称必须存在于
   skill/registry/unified-skills-index.json（169 skills）；
3) 负样本守卫判定：误命中率 > 阈值（默认 10%）exit 1。

与周维护全量门禁（<MEMORY_ROOT>/tests/run_negative_test.py --threshold 0.10）双轨：
- 本脚本 = CI 契约测试（schema + 名称引用 + 自包含误命中演示，数据源仓库内）
- 周维护 = 本机全量误命中率（读真实 skill_content triggers）

用法: python eval/test_negative_guard.py [--threshold 0.10] [--set <负样本json>]
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SET = REPO_ROOT / "eval" / "tests" / "fixtures" / "skill_hit_test_negative.json"
REGISTRY = REPO_ROOT / "skill" / "registry" / "unified-skills-index.json"


def load_registry_names():
    """从仓库统一注册表提取 skill 名集合（169）。"""
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return set(data["skills"].keys())


def check_schema(negs):
    """schema 校验：字段齐全 + not_expect 语义合法。返回错误列表。"""
    errors = []
    for i, item in enumerate(negs):
        if "msg" not in item or not item["msg"].strip():
            errors.append(f"#{i}: 缺 msg 或为空")
        ne = item.get("not_expect")
        if ne is None:
            errors.append(f"#{i}: 缺 not_expect")
        elif not isinstance(ne, list) or not ne:
            errors.append(f"#{i}: not_expect 必须为非空列表")
        elif ne != ["*"] and not all(isinstance(x, str) and x for x in ne):
            errors.append(f"#{i}: not_expect 元素必须为字符串")
        if "cat" not in item:
            errors.append(f"#{i}: 缺 cat")
    return errors


def check_name_refs(negs, registry_names):
    """引用一致性：not_expect 中的 skill 名必须存在于注册表。返回缺失列表。"""
    missing = []
    for i, item in enumerate(negs):
        for x in item.get("not_expect", []):
            if x != "*" and x not in registry_names:
                missing.append(f"#{i}: {x}")
    return missing


def demo_mis_hit_rate(negs, registry_names):
    """自包含误命中演示：对每条反例，检查 not_expect 中是否有 skill 名
    作为子串出现在 msg 中（触发词子串近似）。返回误命中列表。

    说明：这不是真实触发词命中检测（真实版在周维护读 skill_content triggers），
    仅作为 CI 契约测试的守卫基线——若负样本集本身设计失效（如 msg 含 skill 名），
    立即暴露。
    """
    bad = []
    for item in negs:
        msg = item["msg"].lower()
        fired = [x for x in item.get("not_expect", []) if x != "*" and x.lower() in msg]
        if fired:
            bad.append({"msg": item["msg"], "not_expect": item["not_expect"], "fired": fired})
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.10)
    ap.add_argument("--set", default=str(DEFAULT_SET))
    args = ap.parse_args()

    set_path = Path(args.set)
    if not set_path.exists():
        print(f"FAIL: 负样本集不存在: {set_path}")
        return 1

    negs = json.loads(set_path.read_text(encoding="utf-8"))
    if not isinstance(negs, list):
        print("FAIL: 负样本集必须为 JSON 数组")
        return 1

    # 1) schema
    schema_errors = check_schema(negs)
    # 2) 名称引用一致性
    registry_names = load_registry_names()
    ref_missing = check_name_refs(negs, registry_names)
    # 3) 自包含守卫演示
    demo_bad = demo_mis_hit_rate(negs, registry_names)
    rate = len(demo_bad) / len(negs) if negs else 0.0

    print(f"负样本契约门禁: 反例 {len(negs)} 条 | schema 错误 {len(schema_errors)} | 名称缺失 {len(ref_missing)} | 演示误命中 {len(demo_bad)} ({rate:.1%})")
    print(f"注册表 skill 覆盖: {len(registry_names)}")

    ok = True
    if schema_errors:
        ok = False
        for e in schema_errors:
            print(f"  [schema] {e}")
    if ref_missing:
        ok = False
        for m in ref_missing:
            print(f"  [名称缺失] {m}")
    if rate > args.threshold:
        ok = False
        for b in demo_bad:
            print(f"  [演示误命中] {b['msg']} | 不应触发 {b['not_expect']} | 实际 {b['fired']}")

    print(f"结论: {'PASS' if ok else 'FAIL'} (阈值 {args.threshold:.0%})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
