#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cross_writer_idempotence.py — 多写入方产物「幂等性/契约一致性」门禁（R277，2026-09-22）

【为什么需要它】
但凡一个产物有 **≥2 个独立写入方**（尤其是跨语言、各自实现序列化），就必然存在
「谁最后写、产物就是谁的样子」的问题。2026-09-22 实测 `skill_content/{domain}.json`
同时被 3 处写：
  · `scan_skills.ps1`      — ConvertTo-Json -Compress（单行）→ 收尾调规范化器
  · `build_indexes.py`     — json.dump(indent=2)（pretty）
  · `add-to-routing.ps1`   — ConvertTo-Json -Depth 10（**无 [ordered]、无规范化**）
前两者逐字节等价（R275 收敛），**第三者会静默破坏对齐** —— 肉眼 diff 看不出来，
只有「交替跑 N 轮比 MD5」或「静态比对各写入方的序列化契约」才能发现。

【本门禁两层判据】
第一层 · 静态契约（默认，零副作用）：登记「产物 → 期望序列化契约」，自动扫出所有
    写入该产物的代码点，逐个校验其写法是否符合契约。任何新写入方一旦不合契约即 FAIL。
第二层 · 动态幂等（`--run` 才执行，重量级）：交替执行各写入方 N 轮，断言产物字节相等。
    会在磁盘上真实运行生成器，故默认不跑。

【边界】
- 只判「同一产物的多个写入方是否产出同一字节形态」，不判各自业务逻辑对错。
- 写入方清单由**自动扫描**得出（搜含产物路径标记的写入语句），避免人工登记遗漏。
- 动态层依赖真实执行，可能改变工作区内容 ⇒ 必须显式 `--run`，且建议先提交。

用法:
  python eval/cross_writer_idempotence.py            # 静态契约校验
  python eval/cross_writer_idempotence.py --run      # 追加动态交替幂等验证
  python eval/cross_writer_idempotence.py --json
退出码: 0=PASS / 1=FAIL
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import GLOBAL_MEMORY  # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_DIR = os.path.join(PROJECT_DIR, "eval")
GM_SCRIPTS = os.path.join(GLOBAL_MEMORY, "scripts")
GM_ROOT = GLOBAL_MEMORY

# ============================================================
# 契约登记：产物 → 期望序列化契约 + 合规写法 / 违规特征
# ============================================================
# 扫描根：这些目录下的脚本会被全文搜索「是否写该产物」
SCAN_DIRS = [EVAL_DIR, GM_SCRIPTS]
SCAN_EXTS = (".py", ".ps1")

# 已核实的合规写入方：登记后不再参与「违规特征」判定（其合规依据必须写明）
KNOWN_WRITERS = {
    "scan_skills.ps1": "用 -Compress 写单行，但收尾调用 normalize_skill_content.py 规范化 → 与 Python 侧字节等价（R275）",
    "build_indexes.py": "经 write_json_atomic → json.dump(ensure_ascii=False, indent=2)",
    "normalize_skill_content.py": "契约实现方：json.dumps(ensure_ascii=False, indent=2) + 原子替换",
    "add-to-routing.ps1": "写域 JSON，ConvertTo-Json 后**收尾调用 normalize_skill_content.py**（R277 补）",
}

# 写入方豁免：这些文件虽含产物标记与写入调用，但不写「域 JSON」（已逐个核实）
WRITER_WHITELIST = {
    "consistency_consumers.py",       # 只读扫描器
    "skill_content_parse_guard.py",   # 只读门禁
    "derivative_watch.py",            # 写 derivative_manifest，不写域 JSON
    "check_index_refs.py",
    "run-health-check.ps1",           # 只读体检
    "cache_skills.ps1",               # 写缓存
}

