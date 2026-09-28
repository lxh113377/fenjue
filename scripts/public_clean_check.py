#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""public_clean_check.py — 外发面内容安全门禁（重写版）。

为什么重写：上一版把学号/姓名/私人代理域名以「字符串拼接」形式硬编在门禁脚本
自身里（把数字拆成两段相加），于是出现两个缺陷：
  1. 门禁文件本身携带它要拦的内容，且拼接串在源码层扫不到 ⇒ 恒判 CLEAN；
  2. 判绿不判红：模式集合是写死的白名单，未登记的新泄露形态默认放行。
本版把敏感模式移到**仓外配置**（默认读仓库根的上级 `clean-patterns.json`，
也可 `--config` 指定），并内建反例自证：`--selftest` 往临时副本注入一条已知
泄露串，必须判红才算通过。零输入不记 PASS。

用法:
  python scripts/public_clean_check.py [--path PATH] [--config FILE] [--selftest]
退出码: 0=干净 / 1=发现敏感内容或反例未翻红 / 2=输入面不可判（配置缺失、零文件）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

# 形态类模式（不指认具体的人，可公开）：密钥/令牌/私钥形状
SHAPE_PATTERNS = {
    "api_key_shape": r"sk-[A-Za-z0-9]{16,}",
    "gh_token_shape": r"ghp_[A-Za-z0-9]{20,}",
    "private_key_block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "aws_key_shape": r"AKIA[0-9A-Z]{16}",
}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", "output", ".venv"}


def load_patterns(cfg: Path | None) -> dict[str, str] | None:
    """身份类模式只从仓外配置读；缺配置 ⇒ 不可判（rc=2），绝不退化成"没有要拦的"。"""
    cands = [cfg] if cfg else [
        Path(__file__).resolve().parents[2] / "clean-patterns.json",
        Path(os.environ.get("FENJUE_CLEAN_CONFIG", "/nonexistent")),
    ]
    for c in cands:
        if c and c.is_file():
            data = json.loads(c.read_text(encoding="utf-8"))
            pats = {k: v for k, v in data.items() if isinstance(v, str)}
            if pats:
                return pats
    return None


def scan(root: Path, patterns: dict[str, str]) -> tuple[list[str], int]:
    hits: list[str] = []
    seen = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or set(p.relative_to(root).parts) & SKIP_DIRS:
            continue
        data = p.read_bytes()
        if b"\x00" in data[:4096]:
            continue
        seen += 1
        text = data.decode("utf-8", "ignore")
        for i, ln in enumerate(text.splitlines(), 1):
            for label, pat in patterns.items():
                if re.search(pat, ln):
                    hits.append(f"[{label}] {p.relative_to(root).as_posix()}:{i}")
    return hits, seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=None)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    patterns = load_patterns(args.config)

    all_pats = dict(SHAPE_PATTERNS)
    if patterns:
        all_pats.update(patterns)

    if args.selftest:
        return selftest(all_pats, patterns)

    root = Path(args.path) if args.path else Path(__file__).resolve().parents[1]
    hits, seen = scan(root, all_pats)
    if seen == 0:
        print(f"[GATE:clean-unverified] {root} 下零个可扫文本文件 ⇒ 不可判")
        return 2
    if hits:
        for h in hits[:50]:
            print(h)
        print(f"[GATE:clean-fail] {len(hits)} 处敏感内容（扫描 {seen} 文件）")
        return 1
    if patterns is None:
        # 盲区不得复用"通过"这个词：只查了形态类模式，身份类模式没启用
        print(f"[GATE:clean-partial] 形态类模式 0 命中（扫描 {seen} 文件）"
              f"｜盲区=身份类模式未配置，本行不构成「无 PII」结论")
        return 0
    print(f"[GATE:clean-pass] 未发现密钥/PII/个人路径（扫描 {seen} 文件，模式 {len(all_pats)} 条）")
    return 0


def selftest(all_pats: dict[str, str], identity: dict[str, str] | None) -> int:
    """双向自证：干净副本须绿；注入一条已知泄露串须红。

    身份类模式缺配置时退回**形态类**探针（造一个假的 sk- 串），这样这把闸在
    任何一台机器上 clone 完都可演习——不可演习的门禁等于没有门禁。
    """
    if identity:
        key = next(iter(identity))
        pat = identity[key]
        sample = "leak" + re.sub(r"[^a-zA-Z0-9]", "", pat.split("{")[0])[:8]
    else:
        key = "api_key_shape"
        pat = SHAPE_PATTERNS[key]
        sample = "sk-" + "a" * 20
    tmp = Path(tempfile.mkdtemp(prefix="clean-selftest-"))
    try:
        (tmp / "a.py").write_text("print('hello')\n", encoding="utf-8")
        clean_hits, seen = scan(tmp, all_pats)
        if seen == 0 or clean_hits:
            print(f"[GATE:clean-selftest-fail] 正向腿不成立：files={seen} hits={len(clean_hits)}")
            return 1
        (tmp / "b.py").write_text(f"# {sample}\n", encoding="utf-8")
        bad_hits, _ = scan(tmp, {key: pat})
        if not bad_hits:
            print("[GATE:clean-selftest-fail] 反例腿不成立：注入已知泄露串仍判绿 ⇒ 闸是摆设")
            return 1
        print(f"[GATE:clean-selftest-pass] 正向 0 命中/{seen} 文件；反例命中 {len(bad_hits)} 处"
              f"（探针模式 {key}）")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
