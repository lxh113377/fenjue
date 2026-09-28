#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GM 记忆路由表生成器测试（对标轮四 7-D / C33）。

要防的是"重建壳复活"：各在役端启动契约都写「按 meta/memory_index.md 精准加载」，表一旦退回
占位状态，按需加载链就静默断掉（实测断了 3 天无人察觉，因为没有任何判据看它）。
所以测试的主体不是"能生成"，而是**每一类退化都必须变红**：占位残留、死链、空文件、
漏目录、幽灵目录、体积超标；以及覆盖判据不能是空转（删一行必须翻转）。
"""

import os
import sys

import pytest

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EVAL_DIR)
import build_memory_index as bmi  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.isdir(bmi.ROOT), reason="GM 根不可达（异机最小环境）")


def test_scan_covers_every_top_level_dir():
    rows = bmi.scan()
    dirs = {r["dir"] for r in rows}
    on_disk = {n for n in os.listdir(bmi.ROOT)
               if os.path.isdir(os.path.join(bmi.ROOT, n)) and n not in (".git", ".agents")}
    assert dirs == on_disk, "scan 漏目录或多目录"
    assert ".cleanup" in dirs, "隐藏目录被跳过 = 覆盖判据有洞（实测曾因此漏 .cleanup）"


def test_every_dir_is_classified():
    """每个一级目录必须二选一归类；漏一个就该被 C33 W4 拦住。"""
    dirs = {r["dir"] for r in bmi.scan()}
    unclassified = dirs - set(bmi.KNOWLEDGE) - set(bmi.EXCLUDED)
    assert not unclassified, "未归类目录（新增目录须先归类再生成）: %s" % sorted(unclassified)


def test_generated_table_passes_its_own_gate():
    st, detail = bmi.check_text(bmi.render(bmi.scan(), "2026-09-24"))
    assert st == "PASS", detail


def test_placeholder_only_matches_real_form():
    """判据说明文字里提到该词不得自触（本仓当日第三次踩「注释触发断言」坑）。"""
    text = bmi.render(bmi.scan(), "2026-09-24")
    assert "待重建" not in text, "生成表正文不应含该词"
    st, detail = bmi.check_text(text + "\n> 路由规则（待重建）\n")
    assert st == "FAIL" and "W1" in detail


def test_dead_link_is_red(tmp_path):
    text = bmi.render(bmi.scan(), "2026-09-24") + "\n先读 `meta/__no_such__.md`\n"
    st, detail = bmi.check_text(text)
    assert st == "FAIL" and "W3" in detail


def test_missing_dir_row_is_red():
    """删掉一个真实目录的行 → 覆盖判据必须红（否则 W4 是空转断言）。"""
    target = next(r["dir"] for r in bmi.scan() if r["dir"] in bmi.KNOWLEDGE)
    prefix = "| `%s/` |" % target
    text = bmi.render(bmi.scan(), "2026-09-24")
    kept = [l for l in text.splitlines(True) if not l.startswith(prefix)]
    assert len(kept) < len(text.splitlines(True)), "表行格式假设变了，本测试需同步"
    st, detail = bmi.check_text("".join(kept))
    assert st == "FAIL" and "W4" in detail


def test_declared_entry_paths_exist_and_nonempty():
    """表内声明的每个 .md 路径必须实测存在且非空（R240：文档写了≠磁盘有）。"""
    text = bmi.load_text(bmi.OUT) if os.path.exists(bmi.OUT) else bmi.render(bmi.scan(), "x")
    decls = bmi.declared_paths(text)
    assert decls, "表里一个入口路径都没声明 = 路由表没有可直达项"
    for d in decls:
        p = os.path.join(bmi.ROOT, d)
        assert os.path.exists(p), "声明路径死链: %s" % d
        assert os.path.getsize(p) > 0, "声明路径是空文件: %s" % d


def test_size_within_r161_cap():
    text = bmi.render(bmi.scan(), "2026-09-24")
    assert len(text.encode("utf-8")) <= bmi.MAX_BYTES, "路由表超 4KB 硬顶（R161）"


def test_c33_registered_and_stubbed():
    src = open(os.path.join(EVAL_DIR, "verify_truth_consistency.py"), encoding="utf-8").read()
    assert "check_c33_memory_index_routing" in src, "C33 未注册进 verify"
    assert "'check_c33_memory_index_routing': 'governance_layer'" in src, "C33 未登记 _CHECK_HOME"
    stub = open(os.path.join(EVAL_DIR, "stubs", "registry.json"), encoding="utf-8").read()
    assert "C33" in stub, "新判据未补隔离桩（R272 交付契约）"