CONTRACTS = {
    "skill_content/{domain}.json": {
        "desc": "域 JSON（13 个域文件；skill_ids.json / index_manifest.json 属非域文件，不在契约内）",
        # 自动发现：行内同时含「产物目录标记」与「写入调用」即视为写入方
        "artifact_markers": ["skill_content"],
        "write_calls": [r"json\.dump\(", r"write_json_atomic\(", r"ConvertTo-Json",
                        r"WriteAllText", r"Set-Content", r"Out-File"],
        # 非域文件排除：写这些名字的行不算写入方（它们由 build_indexes 独占）
        "skip_if_line_has": ["skill_ids.json", "index_manifest.json", "NON_DOMAIN_FILES",
                            "DOMAIN_FILE_SKIPS"],
        # 合规判据（任一成立即视为合规）
        "ok_patterns": {
            "python_atomic": r"write_json_atomic\(",
            "python_indent2": r"json\.dump\([^)]*indent\s*=\s*2",
            "ps_normalized": r"normalize_skill_content",
            "ps_ordered": r"\[ordered\]",
        },
        # 违规特征（命中即 FAIL，除非同文件满足合规判据）
        "bad_patterns": {
            "ps_compress_no_norm": r"ConvertTo-Json[^\n]*-Compress",
            "ps_bare_convert": r"ConvertTo-Json(?!.*\[ordered\])",
        },
        "note": "R275 收敛点：ensure_ascii=False / indent=2 / 无结尾换行 / [ordered] 键序 / Ordinal 排序 / 无 generated",
    },
    # 注：`skill_content/skill_ids.json` 与 `index_manifest.json` **不列入本契约表** ——
    # 它们由 build_indexes.refresh_index_manifest / index_integrity 独占生成（单写入方），
    # 不存在"多写入方互相覆盖"问题，属别的问题域。曾试图用 `single_writer: True`
    # 做文件级放宽，结果引入 4 项假失败（把写 derivative_manifest / 其它 json 的文件
    # 也算成写入方）—— 假失败比漏检更伤门禁信誉，故收窄：本表只登记**真多写入方产物**。
}

# 动态层：交替执行的写入方命令（--run 时使用）
DYNAMIC_ROUNDS = [
    ("scan_skills.ps1", ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                         os.path.join(GM_SCRIPTS, "scan_skills.ps1")]),
    ("build_indexes.py", [sys.executable, os.path.join(EVAL_DIR, "build_indexes.py"), "--apply"]),
]
DYNAMIC_WATCH_DIR = os.path.join(GM_ROOT, "skill_content")
DYNAMIC_SKIP = {"skill_ids.json", "index_manifest.json", "bge_embeddings.npy",
                "tfidf_matrix.npz", "tfidf_vectorizer.pkl"}


from io_utils import read_text as _io_read_text  # P1-5: 读写原语唯一实现


def read_text(path):
    return _io_read_text(path, errors='ignore')


def iter_scripts():
    for d in SCAN_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(SCAN_EXTS):
                yield os.path.join(d, fn)


def discover_writers(spec):
    """自动发现写入该产物的代码点（R277 三版收敛后的判据）。

    演进（每版都被自己的对照桩/实测打回）：
      v1 「行内同时含产物字面量 skill_content + 写入调用」→ **零命中**：写入方普遍用变量承载路径。
      v2 「文件含标记 + 文件含写入调用 → 整文件写入点全算」→ **大量误报 + 真凶被豁免**：
         `add-to-routing.ps1` 因文件里别处出现合规特征而被 file_ok 放过；
         `pre-cc-check.ps1`/`auto-fix.ps1` 等只在正文提及 skill_content 也被当作写入方。
      v3（本版）**数据流精准 + 显式登记**：
         ① 提取「被赋值为含产物标记表达式的变量名」（path_vars），写入点必须**同行使用该变量**
            或同行含产物字面量 —— 这才是真的写这个产物；
         ② 已核实合规的写入方进 KNOWN_WRITERS（含合规依据），动态发现的**未登记**者才参与契约校验。
    """
    found = []
    call_re = re.compile("|".join(spec["write_calls"]))
    marker_re = re.compile("|".join(re.escape(m) for m in spec["artifact_markers"]))
    for path in iter_scripts():
        base = os.path.basename(path)
        if base == os.path.basename(__file__):
            continue
        text = read_text(path)
        if not marker_re.search(text):
            continue
        # ① 路径变量集合：x = ... skill_content ...  /  $JsonPath = Join-Path ... "skill_content\..."
        path_vars = set()
        for line in text.splitlines():
            m = re.match(r"\s*(?:my\s+)?\$?([A-Za-z_]\w*)\s*=", line)
            if m and marker_re.search(line):
                path_vars.add(m.group(1))
        # ② 逐写入点：同行含写入调用，且（含产物字面量 或 含路径变量）
        for i, line in enumerate(text.splitlines(), 1):
            if not call_re.search(line):
                continue
            # 单写入方产物：写入行可能经常量间接引用路径（如 index_integrity 用 MANIFEST_NAME），
            # 行级无法命中 ⇒ 放宽为「文件含标记即候选」（误报风险低，因该产物本就只应有一个写入方）
            uses_artifact = spec.get("single_writer", False) or bool(marker_re.search(line)) or any(
                re.search(r"\$?" + re.escape(v) + r"\b", line) for v in path_vars)
            if not uses_artifact:
                continue
            if any(s in line for s in spec.get("skip_if_line_has", [])):
                continue
            found.append((path, i, line.strip(), base in KNOWN_WRITERS))
    return found


