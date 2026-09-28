#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_memory_index.py — 生成 GM 记忆路由表 meta/memory_index.md（对标轮四 7-D）。

为什么需要：各在役端启动契约都写着「按 `meta/memory_index.md` 路由精准加载」，而实测该文件自
2026-09-21 R9 事故后一直是 9 行重建壳、内含 4 处「（待重建）」⇒ **按需加载链断了 3 天**，
直接压低主线②（统一记忆+路由）与主线⑤（注意力税）。手写路由表必然腐烂，所以改成生成物：
口径 = 磁盘实测目录树 + 本文件里的用途/排除注解；判据 = verify C33（存在性/非空/全覆盖/无残留）。

用法：
  python eval/build_memory_index.py --check    # 只看漂移，不写盘
  python eval/build_memory_index.py --apply    # 生成并写盘（GM 仓）
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, EVAL_DIR)
import truth_constants as t  # noqa: E402

ROOT = t.GLOBAL_MEMORY_ROOT
OUT = os.path.join(ROOT, "meta", "memory_index.md")
MAX_BYTES = 4096

# 知识目录：路由表正文（dir -> 何时读）
KNOWLEDGE = {
    "core": "铁律与身份层：behavior_core.md（P0 规则权威）/ BOOTSTRAP / SOUL / USER",
    "lessons": "踩坑经验库（报错、排查、复发型问题先查这里；按领域分卷）",
    "memory": "每日日志 + 项目记忆 01~07（继续/接手续跑读 memory/YYYY-MM-DD.md 与 07-next-steps*）",
    "meta": "索引与治理口径：memory_index / bigfile_governance / VERSION_LOCK / retire_policy 等",
    "memory_content": "记忆内容分卷（与 meta/lessons 同源的展开层）",
    "intent_l2": "意图分类 L2 细则（路由消歧的次级判据）",
    "info": "背景信息与外部系统说明",
    "projects": "项目级画像卡（冷启动续接；当前为空则勿依赖）",
    "prompts": "跨端共享工作流规范（七步闭环 workflow_seven_step 等）",
    "system": "系统设计与运行口径文档",
    "skill_content": "技能路由数据层 JSON（由 scan/build 生成，只读不手改）",
}

# 非知识目录：排除清单（dir -> 排除理由）。新增一级目录必须二选一归类，否则 C33 红。
EXCLUDED = {
    "_trash": "回收区（NOISE_PREVENTION 归口，禁作检索源）",
    ".cleanup": "清理任务留痕（执行面标记，非记忆）",
    "hooks": "git 钩子脚本（执行面，非记忆）",
    "scripts": "治理脚本（执行面，非记忆）",
    "tests": "测试用例（执行面，非记忆）",
}


def scan() -> list:
    out = []
    try:
        names = sorted(os.listdir(ROOT))
    except OSError:
        return out  # GM 根不可达（CI/异机）→ 空表，交 check_text 判 SKIP 而非假红
    for name in names:
        p = os.path.join(ROOT, name)
        if not os.path.isdir(p) or name in (".git", ".agents"):
            continue
        try:
            files = [f for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))]
        except OSError:
            files = []
        md = [f for f in files if f.endswith(".md")]
        newest = ""
        for f in md:
            try:
                d = datetime.date.fromtimestamp(
                    os.path.getmtime(os.path.join(p, f))).isoformat()
            except OSError:
                continue
            newest = max(newest, d)
        out.append({"dir": name, "md": len(md), "files": len(files), "newest": newest})
    return out


def render(rows: list, today: str) -> str:
    known = [r for r in rows if r["dir"] in KNOWLEDGE]
    excl = [r for r in rows if r["dir"] in EXCLUDED]
    lines = [
        "# memory_index.md — 记忆路由表（P1 按需）",
        "",
        "> AUTO-GENERATED %s | DO NOT EDIT — 跑 `python eval/build_memory_index.py --apply`" % today,
        "> 权威源 `%s`；口径 = 磁盘实测目录树 + `eval/build_memory_index.py` 注解；"
        "门禁 = 焚诀 verify C33（存在性/非空/全覆盖/无占位残留）" % ROOT.replace("\\", "/"),
        "> 用法：先按「何时读」命中 1~2 个目录，再在该目录内点名文件；**禁止全量读取**。",
        "",
        "## 一、知识目录路由（%d 个，md 计数与最近日期为当日实测）" % len(known),
        "",
        "| 目录 | 何时读 | md | 最近更新 |",
        "|---|---|---|---|",
    ]
    for r in known:
        lines.append("| `%s/` | %s | %d | %s |" % (r["dir"], KNOWLEDGE[r["dir"]], r["md"],
                                                   r["newest"] or "—"))
    lines += ["", "## 二、常用入口（按任务类型直达）", "",
              "| 任务 | 先读 |", "|---|---|",
              "| 规则/铁律口径 | `core/behavior_core.md` |",
              "| 报错/排查/复发问题 | `lessons/` 按领域分卷（先查 lessons.md 索引） |",
              "| 继续上次/冷启动 | `memory/` 当日与昨日日志 + `memory/07-next-steps.md`（含分卷） |",
              "| 技能路由 | 焚诀 `eval/unified_router.py`（数据层 `skill_content/`、`skill_routing.md`） |",
              "| 治理口径（大文件/退役/版本锁） | `meta/` 下 bigfile_governance / retire_policy / VERSION_LOCK |",
              "", "## 三、非记忆目录（显式排除，禁作检索源）", "",
              "| 目录 | 排除理由 |", "|---|---|"]
    for r in excl:
        lines.append("| `%s/` | %s |" % (r["dir"], EXCLUDED[r["dir"]]))
    unclassified = [r["dir"] for r in rows if r["dir"] not in KNOWLEDGE and r["dir"] not in EXCLUDED]
    lines += ["", "## 四、覆盖自检", "",
              "- 一级目录 %d 个 = 知识 %d + 排除 %d%s"
              % (len(rows), len(known), len(excl),
                 "；**未归类 %s**" % unclassified if unclassified else "（全覆盖，无未归类）"),
              "- 生成器：焚诀 `eval/build_memory_index.py`；本表若与磁盘不符即 C33 红"]
    return "\n".join(lines) + "\n"


