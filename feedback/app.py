#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feedback/app.py — 用户反馈通道（R194 闭环补全）

Web 按钮 + JSONL 落盘 + savepoint 联动 + 周维护转 lessons。

启动（默认 127.0.0.1:8787，自动开浏览器）:
    python feedback/app.py

CLI:
    python feedback/app.py --summary              # 按类别/严重度/open 统计
    python feedback/app.py --close <id>           # 标记 closed
    python feedback/app.py --file <path>          # 覆盖 JSONL 路径（测试/多项目）
    python feedback/app.py --port 8788 --no-browser

JSONL schema（每行一条）:
    id/ts/session/task/wrong/expected/category/severity/recovered/source/status
    category 枚举: 方向理解/工具调用/记忆续接/代码结果/评测判定/其他
    severity 枚举: 低/中/高/致命
    status: open/closed（--close 后附 closed_ts）
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_JSONL = os.path.join(PROJECT_ROOT, "feedback", "feedback.jsonl")

CATEGORIES = ("方向理解", "工具调用", "记忆续接", "代码结果", "评测判定", "其他")
SEVERITIES = ("低", "中", "高", "致命")
STATUSES = ("open", "closed")
REQUIRED = ("task", "wrong", "expected")

# R196：关键词自动分类（覆盖-4 / 八.1）——命中顺序即优先级
CLASSIFY_KEYWORDS = {
    "方向理解": ("方向", "理解错", "没明白", "跑偏", "目标理解", "需求误解", "答非所问"),
    "工具调用": ("工具", "调用", "skill", "技能", "没加载", "路由", "工具不存在", "not found"),
    "记忆续接": ("记忆", "断片", "上下文", "续接", "忘记", "忘了", "接不上"),
    "代码结果": ("代码", "报错", "bug", "错误", "结果不对", "运行失败", "编译", "异常", "traceback"),
    "评测判定": ("评分", "分给低", "误判", "判定", "评测", "打分"),
}
ROUTE_SUGGESTIONS = {
    "方向理解": "路由到 A-ask-questions / 07 P0 目标对齐复查",
    "工具调用": "路由到 A-memory-start 路由诊断（skill-trigger-diagnosis）",
    "记忆续接": "路由到 A-project-handoff 续接复核（07 P0 + archive）",
    "代码结果": "路由到 A-get-memory 四维反思 → lessons 沉淀",
    "评测判定": "路由到 fenjue-advisor-scoring 独立复核",
    "其他": "直接答复；必要时登记 07 P0",
}


def classify_feedback(text: str) -> str:
    """按关键词自动分类，未命中返回「其他」。"""
    low = str(text or "").lower()
    for category, kws in CLASSIFY_KEYWORDS.items():
        if any(kw.lower() in low for kw in kws):
            return category
    return "其他"


def route_feedback(category: str) -> str:
    return ROUTE_SUGGESTIONS.get(category, ROUTE_SUGGESTIONS["其他"])


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def load_entries(path: str | None = None) -> list[dict]:
    """读取 JSONL，损坏行跳过（不阻断）。"""
    path = path or DEFAULT_JSONL
    if not os.path.exists(path):
        return []
    rows = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def validate_entry(entry: dict) -> list[str]:
    """返回错误列表；空列表 = 合法。"""
    errors = []
    for key in REQUIRED:
        if not str(entry.get(key) or "").strip():
            errors.append(f"{key} 必填")
    if entry.get("category") not in CATEGORIES:
        errors.append(f"category 非法: {entry.get('category')!r}")
    if entry.get("severity") not in SEVERITIES:
        errors.append(f"severity 非法: {entry.get('severity')!r}")
    if entry.get("status") not in STATUSES:
        errors.append(f"status 非法: {entry.get('status')!r}")
    return errors


def append_entry(entry: dict, path: str | None = None) -> str:
    """校验并追加一条反馈，返回 id。id 重复或字段非法抛 ValueError。"""
    path = path or DEFAULT_JSONL
    errors = validate_entry(entry)
    if errors:
        raise ValueError("; ".join(errors))
    entry.setdefault("id", uuid.uuid4().hex[:12])
    entry.setdefault("ts", now_iso())
    entry.setdefault("session", "")
    entry.setdefault("category", "其他")
    entry.setdefault("severity", "中")
    entry.setdefault("recovered", False)
    entry.setdefault("source", "web")
    entry.setdefault("status", "open")
    existing_ids = {row.get("id") for row in load_entries(path)}
    if entry["id"] in existing_ids:
        raise ValueError(f"id 重复: {entry['id']}")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry["id"]


def summarize(path: str | None = None) -> dict:
    """按类别/严重度/open 统计。"""
    rows = load_entries(path)
    out = {
        "total": len(rows),
        "open": 0,
        "closed": 0,
        "by_category": {},
        "by_severity": {},
        "open_items": [],
    }
    for row in rows:
        cat = row.get("category", "其他")
        sev = row.get("severity", "中")
        status = row.get("status", "open")
        out["by_category"][cat] = out["by_category"].get(cat, 0) + 1
        out["by_severity"][sev] = out["by_severity"].get(sev, 0) + 1
        if status == "open":
            out["open"] += 1
            out["open_items"].append({
                "id": row.get("id"),
                "severity": sev,
                "category": cat,
                "task": str(row.get("task") or "")[:60],
            })
        else:
            out["closed"] += 1
    return out


