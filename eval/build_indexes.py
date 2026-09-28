#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_indexes.py — 焚诀数据层单一生成器（R193 阶段1）
=====================================================================
统一从注册表 + 磁盘 SKILL.md 双源生成派生索引（条数 = 注册表 skill 数，动态），双写双校验：

  eval 侧（本仓库，BGE 三件套入库）:
    bge_fullbody_embeddings.npy
    bge_fullbody_skills.json
    bge_fullbody_meta.json
    tfidf_matrix.npz / tfidf_vectorizer.pkl / tfidf_skill_ids.json（新）

  skill_content 侧（<MEMORY_ROOT>\\skill_content，运行时层）:
    {registry_domain}.json（24 域分桶，含 36 个 OC 插件 skill）
    skill_ids.json / bge_embeddings.npy / tfidf_matrix.npz / tfidf_vectorizer.pkl

  skill/registry/disk_manifest.json（来源清单，条数 = 注册表 skill 数，入库供 CI 全量 C1）

权威:
  - 成员/域名归属 = skill/registry/unified-skills-index.json（唯一权威）
  - 语料 = 磁盘 SKILL.md 前 800 字符（BGE 与 TF-IDF 同源，禁再分叉）
  - 旧生成器 build_bge_index.py / build_skill_embeddings.py 已退役

双域设计（R193 定案）:
  - 域 JSON 文件分桶 = 注册表 domain（24 桶，唯一权威）
  - BGE/TF-IDF 工件内 domain 字段 = 运行时 13 域口径（R192 基线，
    从 .prev 备份恢复 + classify_domain 兜底；路由 L0 过滤层依赖，不退役）

四道防线（lessons-p0 #7 固化）:
  ① 白名单（注册表成员/域名）  ② 写前校验（计数==注册表且非 0）
  ③ 原子替换（tmp + os.replace） ④ 写后守恒（重读比对集合/形状）

用法:
  python eval/build_indexes.py            # dry-run（不加载模型、不写盘）
  python eval/build_indexes.py --apply    # 全量重建 + 双写 + 守恒校验
  python eval/build_indexes.py --check    # 只做守恒校验（不重建）
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
REGISTRY_FILE = os.path.join(PROJECT_DIR, "skill", "registry", "unified-skills-index.json")
DISK_MANIFEST = os.path.join(PROJECT_DIR, "skill", "registry", "disk_manifest.json")

sys.path.insert(0, EVAL_DIR)
from config import GLOBAL_SKILLS, SKILL_CONTENT, PLUGIN_SKILLS_DIR, GLOBAL_MEMORY, SYSTEM_DIRS  # noqa: E402

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
CORPUS_CHARS = 800
DOMAIN_FILE_SKIPS = {"skill_ids.json", "index_manifest.json"}


from io_utils import load_json, write_json_atomic as _io_write_json_atomic  # P1-5: 读写原语唯一实现


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_model_path() -> str:
    """解析本地 HF 缓存中的 bge-small-zh-v1.5 快照（新旧两种 layout 兼容）。"""
    candidates = [
        os.path.expanduser(r"~/.cache/huggingface/models--BAAI--bge-small-zh-v1.5/snapshots"),
        os.path.expanduser(r"~/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5/snapshots"),
    ]
    for snap_root in candidates:
        if os.path.isdir(snap_root):
            snaps = sorted(os.listdir(snap_root))
            if snaps:
                return os.path.join(snap_root, snaps[-1])
    raise FileNotFoundError(
        "BGE 模型缓存缺失：请先运行 `huggingface-cli download BAAI/bge-small-zh-v1.5`"
    )


def find_skill_md(name):
    """按注册表成员名定位 SKILL.md，返回 (path, source)。"""
    for base, source in ((GLOBAL_SKILLS, "global_skills"), (PLUGIN_SKILLS_DIR, "openclaw_plugin")):
        md = os.path.join(base, name, "SKILL.md")
        if os.path.exists(md):
            return md, source
    return None, None


