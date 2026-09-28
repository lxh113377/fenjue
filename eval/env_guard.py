#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_guard.py — 环境隔离检查（R196，缺口-4 / 七.4）

读取 env_mode（memory/06-constraints.md 的 `env_mode:` 行或 ENV_MODE 环境变量）：
  - development/staging：仅输出模式确认。
  - production：校验近期备份（DR 快照 D:\\fenjue_backup\\... 或项目 archive/）、
    sk- 密钥泄露（复用 eval/scan_secrets.py）、.env.prod/.env.production 是否
    被 git 跟踪（保护规则被破坏则 WARN）。
所有发现均为 WARN，不阻断（退出码 0）；避免失败预算变成流程税。

用法:
  python eval/env_guard.py [--project <path>] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)

CONSTRAINTS_REL = os.path.join("memory", "06-constraints.md")
ARCHIVE_REL = "archive"
DR_SNAPSHOT_ROOT = r"D:\fenjue_backup\global_memory-snapshots"
PROTECTED_ENV_FILES = (".env.prod", ".env.production", ".env.local")
BACKUP_STALE_DAYS = 7


def read_env_mode(project: str) -> str | None:
    """env_mode 优先级：ENV_MODE 环境变量 > 06-constraints.md 声明行。"""
    env = os.environ.get("ENV_MODE", "").strip().lower()
    if env in ("development", "staging", "production"):
        return env
    path = os.path.join(project, CONSTRAINTS_REL)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    m = re.search(r"env_mode[:：]\s*(\w+)", text, re.IGNORECASE)
    if not m:
        return None
    mode = m.group(1).strip().lower()
    return mode if mode in ("development", "staging", "production") else None


def latest_backup_ts() -> datetime | None:
    """DR 快照目录或项目 archive/ 的最新 mtime。"""
    candidates = []
    if os.path.isdir(DR_SNAPSHOT_ROOT):
        for name in os.listdir(DR_SNAPSHOT_ROOT):
            full = os.path.join(DR_SNAPSHOT_ROOT, name)
            if os.path.isdir(full):
                candidates.append(full)
    archive = os.path.join(PROJECT_DIR, ARCHIVE_REL)
    if os.path.isdir(archive):
        candidates.append(archive)
    if not candidates:
        return None
    latest = max(os.path.getmtime(c) for c in candidates)
    return datetime.fromtimestamp(latest)


def check_backup_recency() -> tuple[bool, str]:
    ts = latest_backup_ts()
    if ts is None:
        return False, "未找到备份源（DR 快照 D:\\fenjue_backup 或项目 archive/）"
    if datetime.now() - ts > timedelta(days=BACKUP_STALE_DAYS):
        return False, f"最近备份超过 {BACKUP_STALE_DAYS} 天（{ts:%Y-%m-%d %H:%M}）"
    return True, f"最近备份 {ts:%Y-%m-%d %H:%M}（{BACKUP_STALE_DAYS} 天内）"


def check_secrets(project: str) -> tuple[bool, str]:
    script = os.path.join(project, "eval", "scan_secrets.py")
    if not os.path.exists(script):
        return False, "scan_secrets.py 缺失"
    try:
        r = subprocess.run([sys.executable, script], cwd=project,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
    except Exception as e:
        return False, f"scan_secrets 执行异常: {e!r}"
    if r.returncode != 0:
        return False, (r.stdout or r.stderr or "secret-scan FAIL").strip()[-300:]
    return True, "无 sk- 密钥泄露"


def check_env_file_protection(project: str) -> tuple[bool, str]:
    """.env.prod 等保护文件若被 git 跟踪 = 保护规则失效。"""
    tracked = []
    for name in PROTECTED_ENV_FILES:
        path = os.path.join(project, name)
        if os.path.exists(path):
            try:
                r = subprocess.run(
                    ["git", "ls-files", "--error-unmatch", "--", name],
                    cwd=project, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=60)
                if r.returncode == 0:
                    tracked.append(name)
            except Exception:
                # 探测失败→跳过该文件=放行（.gitignore 失效风险仅正常 git 仓内
                # git 命令异常时可能出现；此处留痕避免"保护文件被跟踪"静默漏检，
                # R207 P2-1）。如需 fail-closed 可改 except 时 append 保守上报。
                pass
    if tracked:
        return False, f"保护文件被 git 跟踪（.gitignore 失效）: {', '.join(tracked)}"
    return True, "保护文件未入库（.gitignore 生效）"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="环境隔离检查（R196）")
    p.add_argument("--project", default=PROJECT_DIR)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    project = os.path.abspath(args.project)
    mode = read_env_mode(project)

    checks = []
    if mode is None:
        checks.append({
            "name": "env_mode 声明",
            "pass": False,
            "detail": "06-constraints.md 未声明 env_mode（development/staging/production），建议 init 模板补写",
        })
    elif mode == "production":
        ok, detail = check_backup_recency()
        checks.append({"name": "备份新鲜度", "pass": ok, "detail": detail})
        ok, detail = check_secrets(project)
        checks.append({"name": "密钥泄露", "pass": ok, "detail": detail})
        ok, detail = check_env_file_protection(project)
        checks.append({"name": ".env.prod 入库保护", "pass": ok, "detail": detail})
    else:
        checks.append({"name": "env_mode 确认", "pass": True,
                       "detail": f"当前模式 {mode}：无需生产级检查"})

    payload = {
        "schema": "fenjue-env-guard-v1",
        "env_mode": mode,
        "project": project,
        "all_warn": not any(c["pass"] for c in checks),
        "checks": checks,
        "note": "环境隔离为 WARN 不阻断；production 建议满足全部检查后再操作",
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"[env_guard] env_mode = {mode or '未声明'}")
        for c in checks:
            flag = "OK ✅" if c["pass"] else "WARN ⚠️"
            print(f"[{flag}] {c['name']} — {c['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