def close_entry(entry_id: str, path: str | None = None) -> bool:
    """把 open 条目标记为 closed；条目不存在/已 closed 返回 False。"""
    path = path or DEFAULT_JSONL
    rows = load_entries(path)
    changed = False
    for row in rows:
        if row.get("id") == entry_id and row.get("status") != "closed":
            row["status"] = "closed"
            row["closed_ts"] = now_iso()
            changed = True
    if not changed:
        return False
    Path(path).write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8")
    return True


HTML_FORM = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>焚诀反馈通道</title>
  <style>
    body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#222}
    h1{font-size:20px}label{display:block;margin:14px 0 4px;font-size:14px;font-weight:600}
    input[type=text],textarea,select{width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccc;border-radius:6px;font-size:14px}
    textarea{min-height:64px}button{margin-top:18px;padding:10px 22px;border:0;border-radius:6px;background:#d33;color:#fff;font-size:15px;cursor:pointer}
    #msg{margin-top:12px;font-size:14px}.ok{color:#1a7f37}.err{color:#c00}
  </style>
</head>
<body>
  <h1>反馈通道 — 告诉我这次哪里错了</h1>
  <form id="f">
    <label>会话/任务（手动填，便于定位对话）</label>
    <input type="text" name="session">
    <label>任务（必填）</label>
    <input type="text" name="task" required>
    <label>哪里错了（必填）</label>
    <textarea name="wrong" required></textarea>
    <label>期望行为（必填）</label>
    <textarea name="expected" required></textarea>
    <label>类别</label>
    <select name="category">
      <option>方向理解</option><option>工具调用</option><option>记忆续接</option>
      <option>代码结果</option><option>评测判定</option><option>其他</option>
    </select>
    <label>严重度</label>
    <select name="severity">
      <option>低</option><option>中</option><option>高</option><option>致命</option>
    </select>
    <label><input type="checkbox" name="recovered" value="1"> 已自行恢复</label>
    <button type="submit">提交反馈</button>
  </form>
  <div id="msg"></div>
  <script>
    document.getElementById('f').addEventListener('submit', async e => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const msg = document.getElementById('msg');
      try {
        const r = await fetch('/api/feedback', {method:'POST', body: fd});
        const j = await r.json();
        if (r.ok) { msg.className='ok'; msg.textContent = '已收到，id=' + j.id; e.target.reset(); }
        else { msg.className='err'; msg.textContent = '失败: ' + j.error; }
      } catch (err) {
        msg.className='err'; msg.textContent = '网络错误: ' + err;
      }
    });
  </script>
</body>
</html>
"""


def build_app(jsonl_path: str | None = None):
    """构造 Flask 应用（测试用 test_client；生产直接 main() 启动）。"""
    from flask import Flask, jsonify, request

    app = Flask(__name__)
    data_file = jsonl_path or DEFAULT_JSONL

    @app.get("/")
    def index():
        return HTML_FORM

    @app.post("/api/feedback")
    def api_feedback():
        payload = request.get_json(silent=True) or request.form.to_dict()
        if isinstance(payload.get("recovered"), str):
            payload["recovered"] = payload["recovered"].lower() in ("1", "true", "on", "yes")
        # R196 自动分类：未选或默认「其他」时按 wrong+expected+task 关键词预填
        if payload.get("category") in (None, "", "其他"):
            payload["category"] = classify_feedback(
                f"{payload.get('task', '')} {payload.get('wrong', '')} "
                f"{payload.get('expected', '')}")
        payload.setdefault("source", "web")
        payload.setdefault("status", "open")
        try:
            fid = append_entry(payload, data_file)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "id": fid}), 201

    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="焚诀用户反馈通道")
    parser.add_argument("--summary", action="store_true", help="统计")
    parser.add_argument("--close", metavar="ID", help="标记条目 closed")
    parser.add_argument("--file", metavar="PATH", help="JSONL 路径覆盖")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    data_file = args.file or DEFAULT_JSONL

    if args.summary:
        s = summarize(data_file)
        print(f"total={s['total']} open={s['open']} closed={s['closed']}")
        print("by_category: " + ", ".join(f"{k}={v}" for k, v in sorted(s["by_category"].items())))
        print("by_severity: " + ", ".join(f"{k}={v}" for k, v in sorted(s["by_severity"].items())))
        for item in s["open_items"]:
            cat = item.get("category", "其他")
            print(f"  open [{item['severity']}] {item['id']}: {item['task']} "
                  f"({cat} → {route_feedback(cat)})")
        return 0

    if args.close:
        ok = close_entry(args.close, data_file)
        if ok:
            print(f"closed: {args.close}")
            return 0
        print(f"未找到或已 closed: {args.close}")
        return 1

    app = build_app(data_file)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"反馈通道: {url} (JSONL: {data_file})")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    sys_exit = main()
    if isinstance(sys_exit, int):
        raise SystemExit(sys_exit)