def parse_frontmatter(text):
    """SKILL.md frontmatter 轻量解析：标量 + 列表 + YAML 块标量（| >- 等）。

    R219(2026-09-08): 修复 description: | / >- 块标量被取成 "|" 字面量的缺陷
    （实测 elon-musk-perspective desc='|'、wps-knowledgebase desc='>-'
    → quick_verify "garbled/short descriptions" FAIL）。
    块标量语义：收集后续比当前键更深缩进的行，单空格拼接（desc 用于路由索引，换行无意义）。
    """
    meta = {}
    fm = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not fm:
        return meta
    lines = fm.group(1).splitlines()
    current_key = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        list_match = re.match(r"^\s*-\s*(.+)$", line)
        if list_match and current_key is not None:
            item = list_match.group(1).strip().strip('"').strip("'")
            if not isinstance(meta.get(current_key), list):
                meta[current_key] = []
            meta[current_key].append(item)
            i += 1
            continue
        kv = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if kv:
            current_key = kv.group(1)
            val = kv.group(2).strip()
            if val in ("|", "|-", "|+", ">", ">-", ">+"):
                base_indent = len(line) - len(line.lstrip())
                collected = []
                j = i + 1
                while j < n:
                    ln = lines[j]
                    if not ln.strip():
                        collected.append("")
                        j += 1
                        continue
                    ind = len(ln) - len(ln.lstrip())
                    if ind > base_indent:
                        collected.append(ln.strip())
                        j += 1
                    else:
                        break
                while collected and not collected[-1]:
                    collected.pop()
                meta[current_key] = " ".join(x for x in collected if x)
                i = j
                continue
            if not val:
                meta[current_key] = []
            else:
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                meta[current_key] = val
            i += 1
            continue
        i += 1
    return meta


def load_legacy_skill_content():
    """读取现有 skill_content 域 JSON，返回 name -> {triggers, desc} 兜底映射。"""
    legacy = {}
    if not os.path.isdir(SKILL_CONTENT):
        return legacy
    for fn in sorted(os.listdir(SKILL_CONTENT)):
        if not fn.endswith(".json") or fn in DOMAIN_FILE_SKIPS:
            continue
        try:
            data = load_json(os.path.join(SKILL_CONTENT, fn))
        except Exception:
            continue
        for s in data.get("skills", []):
            if isinstance(s, dict) and s.get("name"):
                legacy[s["name"]] = s
    return legacy


def load_runtime_domains():
    """恢复运行时 13 域口径（R194 迁移后：注册表 domain 已是权威 13 域）。

    注册表 domain 为主源；.prev 备份仅作过渡期兜底（迁移完成后可退役删除）。
    """
    mapping = {}
    reg = load_json(REGISTRY_FILE)
    for name, s in reg.get("skills", {}).items():
        if isinstance(s, dict) and s.get("domain"):
            mapping[name] = s["domain"]
    if os.path.isdir(SKILL_CONTENT):
        for fn in sorted(os.listdir(SKILL_CONTENT)):
            if not fn.endswith(".json.prev"):
                continue
            try:
                data = load_json(os.path.join(SKILL_CONTENT, fn))
            except Exception:
                continue
            file_domain = fn[: -len(".json.prev")]
            for s in data.get("skills", []):
                if isinstance(s, dict) and s.get("name") and s["name"] not in mapping:
                    mapping[s["name"]] = file_domain
    return mapping


