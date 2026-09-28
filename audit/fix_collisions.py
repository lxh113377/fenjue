#!/usr/bin/env python3
"""修复高风险跨域触发词 — 为泛化词添加领域特化触发词"""
import json
import glob
import os
from pathlib import Path

SKILL_CONTENT = r"<MEMORY_ROOT>\skill_content"

# 每个高风险词的修复策略：保留原词 + 添加领域特化词
FIXES = {
    # R201: local-* AIPC 系列已删（本机非 AIPC），仅保留仍在的 windows-* 编码技能
    "windows-gitbash-chinese-path-pit": ["Git Bash中文路径", "Git Bash乱码"],
    "windows-cli-utf8-wrapper": ["Windows CLI编码", "subprocess乱码"],
    
    # 其他高风险词 → 添加领域消歧触发词
    "A-project-handoff":        ["项目交接", "项目记忆初始化"],  # memory→加项目特有词
    "bigfile-split":            ["文件拆分", "4KB限制"],  # memory→加拆分特有词
}

def main():
    fixed = 0
    for fpath in sorted(glob.glob(os.path.join(SKILL_CONTENT, "*.json"))):
        bn = os.path.basename(fpath)
        if bn in ("embeddings.npy", "skill_ids.json", "tfidf_matrix.npz", "tfidf_vectorizer.pkl"):
            continue
        data = json.loads(Path(fpath).read_text(encoding="utf-8"))
        changed = False
        for s in data.get("skills", []):
            name = s["name"]
            if name in FIXES:
                existing = set(s.get("triggers", []))
                new_triggers = [t for t in FIXES[name] if t not in existing]
                if new_triggers:
                    s["triggers"] = list(existing) + new_triggers
                    changed = True
        if changed:
            Path(fpath).write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            count = sum(1 for s in data["skills"] if s["name"] in FIXES)
            print(f"[FIXED] {bn}: {count} skills +领域消歧触发词")
            fixed += count
    print(f"\n总计: {fixed} 个 skill 添加了领域消歧触发词")

if __name__ == "__main__":
    main()
