#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""index_integrity.py — 路由索引 pickle 完整性校验（R192 加固落地）

背景：5 处裸 pickle.load 加载 <MEMORY_ROOT>\\skill_content 下共享可写目录的
TF-IDF 工件，任一端写入恶意 pkl 即 RCE。加固 = 反序列化前对文件字节做
sha256 校验，与 manifest（index_manifest.json）比对；缺失/不匹配一律
fail-closed（IndexIntegrityError），禁止静默降级到裸 load。

用法：
  python eval/index_integrity.py --bootstrap             # dry-run：打印计划写入的 hash
  python eval/index_integrity.py --bootstrap --force     # 原子写入 manifest（tmp+rename+重读校验）
  python eval/index_integrity.py --check                 # 校验全部工件，FAIL 退出码 1

逃生门：R208 A5（P2-12）已改为显式 CLI `--no-integrity`（不再用环境变量一次性开关）；
无参时一律校验（fail-closed）。消费者脚本如需逃逸，显式调用
`set_integrity_override(True)`（可审计、可复查）。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pickle
import sys
from pathlib import Path

from config import SKILL_CONTENT as _SKILL_CONTENT


# R208 A5（P2-12）：逃生门从环境变量（FENJUE_SKIP_INDEX_CHECK）改为显式命令参数。
# import 消费者（unified_router/build_indexes 等）默认 fail-closed，无隐式逃逸通道。
_INTEGRITY_OVERRIDE = False


def set_integrity_override(flag: bool) -> None:
    """显式设置完整性校验覆盖（仅 CLI --no-integrity 或显式调用路径使用）。"""
    global _INTEGRITY_OVERRIDE
    _INTEGRITY_OVERRIDE = bool(flag)


SKIP_ENV = "FENJUE_SKIP_INDEX_CHECK"  # 保留常量名（历史引用/文档兼容），不再作为开关
MANIFEST_NAME = "index_manifest.json"
ARTIFACT_KEYS = (
    "tfidf_vectorizer.pkl",
    "tfidf_matrix.npz",
    "skill_ids.json",
)

# R194/R1: 反序列化白名单——只允许以下类/模块被 pickle 还原。
# 超出白名单 → 拒绝（fail-closed），防「hash 校验通过但内容为恶意 pkl」的 RCE 面。
# 白名单以 sklearn TfidfVectorizer 反序列化实际依赖为准（numpy/scipy/sklearn 数据类）。
ALLOWED_PICKLE_MODULES = {
    "numpy",
    "numpy.core.multiarray",
    "numpy._core.multiarray",
    "scipy.sparse",
    "scipy.sparse._csr",
    "scipy.sparse.csr",
    "scipy.sparse._data",
    "sklearn.feature_extraction.text",
    "sklearn.feature_extraction.text._vectorizers",
    "collections",
    "collections.abc",
    "builtins",
}
ALLOWED_PICKLE_CLASSES = {
    "collections.OrderedDict",
    "collections.Counter",
    "collections.defaultdict",
    "builtins.dict",
    "builtins.list",
    "builtins.tuple",
    "builtins.set",
    "builtins.str",
    "builtins.bytes",
    "builtins.int",
    "builtins.float",
    "builtins.bool",
    "builtins.NoneType",
    "numpy.ndarray",
    "numpy.dtype",
    "numpy.core.multiarray._reconstruct",
    "numpy._core.multiarray._reconstruct",
}


class RestrictedUnpickler(pickle.Unpickler):
    """白名单受限反序列化器：非白名单类直接拒绝（fail-closed）。"""

    def find_class(self, module, name):
        full = f"{module}.{name}"
        if module in ALLOWED_PICKLE_MODULES or full in ALLOWED_PICKLE_CLASSES:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(
            f"禁止反序列化非白名单类 {full}（RCE 加固，R194）"
        )


def restricted_loads(data: bytes):
    """白名单受限 pickle.loads；任何非白名单类 → 抛 UnpicklingError。"""
    return RestrictedUnpickler(io.BytesIO(data)).load()


def safe_load_pickle(path: str, label: str = "tfidf_vectorizer.pkl"):
    """完整安全加载链：skip 逃生门 → sha256 校验 → 白名单受限反序列化 → 结构校验。

    供 unified_router / build_indexes 等消费者替换裸 pickle.load 使用。
    返回 (obj, None)；失败抛 IndexIntegrityError / UnpicklingError（fail-closed）。
    """
    if skip_enabled():
        # R209: 逃生门只豁免 hash 校验，不豁免 RCE 白名单——
        # 裸 pickle.load 可被恶意 pkl 触发任意类反序列化（bandit B301 P0）。
        return restricted_loads(Path(path).read_bytes()), "完整性校验已禁用（--no-integrity 显式逃生门）"
    verify_pickle_hash(path, label)
    obj = restricted_loads(Path(path).read_bytes())
    return obj, None


_skip_warned = False