def collect_skills():
    """从注册表 + 磁盘收集 skill 记录（条数 = 注册表 skill 数，不写盘）。"""
    reg = load_json(REGISTRY_FILE)
    reg_skills = reg.get("skills", {})
    if not reg_skills:
        raise RuntimeError("注册表 skills 为空，拒绝继续")
    try:
        from truth_constants import RETIRED_SKILLS
    except Exception:
        RETIRED_SKILLS = set()
    # R198.6 退役黑名单：派生件不收录退役 skill（防批量入库还原后残留索引）
    reg_skills = {k: v for k, v in reg_skills.items() if k not in RETIRED_SKILLS}
    if not reg_skills:
        raise RuntimeError("注册表 skills 全为退役项，拒绝继续")
    legacy = load_legacy_skill_content()
    runtime_domains = load_runtime_domains()
    from domain_classifier import classify_domain
    records = []
    missing = []
    for name in sorted(reg_skills):
        md, source = find_skill_md(name)
        if not md:
            missing.append(name)
            continue
        with open(md, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        size = os.path.getsize(md)
        fm = parse_frontmatter(text)
        body = text[:CORPUS_CHARS]
        # R275（2026-09-22）：**优先级反转** —— 现有域 JSON（legacy）优先于 SKILL.md frontmatter。
        # 理由：域 JSON 是 scan_skills.ps1 的产物，而它额外应用了 trigger_overrides.json
        # （人类策展覆盖，v3.2 FINAL authority），并把 desc 收敛为 120 字符展示格式；
        # 本函数只解析 frontmatter，每次 --apply 都会把策展结果覆盖回去 ⇒
        #   ① 双生成器内容不等价（实测 A-project-handoff 的 triggers 在两值间跳变，
        #      与缩进/时间戳差异共同构成 -2229 行噪音）；
        #   ② 更严重：**静默抹掉人类策展的 triggers**（数据劣化，不只是 diff 噪音）。
        # legacy 缺失时（新技能首轮）自然回退 frontmatter 解析，行为不变。
        _legacy = legacy.get(name, {}) or {}
        desc = _legacy.get("desc") or fm.get("description") or ""
        triggers = _legacy.get("triggers") or fm.get("triggers") or []
        if not isinstance(triggers, list):
            triggers = [triggers]
        # R275（2026-09-22）：legacy 兜底保留，但**优先级改为 frontmatter 顶层优先**。
        # R275 当初要治的是「version 写在 metadata 嵌套层、parse_frontmatter 只认顶层 key，
        # 读不到就回退注册表 'community' 把真版本降级」（实测 web-design-guidelines）；
        # 但把 legacy 摆在 fm 之前会带来另一个更隐蔽的缺陷：**version 一旦进入 legacy
        # 快照就永久冻结**（每次 --apply 都拿上一轮生成的值自我确认，frontmatter 再升也不动）。
        # 2026-09-26 实测：A-get-memory frontmatter 已 4.38.0、磁盘 74,681B，而
        # skill_content/memory.json 与 disk_manifest 双双仍是 4.35.0，且全仓无任何判据比对
        # skill_content.version 与 frontmatter（grep 零命中）⇒ 三版漂移静默存活。
        # 本行取值链的不变量：version 是**派生值**（不是人类策展值，与 triggers 不同），
        # 源头必须是当前 frontmatter；legacy 仅在 frontmatter 读不到时兜底 ⇒
        # R275 的嵌套层场景（fm.get 为空）行为不变，仍由 legacy 保住真版本。
        version = (fm.get("version") or _legacy.get("version")
                   or reg_skills[name].get("version") or "community")
        domain = reg_skills[name].get("domain") or "99-other"
        records.append({
            "name": name,
            "domain": domain,
            "routing_domain": runtime_domains.get(name) or classify_domain(f"{name} {body[:200]}"),
            "sub_domain": "",
            "version": version,
            "desc": str(desc)[:300],
            "triggers": [str(t) for t in triggers],
            "body": body if body else name,
            "size": size,
            "source": source,
            "path": md,
            "sha256": sha256_file(md),
        })
    if missing:
        raise RuntimeError(f"{len(missing)} 个注册表 skill 无 SKILL.md: {sorted(missing)[:10]}")
    if len(records) != len(reg_skills):
        raise RuntimeError(f"收集 {len(records)} != 注册表 {len(reg_skills)}")
    return records


def build_tfidf(texts):
    """TF-IDF 语料与 BGE 同源（SKILL.md 前 800 字符）。返回 (csr_matrix, vectorizer)。"""
    from scipy import sparse
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 4),
        max_features=5000,
        sublinear_tf=True,
        max_df=0.85,
        min_df=1,
    )
    matrix = vectorizer.fit_transform(texts)
    return sparse.csr_matrix(matrix), vectorizer


def encode_bge(bodies):
    """BGE 全量编码（N x 512）。

    优先 ONNX 后端（bge_onnx_engine）：零 torch / 零 tokenizers 依赖，
    与本机 torch 原生崩溃解耦，且与 bge_layer 实时服务路径共用同一语义空间
    （消除 torch/ONNX 漂移，保证检索一致性）。sentence_transformers/torch 作为兜底。
    """
    try:
        sys.path.insert(0, EVAL_DIR)
        from bge_onnx_engine import BgeOnnxEncoder
        enc = BgeOnnxEncoder()
        return enc.encode(bodies, show_progress_bar=False, batch_size=32)
    except Exception as e:
        print(f"[build_indexes] ONNX 编码失败，回退 sentence_transformers: {e}", file=sys.stderr)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(resolve_model_path(), device="cpu")
        return model.encode(bodies, show_progress_bar=False, batch_size=32)


