# -*- coding: utf-8 -*-
"""guardrail_checks.py — 护栏转化首批（R170 真实使用闭环）

把可脚本化的 P0 教训变成机器断言：
  G1 BOM/编码护栏（lessons-p0 #4）: 活跃 .ps1 无 UTF-8 BOM
  G2 数据层守恒护栏（lessons-p0 #7）: 复跑 functional_dim_checks 内容自洽 100%
  G3 泛规则抢占护栏（R169 dogfood 案）: 4 条已知冲突查询 top1 不回退
  G4 生产缺口护栏（R170 决策）: 4 条新直连查询 top1 精确命中

用法:
  python eval/guardrail_checks.py [--json]
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)
from config import GLOBAL_MEMORY  # noqa: E402

# D-108：解释器路径此前写死成 `C:\Program Files\Python312\python.exe`（本机装位），
# 换机/CI Linux 上这个文件不存在 ⇒ G3/G4 探针一律 return None，护栏**静默全红或全瞎**。
# 现取当前进程解释器，并留 env 覆盖口（与 config.py 的 env 优先口径一致）。
PY = os.environ.get("FENJUE_PY") or sys.executable
# D-110：跳过清单此前按「整条路径 substring」判定 ⇒ `Templates/`、`my_archive/`、
# `C:\Users\...\Temp\` 之类只要*路径里含这些字串*就整棵树被跳过（本轮写测试时当场撞上：
# pytest 的 tmp_path 在 %TEMP% 下，BOM 夹具直接扫不到 ⇒ 判"无 BOM"= 假绿）。
# 现按**目录分量**精确比对，只跳真正的噪音目录。
SKIP_DIR_PARTS = {"archive", "_bak", "_trash", "_temp", "_tmp", ".git", "__pycache__",
                 "temp", "tmp", "node_modules"}
# 实测补充：仓内临时克隆（`_temp/ci_*`）会把 G1 的读数从 7 顶到 21 —— 度量被自己的脚手架污染
# 比读不到更坏，因为它会让人以为债务在涨。跳过清单必须包含本仓约定的临时归口目录。


def _skip_dir(dp: str) -> bool:
    return any(part.lower() in SKIP_DIR_PARTS for part in os.path.normpath(dp).split(os.sep))


def scan_bom(paths):
    bad = []
    for base in paths:
        for dp, _dn, fns in os.walk(base):
            if _skip_dir(dp):
                continue
            for fn in fns:
                if not fn.endswith(".ps1"):
                    continue
                fp = os.path.join(dp, fn)
                with open(fp, "rb") as f:
                    head = f.read(3)
                if head == b"\xef\xbb\xbf":
                    bad.append(fp)
    return bad


def run_probe(query):
    """D-111：路由探针的环境性失败（解释器缺失 / router 报错 / 超时）不得把整条护栏带崩。

    旧实现把 `subprocess.run` 裸在外面 ⇒ 换机后 `FileNotFoundError` 直接抛出，
    G1/G2 的结论也一起没了（一处脆断拖垮全表）。现在失败回 None，让 G3/G4 逐条判 FAIL，
    红是"探针不通"的红，而不是"整条护栏不存在"。
    """
    try:
        out = subprocess.run([PY, os.path.join(ROOT, "unified_router.py"), "--json", query],
                             capture_output=True, text=True, encoding="utf-8", timeout=120)
        return json.loads(out.stdout[out.stdout.find("{"):]).get("top1")
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-router", action="store_true", help="跳过 G3/G4 路由探针（省时）")
    args = ap.parse_args()

    checks = []

    # G1
    bad = scan_bom([PROJ, os.path.join(GLOBAL_MEMORY, "scripts")])
    checks.append({"id": "G1", "name": "BOM/编码护栏", "pass": len(bad) == 0,
                   "detail": f"无 BOM 的 .ps1 应为全部；BOM 文件 {len(bad)} 个" + (f": {bad[:3]}" if bad else "")})

    # G2
    g2_ok = False
    g2_detail = "functional_dim_checks.py 未找到"
    fdc = os.path.join(ROOT, "functional_dim_checks.py")
    if os.path.exists(fdc):
        try:
            out = subprocess.run([PY, fdc, "--json"], capture_output=True, text=True,
                                 encoding="utf-8", timeout=120)
            data = json.loads(out.stdout[out.stdout.find("{"):])
            di = data.get("dataintegrity", {})
            g2_ok = di.get("health") == 100
            g2_detail = f"内容级自洽 health={di.get('health')}% route_cover={di.get('route_cover')}"
        except Exception as e:
            g2_detail = f"执行失败: {e}"
    checks.append({"id": "G2", "name": "数据层四道防线/守恒", "pass": g2_ok, "detail": g2_detail})

    if not args.skip_router:
        probes = [
            ("帮我看看路由有没有问题", "A-skill-manager"),
            ("我想让别人也可以打开我的网站", "byted-bp-cdn-pagesdeploy"),
            ("继续执行未完成的任务", "A-project-handoff"),
            ("下载 Hermes 桌面版", "hermes-installer"),
            ("写个脚本定期备份数据库", "tencent-cos-skill__skillhub"),
            ("开始写第一章小说", "doc-coauthoring"),
            ("这是我的记忆系统项目文件夹，为codex配置我的记忆系统memory tree和skill tree", "cross-platform-agent-sync"),
            ("生成一张海报", "byted-seedream-image-generate"),
        ]
        for idx, (q, want) in enumerate(probes):
            got = run_probe(q)
            checks.append({"id": "G3" if idx < 4 else "G4", "name": q, "pass": got == want,
                           "detail": f"期望={want} 实测={got}"})

    all_pass = all(c["pass"] for c in checks)
    if args.json:
        print(json.dumps({"all_pass": all_pass, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        for c in checks:
            print(("PASS" if c["pass"] else "FAIL"), c["id"], c["name"], "|", c["detail"])
        print("guardrail 总判定:", "PASS" if all_pass else "FAIL")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