def declared_paths(text: str) -> list:
    """从渲染出的表里抽出所有反引号包裹的路径声明（供 C33 逐个实测存在且非空）。"""
    out = []
    for chunk in text.split("`")[1::2]:
        c = chunk.strip()
        if "/" in c and not c.endswith("/") and " " not in c and c.endswith(".md"):
            out.append(c)
    return out


def check_text(text: str, today: str | None = None, rows: list | None = None) -> tuple:
    """纯函数判据面（C33 与桩共用）：结构 + 死链 + 全覆盖 + 体积 + 残留。

    rows= 仅供桩注入合成目录表（让桩在 GM 根不可达的 CI 上也能跑真实判据分支，
    不必整批 SKIP——桩在 CI 上集体假绿过一次，就是因为把"外部不可达"直接等于"通过"）。
    """
    if rows is None:
        rows = scan()
        if not rows:
            return ("SKIP", "GM 根不可达（CI/异机最小环境），C33 保持本地判据面")
    # 占位符按其**真实形态**匹配（R3 D-11 原壳用的就是「（待重建）」），不匹配任何含该词的行——
    # 否则判据说明文字里提一次这个词就把自己判红（本仓当日第三次踩这类"注释触发断言"坑）
    placeholders = [tok for tok in ("（待重建）", "(待重建)", "待重建）") if tok in text]
    if placeholders:
        return ("FAIL", "W1 路由表仍含占位符 %s = 按需加载链未恢复（7-D 未完成）"
                        % ", ".join(placeholders))
    if len(text.encode("utf-8")) > MAX_BYTES:
        return ("FAIL", "W2 路由表 %d B > %d B（R161 4KB 硬顶）"
                        % (len(text.encode("utf-8")), MAX_BYTES))
    dead = []
    for decl in declared_paths(text):
        p = decl if os.path.isabs(decl) else os.path.join(ROOT, decl)
        if not os.path.exists(p):
            dead.append(decl)
        elif os.path.getsize(p) == 0:
            dead.append(decl + "(空文件)")
    if dead:
        return ("FAIL", "W3 路由声明死链 %d 处（R240：文档写了≠磁盘有）: %s"
                        % (len(dead), ", ".join(dead[:5])))
    listed = set()
    for line in text.splitlines():
        if line.startswith("| `"):
            listed.add(line.split("`")[1].strip("/"))
    dirs = {r["dir"] for r in rows}
    missing = sorted(dirs - listed)
    if missing:
        return ("FAIL", "W4 一级目录未登记 %d 个（新增目录必须归类为知识或排除）: %s"
                        % (len(missing), ", ".join(missing[:6])))
    ghost = sorted(listed - dirs)
    if ghost:
        return ("FAIL", "W5 路由表指向不存在目录 %s" % ", ".join(ghost[:5]))
    stale = [r["dir"] for r in rows if r["dir"] in KNOWLEDGE and r["md"] == 0]
    note = ("（注：%s 目录当前 0 个 md，表内已标注勿依赖）" % ", ".join(stale)) if stale else ""
    return ("PASS", "路由表 %d B / 一级目录全覆盖 %d 个（知识 %d + 排除 %d）/ 声明路径零死链 %s"
            % (len(text.encode("utf-8")), len(dirs), len(KNOWLEDGE), len(EXCLUDED), note))


def load_text(path: str = OUT) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成 GM 记忆路由表")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    if not os.path.isdir(ROOT):
        print("[memory_index] GM 根不可达（非本机环境）: %s" % ROOT)
        return 0
    today = datetime.date.today().isoformat()
    text = render(scan(), today)
    if getattr(a, "print"):
        print(text)
        return 0
    if a.apply:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        st, detail = check_text(load_text(a.out))
        print("已生成 %s (%d B) -> %s | %s" % (a.out, len(text.encode("utf-8")), st, detail))
        return 0 if st == "PASS" else 1
    if a.check:
        st, detail = check_text(load_text(a.out))
        print("[%s] %s" % (st, detail))
        return 0 if st == "PASS" else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