# ===== 原子写入 =====
# 唯一写路径 = io_utils.write_json_atomic（json.dump ensure_ascii=False, indent=2 + tmp/改名原子替换）。
# R219 任务3（2026-09-08）原计划改走 GM `scripts/json_canonical.py` 单源契约模块，但该模块
# 从未入库（磁盘不存在 + GM 仓 git log 零记录），其 `if os.path.isfile` 条件分支恒不成立，
# 所有写入实际一直走下面的 io_utils 回退 —— 2026-09-26 删除这段死间接层，使代码与注释一致。
# 跨写方（scan_skills.ps1 / add-to-routing.ps1）的字节收敛由 GM
# `scripts/normalize_skill_content.py` 在收尾阶段统一承担（R275/R277，即 C18 的判据面）。


def write_json_atomic(path, obj):
    _io_write_json_atomic(path, obj)


def write_pkl_atomic(path, obj):
    tmp = Path(path).with_name(Path(path).name + '.tmp')
    tmp.write_bytes(pickle.dumps(obj))
    os.replace(tmp, path)


def write_npy_atomic(path, arr):
    tmp = path + ".tmp.npy"  # np.save 对非 .npy 后缀会自动追加，须以 .npy 结尾
    np.save(tmp, arr)
    os.replace(tmp, path)


def write_npz_atomic(path, matrix):
    from scipy import sparse

    tmp = path + ".tmp.npz"  # save_npz 对非 .npz 后缀会自动追加
    sparse.save_npz(tmp, matrix)
    os.replace(tmp, path)


def skill_entries_by_domain(records):
    """按注册表 domain 分桶（唯一权威），域内按 name 排序。"""
    buckets = {}
    for r in records:
        buckets.setdefault(r["domain"], []).append(r)
    return {d: sorted(entries, key=lambda x: x["name"]) for d, entries in buckets.items()}


def build_domain_payloads(records):
    """生成 24 个域 JSON 的 payload（dry-run 与 --apply 共用同一纯函数）。"""
    buckets = skill_entries_by_domain(records)
    payloads = {}
    for domain, entries in sorted(buckets.items()):
        payloads[domain] = {
            # R275（2026-09-22）：移除 generated 时间戳 ——
            # ① 该字段**无任何消费者**（全库实测：域 JSON 的 generated 只被写入、从不被读取）；
            # ② 它是唯一的非确定性来源：每次重建都变 ⇒ 内容未变也产生整文件 diff；
            # ③ 且与 scan_skills.ps1:456 的格式不一致（ISO 'T'+秒 vs 'yyyy-MM-dd HH:mm'），
            #    两生成器交替覆盖时该字段在两种格式间跳变，是 2026-09-22 实测 -2229 行
            #    格式噪音的直接成因之一。结构性字段（domain/count/skills）全部保留。
            "domain": domain,
            "count": len(entries),
            "skills": [
                {
                    "name": r["name"],
                    "triggers": r["triggers"],
                    "size": r["size"],
                    "version": r["version"],
                    "desc": r["desc"],
                }
                for r in entries
            ],
        }
    return payloads


def build_disk_manifest(records):
    return {
        "schema": "fenjue-disk-manifest-v1",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "count": len(records),
        "skills": [
            {
                "name": r["name"],
                "source": r["source"],
                "path": r["path"],
                "size": r["size"],
                "sha256": r["sha256"],
                "version": r["version"],
            }
            for r in records
        ],
    }


