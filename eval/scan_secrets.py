#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan_secrets.py — 全仓凭据泄露扫描（CI/pre-commit 复用，R192；R207 N3 扩模式）。

覆盖形态: OpenAI sk- / GitHub ghp_·github_pat_·gho_ / Slack xox* / AWS AKIA /
Google AIza / Stripe sk_live_ / 私钥块头。命中任一即 FAIL。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# R207 N3: 单模式 -> 多模式集（原 sk- 保留）。误报控制：每模式带足长度/字符类门槛。
SECRET_RES = [
    # OpenAI / 通用 sk- 形态（R192 原单模式）
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    # GitHub: ghp_ 个人令牌 / github_pat_ 细粒度令牌 / gho_ OAuth app
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{22,}"),
    # Slack: xoxb- bot / xoxa app / xoxp user / xoxr / xoxs
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    # AWS Access Key ID
    re.compile(r"AKIA[0-9A-Z]{16}"),
    # Google API Key
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    # Stripe live secret key
    re.compile(r"sk_live_[0-9a-zA-Z]{20,}"),
    # 私钥块头（RSA/EC/OPENSSH/DSA/PGP 或裸）
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
]
SKIP_DIRS = {
    ".git", ".cache", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "archive", "__pycache__", "memory", "memory_content", "prompts",
    # P2-4（2026-09-23）：_bak 移出豁免 —— 备份区泄露凭据同样在盘，须纳入扫描
    # （实测移除后全量扫描 0 误报）；_trash/_temp 维持 R207 豁免（回收/临时区，非交付面）
    "_trash", "_temp",
}


def main() -> int:
    bad = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        for res in SECRET_RES:
                            if res.search(line):
                                bad.append(f"{os.path.relpath(p, ROOT)}:{i} ({res.pattern})")
                                break
            except OSError:
                continue
    if bad:
        print("secret-scan FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    print("secret-scan PASS: 无泄露凭据")
    return 0


if __name__ == "__main__":
    sys.exit(main())