def check_static():
    failures, notes = [], []
    for artifact, spec in CONTRACTS.items():
        writers = discover_writers(spec)
        if not writers:
            failures.append(f"[{artifact}] 未发现任何写入方（判据面失效，R247）")
            continue
        bad_res = [(n, re.compile(p)) for n, p in spec["bad_patterns"].items()]
        for path, ln, line, registered in writers:
            rel = os.path.basename(path)
            if registered:
                notes.append(f"[{artifact}] {rel}:{ln} 已登记合规 ✔")
                continue
            # 未登记写入方：只要命中违规特征即 FAIL（不再做宽松的文件级豁免）
            hits = [n for n, r in bad_res if r.search(line)]
            if hits:
                failures.append(
                    f"[{artifact}] {rel}:{ln} **未登记的写入方**且写法不合契约"
                    f"（{'/'.join(hits)}）→ {line[:88]}")
            else:
                notes.append(f"[{artifact}] {rel}:{ln} 未登记但未命中违规特征（建议补登记）⚠")
    return failures, notes


def snapshot():
    out = {}
    if not os.path.isdir(DYNAMIC_WATCH_DIR):
        return out
    import hashlib
    for fn in sorted(os.listdir(DYNAMIC_WATCH_DIR)):
        if not fn.endswith(".json") or fn in DYNAMIC_SKIP:
            continue
        p = os.path.join(DYNAMIC_WATCH_DIR, fn)
        with open(p, "rb") as fh:
            out[fn] = hashlib.md5(fh.read()).hexdigest()
    return out


def check_dynamic():
    """交替执行写入方 N 轮，断言产物字节全等。仅在 --run 时调用。"""
    fails, log = [], []
    snaps = []
    for rnd in range(1, len(DYNAMIC_ROUNDS) * 2 + 1):
        name, cmd = DYNAMIC_ROUNDS[(rnd - 1) % len(DYNAMIC_ROUNDS)]
        try:
            subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=True, timeout=900)
        except Exception as exc:  # noqa: BLE001
            fails.append(f"第 {rnd} 轮执行 {name} 失败: {exc}")
            break
        s = snapshot()
        uniq = len(set(s.values()))
        log.append(f"  第 {rnd} 轮 {name:18s} → {len(s)} 文件 / 唯一 hash {uniq}")
        snaps.append(s)
    if len(snaps) >= 2:
        base = snaps[-2]
        for i, s in enumerate(snaps):
            if s != base and i != len(snaps) - 1:
                diff = [k for k in s if base.get(k) != s.get(k)]
                fails.append(f"第 {i+1} 轮与倒数第二轮不一致，差异文件: {diff}")
    return fails, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--run", action="store_true",
                    help="追加动态交替幂等验证（会真实运行生成器，改工作区内容）")
    args = ap.parse_args()

    failures, notes = check_static()
    dyn_fails, dyn_log = ([], [])
    if args.run:
        dyn_fails, dyn_log = check_dynamic()
        failures += dyn_fails

    if args.json:
        print(json.dumps({"contracts": len(CONTRACTS), "failures": failures,
                          "dynamic_log": dyn_log, "pass": not failures},
                         ensure_ascii=False, indent=2))
        return 1 if failures else 0

    print("=" * 70)
    print("cross_writer_idempotence — 多写入方产物契约一致性 / 幂等性（R277）")
    print("=" * 70)
    print(f"契约产物 {len(CONTRACTS)} 个 | 扫描目录 {len(SCAN_DIRS)} | 模式 {'静态+动态' if args.run else '静态'}")
    print()
    for n in notes:
        print(f"  ✔ {n}")
    if dyn_log:
        print()
        for ln in dyn_log:
            print(ln)
    print()
    if failures:
        print(f"❌ FAIL — {len(failures)} 项:")
        for f in failures:
            print(f"  - {f}")
        print("\n处置：把违规写入方改为契约写法（Python 走 write_json_atomic / PS 走 [ordered]+规范化器，")
        print("      或在该写入方收尾调用 normalize_skill_content.py），使其与同产物其它写入方字节等价。")
        return 1
    print("✅ PASS — 所有多写入方产物的写入方式均符合契约")
    return 0


if __name__ == "__main__":
    sys.exit(main())