def _write_all(records, embeddings, matrix, vectorizer):
    """双写全部派生件；返回写入文件清单。"""
    written = []
    # 域 JSON 文件按注册表 domain 分桶；BGE/TF-IDF 的 domain 字段保持运行时 13 域口径
    # （路由 L0 分类器/域过滤/R192 基线盲测依赖，R193 不退役旧层）。
    skill_meta = [{"name": r["name"], "domain": r["routing_domain"], "sub_domain": ""} for r in records]
    skill_ids = [{"name": r["name"], "domain": r["routing_domain"]} for r in records]

    # ===== eval 侧 =====
    write_npy_atomic(os.path.join(EVAL_DIR, "bge_fullbody_embeddings.npy"), embeddings)
    written.append("eval/bge_fullbody_embeddings.npy")
    write_json_atomic(os.path.join(EVAL_DIR, "bge_fullbody_skills.json"), skill_meta)
    written.append("eval/bge_fullbody_skills.json")
    write_json_atomic(os.path.join(EVAL_DIR, "bge_fullbody_meta.json"), {
        "model": MODEL_NAME,
        "dim": int(embeddings.shape[1]),
        "count": int(embeddings.shape[0]),
        "encoding": f"full-body (SKILL.md first {CORPUS_CHARS} chars)",
        "source": "skill/registry/unified-skills-index.json",
        "snapshot": os.path.basename(resolve_model_path()),
        "tfidf": {"corpus": f"SKILL.md first {CORPUS_CHARS} chars (同源 BGE)"},
    })
    written.append("eval/bge_fullbody_meta.json")
    write_npz_atomic(os.path.join(EVAL_DIR, "tfidf_matrix.npz"), matrix)
    written.append("eval/tfidf_matrix.npz")
    write_pkl_atomic(os.path.join(EVAL_DIR, "tfidf_vectorizer.pkl"), vectorizer)
    written.append("eval/tfidf_vectorizer.pkl")
    write_json_atomic(os.path.join(EVAL_DIR, "tfidf_skill_ids.json"), skill_ids)
    written.append("eval/tfidf_skill_ids.json")

    # ===== skill_content 侧 =====
    os.makedirs(SKILL_CONTENT, exist_ok=True)
    write_npy_atomic(os.path.join(SKILL_CONTENT, "bge_embeddings.npy"), embeddings)
    written.append("skill_content/bge_embeddings.npy")
    write_json_atomic(os.path.join(SKILL_CONTENT, "skill_ids.json"), skill_ids)
    written.append("skill_content/skill_ids.json")
    write_npz_atomic(os.path.join(SKILL_CONTENT, "tfidf_matrix.npz"), matrix)
    written.append("skill_content/tfidf_matrix.npz")
    write_pkl_atomic(os.path.join(SKILL_CONTENT, "tfidf_vectorizer.pkl"), vectorizer)
    written.append("skill_content/tfidf_vectorizer.pkl")

    payloads = build_domain_payloads(records)
    known_domains = set(payloads)
    for domain, payload in payloads.items():
        write_json_atomic(os.path.join(SKILL_CONTENT, f"{domain}.json"), payload)
        written.append(f"skill_content/{domain}.json")
    # 删除不在新白名单的旧域 JSON（四道防线①白名单校验：只删非白名单的纯域文件）
    removed = []
    for fn in sorted(os.listdir(SKILL_CONTENT)):
        if not fn.endswith(".json") or fn in DOMAIN_FILE_SKIPS:
            continue
        if fn[:-5] not in known_domains:
            os.remove(os.path.join(SKILL_CONTENT, fn))
            removed.append(f"skill_content/{fn}")
    written.extend(removed)

    # ===== 仓库侧来源清单（入库） =====
    write_json_atomic(DISK_MANIFEST, build_disk_manifest(records))
    written.append("skill/registry/disk_manifest.json")
    return written


def conserve_check():
    """写后守恒：集合/形状/内容双端相等。返回问题列表（空 = 全绿）。"""
    try:
        return _conserve_check_impl()
    except Exception as e:
        return [f"守恒校验异常（fail-closed）: {e}"]


