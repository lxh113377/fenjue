#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill_registry_consistency.py — 技能注册表一致性（仓库内可移植，CI 用）

判据（语义优先，勿设「两账本必须相等」）：
  1. 每个注册项必须出现在 cross_platform_map.json（注册了却没进 cpm = 半登记 → FAIL）
  2. 每个注册项字段完整（含 domain）→ 缺失即 FAIL
  3. cpm 多出项：允许（install_state 台账保留历史）→ 仅信息级；若多出项不在退役黑名单则提示留意

退出码：0 = 一致 / 1 = 有半登记或字段缺失 / **2 = 面不可用（缺失、不可解析、空）**。
用法：python eval/skill_registry_consistency.py [--json]

2026-09-25（D-124）补的三处口径：空注册表此前会打印「结论: PASS」并以 0 退出 ——
`{"skills": {}}` 是一次写坏的文件就能让这条 CI 闸瞎眼过关，属 R247 禁止的形状；
损坏 JSON 此前抛裸 traceback，退出码碰巧非 0 但**不可归因**（D-67 族）。
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(REPO, "skill", "registry", "unified-skills-index.json")
CPM = os.path.join(REPO, "skill", "registry", "cross_platform_map.json")
TRUTH = os.path.join(REPO, "eval", "truth_constants.json")
# 面下限：低于此数就当"没有判据对象"处理（R247）。取 20 而不是 167，是为了不替并行会话的
# 正常增删做门禁；真注册表实测 167 条，一次写坏/截断会瞬间掉到个位数。
MIN_FACE = 20


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_face(path, key="skills"):
    """返回 (数据, 失败原因)。任一取不到数的情形都必须给出原因，而不是给一个空字典。"""
    if not os.path.exists(path):
        return None, "文件不存在：%s" % path
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError) as e:
        return None, "不可解析：%s（%r）" % (path, e)
    if not isinstance(data, dict):
        return None, "顶层不是对象：%s（拿到 %s）" % (path, type(data).__name__)
    body = data.get(key)
    if not isinstance(body, dict):
        return None, "缺 `%s` 段或类型不对：%s（拿到 %s）" % (key, path, type(body).__name__)
    if not body:
        return None, "%s 段为空：%s ⇒ 空面不是零违规（R247）" % (key, path)
    if len(body) < MIN_FACE:
        # 下限必须是**常量**而不是"本次读数"：否则一份被截断到 3 条的注册表照样过关（截断没有报错）
        return None, ("%s 段只有 %d 条，低于面下限 %d ⇒ 判据面无对象（R247）"
                      % (path, len(body), MIN_FACE))
    return body, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    reg, err_reg = load_face(REG)
    cpm, err_cpm = load_face(CPM)
    errs = [e for e in (err_reg, err_cpm) if e]
    if errs:
        # 面不可用既不判"一致"也不判"半登记"：单独一档退出码 2，让人去修面而不是改基线
        if a.json:
            print(json.dumps({"schema": "fenjue-skill-registry-consistency-v1",
                              "verdict": "FAIL-FAST", "reasons": errs}, ensure_ascii=False))
        else:
            for e in errs:
                print("[FAIL-FAST] %s" % e)
        return 2
    retired = set()
    if os.path.exists(TRUTH):
        retired = set(load(TRUTH).get("retired_skills", []))

    missing_domain = sorted(k for k, v in reg.items()
                            if not isinstance(v, dict) or not v.get("domain"))
    half = sorted(set(reg) - set(cpm))
    extra = sorted(set(cpm) - set(reg))
    extra_not_retired = [x for x in extra if x not in retired]

    out = {
        "schema": "fenjue-skill-registry-consistency-v1",
        "registry_count": len(reg),
        "cpm_count": len(cpm),
        "missing_domain": missing_domain,
        "half_registered": half,
        "cpm_extra": extra,
        "cpm_extra_not_retired": extra_not_retired,
        "all_pass": not missing_domain and not half,
    }
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["all_pass"] else 1

    print("技能注册表一致性（仓库内检查）")
    print("  注册表 %d 条 / cross_platform_map %d 条" % (len(reg), len(cpm)))
    print("  面下限 %d 条（低于即 FAIL-FAST，空面/写坏的面不得算成 PASS）" % MIN_FACE)
    if missing_domain:
        print("  ❌ 缺 domain 字段 %d 条: %s" % (len(missing_domain), missing_domain[:5]))
    if half:
        print("  ❌ 半登记（注册了却没进 cpm）%d 条: %s" % (len(half), half[:5]))
    if extra:
        print("  ℹ️ cpm 历史多出 %d 条（退役 %d / 非退役 %d）%s"
              % (len(extra), len(extra) - len(extra_not_retired), len(extra_not_retired),
                 ("；非退役留意: %s" % extra_not_retired[:4]) if extra_not_retired else ""))
    print("结论: %s" % ("PASS" if out["all_pass"] else "FAIL"))
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
