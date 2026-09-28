"""降级重建脚本：torch 损坏时重建 TF-IDF + 域 JSON + disk_manifest，裁剪旧 BGE 向量。

用法: python eval/rebuild_no_bge.py
背景: 系统 torch 2.12.1 安装损坏（AppData site-packages 缺 lib DLL，import 即 access
violation），build_indexes.py --apply 全量 BGE 编码路径不可用。本脚本复用 build_indexes
的纯函数（collect_skills/build_tfidf/_write_all），BGE 向量从旧基线裁剪到注册表条数
（对应 unified-skills-index.json），TF-IDF 全新构建，保证 conserve_check 全绿。

R201 自动差集（2026-08-15）: 已删技能不再硬编码 DEAD 集合——每次运行自动计算
「旧 BGE 清单 − 注册表技能集」= 已删技能，后续删除技能无需再手动改本脚本。
基线说明: bge_fullbody_skills.json / bge_fullbody_embeddings.npy 是 git 跟踪的
213 行全量基线；若被上一次运行覆盖成 records 顺序导致与 npy 脱同步（断言失败），
先 `git checkout HEAD -- eval/bge_fullbody_skills.json eval/bge_fullbody_embeddings.npy eval/bge_fullbody_meta.json` 恢复。
"""
from __future__ import annotations

import os
import sys

import numpy as np

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

import build_indexes as bi  # noqa: E402

EVAL_DIR = bi.EVAL_DIR
SKILL_CONTENT = bi.SKILL_CONTENT


def load_old_bge():
    """读旧 BGE 向量与技能清单，按注册表差集自动裁剪。

    已删技能 = 旧 BGE 清单 − 注册表技能集（自动识别，无需手动维护）。
    新增技能（注册表有、旧 BGE 无）无向量可用，仅警告，需 build_indexes 全量编码补齐。
    """
    old_skills = bi.load_json(os.path.join(EVAL_DIR, "bge_fullbody_skills.json"))
    old_arr = np.load(os.path.join(EVAL_DIR, "bge_fullbody_embeddings.npy"))
    assert old_arr.shape[0] == len(old_skills), (
        f"旧 BGE 行数 {old_arr.shape[0]} != 清单 {len(old_skills)}（基线被污染）——"
        f"先恢复基线: git checkout HEAD -- eval/bge_fullbody_skills.json "
        f"eval/bge_fullbody_embeddings.npy eval/bge_fullbody_meta.json"
    )
    reg = bi.load_json(bi.REGISTRY_FILE)
    reg_names = set(reg.get("skills", {}))
    old_names = [s["name"] for s in old_skills]

    # 自动差集：旧 BGE 有、注册表无 = 已删技能
    dead = set(old_names) - reg_names
    added = reg_names - set(old_names)  # 注册表有、旧 BGE 无 = 新增技能
    if added:
        print(f"⚠ 注册表比旧 BGE 多 {len(added)} 个新技能（旧 BGE 无向量，"
              f"需 build_indexes.py --apply 全量编码补齐）: {sorted(added)[:5]}")
    if dead:
        print(f"自动识别已删技能 {len(dead)} 个: {sorted(dead)}")
    keep_idx = [i for i, s in enumerate(old_skills) if s["name"] not in dead]
    keep_names = {old_skills[i]["name"] for i in keep_idx}
    extra = keep_names - reg_names
    if extra:
        print(f"⚠ 裁剪后 BGE 仍多 {sorted(extra)[:5]}（不应发生，请检查注册表）")
    new_arr = old_arr[keep_idx]
    new_skills = [old_skills[i] for i in keep_idx]
    print(f"BGE 裁剪: {old_arr.shape[0]} → {new_arr.shape[0]} 行")
    return new_arr, new_skills


def main():
    records = bi.collect_skills()
    summary = bi.plan_summary(records)
    print(f"收集 {len(records)} 条 skill（global_skills {summary['global_skills']} + plugin {summary['openclaw_plugin']}）")

    bodies = [r["body"] for r in records]
    print("构建 TF-IDF（同源语料，无 torch 依赖）...")
    matrix, vectorizer = bi.build_tfidf(bodies)
    print(f"  TF-IDF shape: {matrix.shape}")

    new_arr, new_skills = load_old_bge()
    # 校验裁剪后 BGE 顺序与 records 顺序一致性（conserve_check 只查集合，这里尽力对齐）
    rec_names = [r["name"] for r in records]
    old_names = [s["name"] for s in new_skills]
    if rec_names != old_names:
        print(f"⚠ records 顺序与 BGE 清单顺序不一致（{len(rec_names)} vs {len(old_names)}），"
              f"BGE 行序可能错位——将按 records 顺序重排 BGE 行")
        idx_map = {name: i for i, name in enumerate(old_names)}
        reordered = np.zeros_like(new_arr)
        for r_i, name in enumerate(rec_names):
            if name in idx_map:
                reordered[r_i] = new_arr[idx_map[name]]
        new_arr = reordered

    written = bi._write_all(records, new_arr, matrix, vectorizer)
    print(f"写入 {len(written)} 个派生件:")
    for w in written:
        print("  +", w)
    bi.refresh_index_manifest()
    print("+ skill_content/index_manifest.json")
    issues = bi.conserve_check()
    if issues:
        print("守恒校验 FAIL:", *issues, sep="\n  - ", file=sys.stderr)
        return 1
    print(f"守恒校验 PASS：双端集合/形状完全一致（{len(records)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