def _conserve_check_impl():
    issues = []
    reg = load_json(REGISTRY_FILE)
    reg_names = set(reg.get("skills", {}))

    # eval 侧
    if not os.path.exists(os.path.join(EVAL_DIR, "bge_fullbody_embeddings.npy")):
        return ["eval/bge_fullbody_embeddings.npy 缺失"]
    bge_arr = np.load(os.path.join(EVAL_DIR, "bge_fullbody_embeddings.npy"), mmap_mode='r')  # P1-4: 只读 mmap
    bge_skills = load_json(os.path.join(EVAL_DIR, "bge_fullbody_skills.json"))
    bge_names = {s["name"] for s in bge_skills}
    if bge_arr.shape[0] != len(bge_names) or bge_names != reg_names:
        issues.append(f"eval BGE 集合/形状不一致 ({bge_arr.shape}, {len(bge_names)} vs {len(reg_names)})")

    # skill_content 侧
    sc_ids = load_json(os.path.join(SKILL_CONTENT, "skill_ids.json"))
    sc_names = {s["name"] for s in sc_ids}
    if sc_names != reg_names:
        issues.append(f"skill_content skill_ids 集合不一致 ({len(sc_names)} vs {len(reg_names)})")
    sc_arr = np.load(os.path.join(SKILL_CONTENT, "bge_embeddings.npy"), mmap_mode='r')  # P1-4
    if sc_arr.shape != bge_arr.shape or not np.array_equal(sc_arr, bge_arr):
        issues.append(f"skill_content BGE 与 eval 不一致 ({sc_arr.shape} vs {bge_arr.shape})")

    total_sc = 0
    sc_files = 0
    sc_domain_names = set()
    for fn in sorted(os.listdir(SKILL_CONTENT)):
        if not fn.endswith(".json") or fn in DOMAIN_FILE_SKIPS:
            continue
        data = load_json(os.path.join(SKILL_CONTENT, fn))
        entries = data.get("skills", [])
        total_sc += len(entries)
        sc_files += 1
        if data.get("count") != len(entries):
            issues.append(f"{fn}: count 字段 {data.get('count')} != 实际 {len(entries)}")
        sc_domain_names.update(e["name"] for e in entries)
    if total_sc != len(reg_names):
        issues.append(f"skill_content 域 JSON 总数 {total_sc} != 注册表 {len(reg_names)}")
    if sc_domain_names != reg_names:
        issues.append("skill_content 域 JSON name 集合 != 注册表（存在重复/缺失）")
    reg_domains = {v.get("domain") or "99-other" for v in reg.get("skills", {}).values()}
    if sc_files != len(reg_domains):
        issues.append(f"域 JSON 文件数 {sc_files} != 注册表 domain 数 {len(reg_domains)}")

    # skill_routing.md 计数一致性（根治 213/175/144 三重漂移）
    try:
        sr = os.path.join(GLOBAL_MEMORY, "skill_routing.part1.part3.md")  # 领域表卷（R194 拆分后）
        if not os.path.exists(sr):
            sr = os.path.join(GLOBAL_MEMORY, "skill_routing.part1.md")  # 兼容旧布局
        if os.path.exists(sr):
            srt = _read_text(sr)
            mt = re.search(r"\*\*总计：(\d+)\s*个 skill\s*/\s*(\d+)\s*个领域\*\*", srt)
            if mt:
                if int(mt.group(1)) != len(reg_names) or int(mt.group(2)) != len(reg_domains):
                    issues.append(
                        f"skill_routing.part1.part3.md 总计行 {mt.group(1)}/{mt.group(2)} "
                        f"!= 注册表 {len(reg_names)}/{len(reg_domains)}（计数漂移，"
                        f"请跑 build_indexes.py --apply 自动注入）"
                    )
            else:
                issues.append("skill_routing.part1.part3.md 缺少 **总计：N 个 skill / M 个领域** 行")
    except Exception as e:
        issues.append(f"skill_routing 文档核对异常: {e}")

    # TF-IDF 双端
    from scipy import sparse

    tfidf_mats = {}
    for side, base in (("eval", EVAL_DIR), ("skill_content", SKILL_CONTENT)):
        m = sparse.load_npz(os.path.join(base, "tfidf_matrix.npz"))
        tfidf_mats[side] = m  # P1-4: 复用本侧矩阵，下方一致性比对不再二次 load_npz
        ids = load_json(os.path.join(base, "tfidf_skill_ids.json" if side == "eval" else "skill_ids.json"))
        if m.shape[0] != len(ids) or len(ids) != len(reg_names):
            issues.append(f"{side} tfidf 形状/索引不一致 ({m.shape}, {len(ids)})")
    if os.path.exists(os.path.join(EVAL_DIR, "tfidf_matrix.npz")):
        m1 = tfidf_mats["eval"]
        m2 = tfidf_mats["skill_content"]
        if m1.shape != m2.shape or not np.array_equal(m1.toarray(), m2.toarray()):
            issues.append("eval/skill_content TF-IDF 矩阵不一致")
        with open(os.path.join(EVAL_DIR, "tfidf_vectorizer.pkl"), "rb") as f1, \
                open(os.path.join(SKILL_CONTENT, "tfidf_vectorizer.pkl"), "rb") as f2:
            if f1.read() != f2.read():
                issues.append("eval/skill_content vectorizer 字节不一致")

    # 退役残留
    if os.path.exists(os.path.join(EVAL_DIR, "skill_ids.json")):
        issues.append("eval/skill_ids.json 退役残留")

    # manifest
    if not os.path.exists(DISK_MANIFEST):
        issues.append("skill/registry/disk_manifest.json 缺失")
    else:
        dm = load_json(DISK_MANIFEST)
        dm_names = {s["name"] for s in dm.get("skills", [])}
        if dm_names != reg_names or dm.get("count") != len(reg_names):
            issues.append("disk_manifest 与注册表不一致")
    return issues