class IndexIntegrityError(RuntimeError):
    """路由索引不再匹配权威 manifest，拒绝继续使用。"""


def skill_content_dir() -> str:
    return _SKILL_CONTENT


def manifest_path() -> str:
    return os.path.join(skill_content_dir(), MANIFEST_NAME)


def skip_enabled() -> bool:
    global _skip_warned
    if _INTEGRITY_OVERRIDE:
        if not _skip_warned:
            print(
                "[index_integrity] WARNING: --no-integrity -- pickle 完整性校验已禁用，"
                "路由输出不可信。请尽快解除并运行 --check。",
                file=sys.stderr,
            )
            _skip_warned = True
        return True
    return False


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: str | None = None) -> dict:
    p = path or manifest_path()
    if not os.path.exists(p):
        raise IndexIntegrityError(
            f"index_manifest.json 不存在（{p}）。先运行 "
            "`python eval/index_integrity.py --bootstrap --force` 生成后再加载工件。"
        )
    data = json.loads(Path(p).read_text(encoding="utf-8"))
    if data.get("schema") != "fenjue-index-manifest-v1":
        raise IndexIntegrityError(f"manifest schema 未知：{data.get('schema')}")
    return data


def verify_pickle_hash(path: str, label: str = "tfidf_vectorizer.pkl") -> None:
    """pickle.load 前对文件字节校验；manifest 缺失/记录缺失/不匹配均抛错。"""
    if skip_enabled():
        return
    manifest = load_manifest()
    artifacts = manifest.get("artifacts", {})
    expected = artifacts.get(label)
    if expected is None:
        raise IndexIntegrityError(
            f"manifest 无 {label} 记录；工件可能是被替换的新文件。"
            "运行 `python eval/index_integrity.py --bootstrap --force` 重建 manifest 后重试。"
        )
    actual = file_sha256(path)
    if actual != expected:
        raise IndexIntegrityError(
            f"{label} 内容 hash 不匹配（expected {expected}, got {actual}）："
            "工件被篡改或污染，拒绝反序列化。"
        )


def verify_vectorizer_structure(vectorizer, matrix_columns: int, label: str) -> None:
    """反序列化后的结构校验：必须是已拟合的 TfidfVectorizer 且特征数一致。"""
    for attr in ("idf_", "vocabulary_"):
        if not hasattr(vectorizer, attr):
            raise IndexIntegrityError(
                f"{label}: 反序列化对象缺少 {attr!r}，不是已拟合的 "
                "TfidfVectorizer（可能被污染），拒绝使用。"
            )
    idf = getattr(vectorizer, "idf_", None)
    n = len(idf) if idf is not None else 0
    if n == 0:
        raise IndexIntegrityError(f"{label}: idf_ 为空，不是已拟合索引。")
    if n != matrix_columns:
        raise IndexIntegrityError(
            f"{label}: 特征数 {n} != matrix 列数 {matrix_columns}，索引漂移或工件替换。"
        )


def _bootstrap(force: bool) -> int:
    sc = skill_content_dir()
    missing = [k for k in ARTIFACT_KEYS if not os.path.exists(os.path.join(sc, k))]
    if missing:
        print(f"缺失工件：{missing}", file=sys.stderr)
        return 1
    hashes = {k: file_sha256(os.path.join(sc, k)) for k in ARTIFACT_KEYS}
    manifest = {
        "schema": "fenjue-index-manifest-v1",
        "created": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "artifacts": hashes,
    }
    if not force:
        print("dry-run：以下内容将写入", manifest_path())
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        print("确认后加 --force 执行（原子写 + 重读校验）。")
        return 0
    target = manifest_path()
    tmp = Path(target + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    # 写后守恒校验：重读比对
    reread = load_manifest(target)
    if reread.get("artifacts") != hashes:
        print("写后校验不一致，manifest 生成失败", file=sys.stderr)
        return 1
    print(f"manifest 已写入并校验通过：{target} ({len(hashes)} 工件)")
    return 0


def _check() -> int:
    sc = skill_content_dir()
    manifest = load_manifest()
    artifacts = manifest.get("artifacts", {})
    ok = True
    for key in ARTIFACT_KEYS:
        path = os.path.join(sc, key)
        if not os.path.exists(path):
            print(f"FAIL {key}: 文件缺失")
            ok = False
            continue
        expected = artifacts.get(key)
        if expected is None:
            print(f"FAIL {key}: manifest 无记录")
            ok = False
            continue
        actual = file_sha256(path)
        if actual != expected:
            print(f"FAIL {key}: hash 不匹配")
            ok = False
        else:
            print(f"PASS {key}: {actual[:16]}...")
    print("index integrity: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if "--no-integrity" in args:
        set_integrity_override(True)
        print("[index_integrity] --no-integrity：已显式跳过完整性校验（逃生门）",
              file=sys.stderr)
    if "--bootstrap" in args:
        return _bootstrap("--force" in args)
    if "--check" in args or not args:
        return _check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
