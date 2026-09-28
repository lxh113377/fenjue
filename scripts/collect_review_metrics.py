"""月度代码审查指标采集器 (CODE_REVIEW.md §6).

通过 gh CLI 拉取当月已合并 PR, 生成 reports/code_review_metrics_YYYY-MM.md.
gh 不可用/未登录时输出可执行指引并非零退出; --sample 用内置样例数据演示.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

DIMENSIONS: tuple[str, ...] = (
    "正确性",
    "安全性",
    "SQL",
    "可维护性",
    "性能",
    "测试",
    "AI 生成代码",
    "规范",
)
MIN_CHECKED = 5


@dataclass
class PullRequest:
    number: int
    title: str
    created_at: datetime
    merged_at: datetime | None
    author: str
    body: str
    first_review_at: datetime | None
    changes_requested: bool
    red_count: int
    yellow_count: int


def resolve_gh() -> Path | None:
    """定位 gh 可执行文件 (兼容 Windows 下 PATH 被 0 字节占位遮蔽的情况)."""
    found = shutil.which("gh")
    if found:
        return Path(found)
    candidates = (
        Path(r"C:\Program Files\GitHub CLI\gh.exe"),
        Path("/usr/local/bin/gh"),
        Path("/opt/homebrew/bin/gh"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def run_gh(gh: Path, args: list[str]) -> str:
    """执行 gh 并返回 stdout; 失败时抛 CalledProcessError."""
    proc = subprocess.run([str(gh), *args], capture_output=True, text=True, check=True,
                          timeout=120)  # P1-6
    return proc.stdout.strip()


def detect_repo(gh: Path) -> str:
    """从当前 gh 上下文探测 owner/name."""
    try:
        return run_gh(gh, ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    except subprocess.CalledProcessError:
        return ""


def month_range(month: str) -> tuple[str, str]:
    """返回 [当月首日, 次月首日) 的搜索区间."""
    year_text, month_text = month.split("-")
    year = int(year_text)
    mon = int(month_text)
    start = f"{year:04d}-{mon:02d}-01"
    end = f"{year + 1:04d}-01-01" if mon == 12 else f"{year:04d}-{mon + 1:02d}-01"
    return start, end


def parse_dt(value: str | None) -> datetime | None:
    """解析 gh 返回的 ISO 时间; 解析失败返回 None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract_count(body: str, marker: str) -> int:
    """从 body 中 marker 后 40 字符内提取第一个数字 (度量字段计数)."""
    idx = body.find(marker)
    if idx < 0:
        return 0
    segment = body[idx : idx + 40]
    match = re.search(r"\d+", segment)
    return int(match.group(0)) if match else 0


def has_evidence(body: str) -> bool:
    """判定 PR body 是否含 5+1 维度 checklist 的机器证据."""
    if not all(dim in body for dim in DIMENSIONS):
        return False
    return len(re.findall(r"\[x\]", body, re.IGNORECASE)) >= MIN_CHECKED


def fetch_pull_requests(gh: Path, repo: str, month: str) -> list[dict[str, Any]]:
    """拉取当月已合并 PR 的元数据."""
    start, end = month_range(month)
    query = f"merged:{start}..{end}"
    raw = run_gh(
        gh,
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "merged",
            "--search",
            query,
            "--json",
            "number,title,createdAt,mergedAt,author,body",
            "--limit",
            "100",
        ],
    )
    data = json.loads(raw)
    items: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                items.append(cast(dict[str, Any], item))
    return items


def fetch_first_review(gh: Path, repo: str, number: int) -> tuple[datetime | None, bool]:
    """返回 (首次评审时间, 是否曾 CHANGES_REQUESTED)."""
    try:
        raw = run_gh(
            gh,
            [
                "api",
                f"repos/{repo}/pulls/{number}/reviews",
                "--paginate",
                "--jq",
                ".[] | [.submittedAt, .state] | @tsv",
            ],
        )
    except subprocess.CalledProcessError:
        return None, False
    first: datetime | None = None
    changes = False
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        submitted = parse_dt(parts[0])
        if submitted is not None and (first is None or submitted < first):
            first = submitted
        if parts[1].strip().upper() == "CHANGES_REQUESTED":
            changes = True
    return first, changes


def build_records(items: list[dict[str, Any]], gh: Path | None, repo: str) -> list[PullRequest]:
    """把 gh 原始数据组装为指标记录."""
    records: list[PullRequest] = []
    for item in items:
        number = int(item.get("number", 0))
        author_obj = item.get("author")
        author = author_obj.get("login", "?") if isinstance(author_obj, dict) else "?"
        body = str(item.get("body") or "")
        first_review: datetime | None = None
        changes = False
        if gh is not None and repo:
            first_review, changes = fetch_first_review(gh, repo, number)
        records.append(
            PullRequest(
                number=number,
                title=str(item.get("title", "")),
                created_at=parse_dt(item.get("createdAt")) or datetime.now(),
                merged_at=parse_dt(item.get("mergedAt")),
                author=author,
                body=body,
                first_review_at=first_review,
                changes_requested=changes,
                red_count=extract_count(body, "🔴"),
                yellow_count=extract_count(body, "🟡"),
            )
        )
    return records