def refresh_index_manifest():
    """重建 skill_content/index_manifest.json（pickle 完整性门禁依赖）。"""
    sys.path.insert(0, EVAL_DIR)
    import index_integrity

    return index_integrity._bootstrap(force=True)


def _read_text(path):
    from io_utils import read_text  # P1-5: 读写原语唯一实现（newline='' 保留 CRLF 原文）
    return read_text(path, newline='')


def _write_text_atomic_file(path, text):
    tmp = Path(path).with_name(Path(path).name + '.tmp')
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _parse_sr_triggers(path):
    """读取现有 skill_routing 领域表，归集 {domain: triggers_text}，保留人工精选文案。"""
    out = {}
    try:
        text = _read_text(path)
    except Exception:
        return out
    for line in text.splitlines():
        m = re.match(
            r"^\|\s*([\w-]+)\s*\|\s*`skill_content/([\w-]+)\.json`\s*\|\s*\d+\s*\|\s*(.*?)\s*\|\s*$",
            line,
        )
        if m:
            out[m.group(1)] = m.group(3)
    return out


def _derive_triggers(domain, by_domain):
    """从 records 派生触发词文案（仅当现有表缺该域时使用）。"""
    trigs = []
    for r in by_domain.get(domain, []):
        trigs.extend(r.get("triggers", []) or [])
    seen, uniq = set(), []
    for t in trigs:
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    if not uniq:
        return "（frontmatter 无触发词，按需查域 JSON）"
    if len(uniq) > 8:
        return ", ".join(uniq[:8]) + " …"
    return ", ".join(uniq)


def _build_sr_table(per_domain, existing_triggers, by_domain):
    header = "| 领域 | 文件 | 技能数 | 触发词(Triggers) |\n|------|------|:------:|-----------------|"
    rows = []
    for domain in sorted(per_domain):
        cnt = per_domain[domain]
        trig = existing_triggers.get(domain)
        if trig is None:
            trig = _derive_triggers(domain, by_domain)
        rows.append(f"| {domain} | `skill_content/{domain}.json` | {cnt} | {trig} |")
    return header + "\n" + "\n".join(rows)


def inject_skill_routing_counts(records):
    """根治 skill_routing.md 计数漂移：从注册表真源(records)自动重写领域表 + 总计行 + 头注。
    只修正计数与领域集合（保留人工精选触发词文案），fail-closed：异常仅告警不阻断主流程。
    返回问题/变更清单列表。
    """
    issues = []
    sr_part1 = os.path.join(GLOBAL_MEMORY, "skill_routing.part1.md")
    sr_part3 = os.path.join(GLOBAL_MEMORY, "skill_routing.part1.part3.md")  # 领域表卷（R194 拆分后实际位置）
    sr_md = os.path.join(GLOBAL_MEMORY, "skill_routing.md")
    targets = [p for p in (sr_part1, sr_part3, sr_md) if os.path.exists(p)]
    if not targets:
        return ["skill_routing 注入跳过：未找到 skill_routing.md / skill_routing.part1.md"]
    buckets = skill_entries_by_domain(records)
    per_domain = {d: len(v) for d, v in buckets.items()}
    by_domain = {}
    for r in records:
        by_domain.setdefault(r["domain"], []).append(r)
    existing_triggers = _parse_sr_triggers(sr_part3) if os.path.exists(sr_part3) else {}
    if not existing_triggers and os.path.exists(sr_part1):
        existing_triggers = _parse_sr_triggers(sr_part1)
    registry_count = len(records)
    domain_count = len(per_domain)
    n_global = sum(1 for r in records if r["source"] == "global_skills")
    n_plugin = sum(1 for r in records if r["source"] == "openclaw_plugin")
    new_table = _build_sr_table(per_domain, existing_triggers, by_domain)
    table_re = re.compile(
        r"(\| 领域 \| 文件 \| 技能数 \| 触发词\(Triggers\) \|\n\|[-| :]+\|\n)"
        r"(\|.*\|\n)+",
        re.S,
    )
    total_re = re.compile(r"\*\*总计：\d+\s*个 skill\s*/\s*\d+\s*个领域\*\*")
    for path in targets:
        try:
            text = _read_text(path)
            new_text = text
            # 1) 重写领域表（若存在），并把总计行紧跟表后
            new_text, n_table = table_re.subn(
                lambda m: m.group(1) + new_table + "\n"
                + f"**总计：{registry_count} 个 skill / {domain_count} 个领域**\n",
                new_text, count=1,
            )
            # 2) 若表不存在但已有独立总计行，则替换之
            new_text, n_total = total_re.subn(
                f"**总计：{registry_count} 个 skill / {domain_count} 个领域**", new_text, count=1
            )
            # 3) 若既无表也无总计行，追加到末尾（指针壳场景）
            if n_table == 0 and n_total == 0:
                new_text = new_text.rstrip() + f"\n\n**总计：{registry_count} 个 skill / {domain_count} 个领域**\n"
            new_text = re.sub(
                r"\b24 域\s*/\s*213 条\b", f"{domain_count} 域 / {registry_count} 条", new_text
            )
            new_text = re.sub(
                r"全局 177 \+ OC 插件 36", f"全局 {n_global} + OC 插件 {n_plugin}", new_text
            )
            if new_text != text:
                _write_text_atomic_file(path, new_text)
                issues.append(
                    f"已注入 {os.path.basename(path)} 计数（{registry_count}/{domain_count}，"
                    f"领域表={'已重写' if n_table else '无变化'}）"
                )
            else:
                issues.append(
                    f"{os.path.basename(path)} 无需变更（计数已一致 {registry_count}/{domain_count}）"
                )
        except Exception as e:
            issues.append(f"{os.path.basename(path)} 注入异常：{e}")
    return issues


def plan_summary(records):
    buckets = skill_entries_by_domain(records)
    return {
        "registry_count": len(records),
        "global_skills": sum(1 for r in records if r["source"] == "global_skills"),
        "openclaw_plugin": sum(1 for r in records if r["source"] == "openclaw_plugin"),
        "domains": {d: len(v) for d, v in sorted(buckets.items())},
        "bge": {"model": MODEL_NAME, "dim": 512, "corpus": f"SKILL.md first {CORPUS_CHARS} chars"},
        "tfidf": {"analyzer": "char_wb", "ngram": "2-4", "max_features": 5000,
                  "corpus": f"SKILL.md first {CORPUS_CHARS} chars（同源 BGE）"},
    }


def main() -> int:
    args = sys.argv[1:]
    if "--check" in args:
        issues = conserve_check()
        if issues:
            print("守恒校验 FAIL:", *issues, sep="\n  - ", file=sys.stderr)
            return 1
        print("守恒校验 PASS：双端集合/形状完全一致")
        return 0

    records = collect_skills()
    summary = plan_summary(records)
    if "--apply" not in args:
        print("dry-run：以下内容将重建（未写盘、未加载模型）")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("域 JSON:", ", ".join(f"{d}={n}" for d, n in summary["domains"].items()))
        print("加 --apply 执行全量重建 + 守恒校验")
        return 0

    print(f"收集 {len(records)} 条 skill（global_skills {summary['global_skills']} + plugin {summary['openclaw_plugin']}）")
    print(f"编码 BGE（{MODEL_NAME}，{len(records)} 条）...")
    bodies = [r["body"] for r in records]
    embeddings = encode_bge(bodies)
    print(f"  BGE shape: {embeddings.shape}")
    print("构建 TF-IDF（同源语料）...")
    matrix, vectorizer = build_tfidf(bodies)
    print(f"  TF-IDF shape: {matrix.shape}")
    written = _write_all(records, embeddings, matrix, vectorizer)
    print(f"写入 {len(written)} 个派生件:")
    for w in written:
        print("  +", w)
    refresh_index_manifest()
    print("+ skill_content/index_manifest.json")
    # 自动注入 skill_routing.md 计数（根治 213/175/144 三重漂移），与数据层同源
    for line in inject_skill_routing_counts(records):
        print(line)
    issues = conserve_check()
    if issues:
        print("守恒校验 FAIL:", *issues, sep="\n  - ", file=sys.stderr)
        return 1
    print("守恒校验 PASS：双端集合/形状完全一致（%d 条）" % len(records))
    # R216-02: 派生件基线快照自愈保持——重建成功即刷新 watcher manifest（失败仅告警，不阻断重建成果）
    try:
        from derivative_watch import snapshot
        m = snapshot()
        print("+ derivative_manifest.json（watcher 快照 %d 个产物）" % len(m["artifacts"]))
    except Exception as e:  # noqa: BLE001
        print("WARN: watcher 快照失败: %r" % e, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