def median(values: list[float]) -> float:
    """中位数; 空列表返回 0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def compute_summary(records: list[PullRequest]) -> dict[str, Any]:
    """按 CODE_REVIEW.md §6 五指标口径汇总."""
    total = len(records)
    with_evidence = sum(1 for r in records if has_evidence(r.body))
    changes = sum(1 for r in records if r.changes_requested)
    response_hours = [
        (r.first_review_at - r.created_at).total_seconds() / 3600.0
        for r in records
        if r.first_review_at is not None
    ]
    merge_hours = [
        (r.merged_at - r.created_at).total_seconds() / 3600.0
        for r in records
        if r.merged_at is not None
    ]
    return {
        "total": total,
        "coverage": (with_evidence / total) if total else 0.0,
        "rework_rate": (changes / total) if total else 0.0,
        "median_response_hours": median(response_hours),
        "median_merge_hours": median(merge_hours),
        "total_red": sum(r.red_count for r in records),
        "total_yellow": sum(r.yellow_count for r in records),
    }


def hours(after: datetime | None, before: datetime) -> float:
    """两个时间点的小时差; after 为空返回 0."""
    if after is None:
        return 0.0
    return round((after - before).total_seconds() / 3600.0, 1)


def sample_body(red: int, yellow: int) -> str:
    """构造符合 PR 模板的样例 body."""
    checks = "\n".join(f"- [x] {dim}" for dim in DIMENSIONS)
    return f"{checks}\n🔴 数量: {red}\n🟡 数量: {yellow}\n合并耗时: 5"


def sample_records() -> list[PullRequest]:
    """内置样例数据, 供无 gh 环境验证报告格式."""
    now = datetime.now()
    base_a = now.replace(hour=10, minute=0, second=0, microsecond=0)
    base_b = now.replace(hour=14, minute=30, second=0, microsecond=0)
    base_c = now.replace(hour=9, minute=15, second=0, microsecond=0)
    return [
        PullRequest(
            number=101,
            title="样例: 修复 mypy 门禁",
            created_at=base_a,
            merged_at=base_a,
            author="alice",
            body=sample_body(0, 1),
            first_review_at=base_a,
            changes_requested=True,
            red_count=0,
            yellow_count=1,
        ),
        PullRequest(
            number=102,
            title="样例: 启用 ruff C901",
            created_at=base_b,
            merged_at=base_b,
            author="bob",
            body=sample_body(1, 2),
            first_review_at=base_b,
            changes_requested=False,
            red_count=1,
            yellow_count=2,
        ),
        PullRequest(
            number=103,
            title="样例: 无审查证据",
            created_at=base_c,
            merged_at=base_c,
            author="carol",
            body="没有填写 checklist",
            first_review_at=None,
            changes_requested=False,
            red_count=0,
            yellow_count=0,
        ),
    ]


def build_report(month: str, records: list[PullRequest]) -> str:
    """生成 Markdown 月度指标报告."""
    summary = compute_summary(records)
    lines = [
        f"# 代码审查指标 {month}",
        "",
        f"> 采集时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 来源: scripts/collect_review_metrics.py",
        "",
        "## §6 指标汇总",
        "",
        "| 指标 | 值 | 口径 |",
        "|---|---|---|",
        f"| 审查覆盖率 | {summary['coverage']:.1%} | 已合并 PR 中含 5+1 证据比例 |",
        f"| 返工率 | {summary['rework_rate']:.1%} | CHANGES_REQUESTED 评审占比 |",
        f"| 审查响应时间(中位) | {summary['median_response_hours']:.1f} h | 首次 review - PR 创建 |",
        f"| 合并耗时(中位) | {summary['median_merge_hours']:.1f} h | merged - created |",
        f"| 缺陷密度(代理) | 🔴 {summary['total_red']} / 🟡 {summary['total_yellow']} | 每 PR 模板计数, 缺 KLOC 口径 |",
        "",
        "## PR 明细",
        "",
        "| # | 标题 | 作者 | 合并耗时 h | 响应 h | 🔴 | 🟡 | 证据 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for record in sorted(records, key=lambda r: r.number):
        lines.append(
            "| {n} | {title} | {author} | {merge_h} | {resp_h} | {red} | {yellow} | {evidence} |".format(
                n=record.number,
                title=record.title,
                author=record.author,
                merge_h=hours(record.merged_at, record.created_at),
                resp_h=hours(record.first_review_at, record.created_at),
                red=record.red_count,
                yellow=record.yellow_count,
                evidence="✅" if has_evidence(record.body) else "❌",
            )
        )
    lines.append("")
    return "\n".join(lines)


def guidance() -> str:
    """gh 不可用时的可执行指引."""
    return (
        "无法调用 gh: 指标采集需要 GitHub CLI。\n"
        "安装/修复方式: 1) 安装 https://cli.github.com 并确认 gh 在 PATH;\n"
        "2) 运行 gh auth login 完成认证; 3) 重跑本脚本。\n"
        "若仅想预览报告格式: 加 --sample 参数。"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="采集 CODE_REVIEW.md §6 月度指标")
    parser.add_argument("--month", default=datetime.now().strftime("%Y-%m"), help="YYYY-MM")
    parser.add_argument("--repo", default="", help="owner/name, 默认取 gh 当前仓库")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的采集动作")
    parser.add_argument("--sample", action="store_true", help="用内置样例数据生成报告")
    parser.add_argument("--out", default="", help="输出文件路径, 默认 reports/ 下")
    args = parser.parse_args()

    if args.sample:
        records = sample_records()
    else:
        gh = resolve_gh()
        if gh is None:
            print(guidance())
            return 2
        repo = args.repo or detect_repo(gh)
        if not repo:
            print("无法确定仓库: 请传 --repo owner/name, 或在已登录仓库目录内运行")
            return 2
        if args.dry_run:
            print(f"[dry-run] 将拉取 {repo} {args.month} 已合并 PR 并生成 §6 指标报告")
            return 0
        items = fetch_pull_requests(gh, repo, args.month)
        records = build_records(items, gh, repo)

    report = build_report(args.month, records)
    out_path = (
        Path(args.out) if args.out else Path("reports") / f"code_review_metrics_{args.month}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"已生成: {out_path} (PR 数: {len(records)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
