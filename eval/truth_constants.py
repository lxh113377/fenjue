"""truth_constants.py — 焚诀单一真相源薄 loader。

从 truth_constants.json 加载常量，供所有 Python 消费方 import。
禁止手抄常量，所有脚本/CI/壳文档须从此模块或 JSON 文件引用。

用法:
    from truth_constants import ENDPOINTS, ENDPOINT_COUNT, MAINLINES, ...
"""
import json
import os

_BASE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_BASE, "truth_constants.json"), encoding="utf-8") as _f:
    _C = json.load(_f)

# === 门禁编号唯一派生点（2026-09-24 GitHub 对标轮收口）===
# 根因：generate_index 与 aggregate_status 各自内联正则算 C 号，且后者硬编码「C1~C18」。
#       门禁从 C18 涨到 C29 期间三处文案各自漂移 —— 与 C5/C16 治的是同一病灶，只是发生在标签面。
def derive_max_gate_id(verify_src_path=None):
    """从 verify 的 checks 注册表解析最大门禁编号；解析不出返回 0（调用方须显式降级，禁当通过）。"""
    import re as _re
    path = verify_src_path or os.path.join(_BASE, "verify_truth_consistency.py")
    try:
        with open(path, encoding="utf-8") as f:
            nums = [int(x) for x in _re.findall(r"\('C(\d+)'", f.read())]
    except OSError:
        return 0
    return max(nums) if nums else 0


# === 端点 ===
ENDPOINTS = _C["endpoints"]["active"]            # 当前 7 端：wb/tr/cx/hm/zc/oc/qd（值随 JSON 派生，注释仅快照）
ENDPOINT_COUNT = len(ENDPOINTS)                   # 由 ENDPOINTS 派生，禁手抄端数
ENDPOINT_LABELS = _C["endpoints"]["labels"]       # {"wb":"WorkBuddy",...}
ENDPOINT_ALIASES = _C["endpoints"]["aliases"]     # {"tr":"tc"}
ENDPOINT_NOTES = _C["endpoints"]["notes"]         # {"cc":"CC记忆规则不同"}
ENDPOINTS_RETIRED = _C["endpoints"]["retired"]    # {"qw":"已下线","hm":"已卸载"}
ENDPOINTS_INCOMPATIBLE = _C["endpoints"]["incompatible"]  # {"mv":"...","td":"..."}

# === Junction 路径 ===
JUNCTION_PATHS_RAW = _C["junction_paths"]         # 原始映射 dict

# === 全局根常量（P1-6 收口锚点，2026-09-02）：全仓唯一定义点 ===
# config.py 由此 re-export（env 可覆盖）；新增代码禁止再手写这两个字面量，
# 路径字面量新增由 CI path-hygiene ratchet lint 拦截（eval/path_hygiene.py）。
GLOBAL_SKILLS_ROOT = r"<SKILLS_ROOT>"
GLOBAL_MEMORY_ROOT = r"<MEMORY_ROOT>"

# === 退役 skill 黑名单（R198.6，用户确认） ===
RETIRED_SKILLS = set(_C.get("retired_skills", []))  # 防批量入库还原（build_registry/build_indexes 排除）

# === 七步闭环工作流（R195） ===
WORKFLOW = _C["workflow"]
WORKFLOW_DOC_PATH = WORKFLOW["doc_path"]          # <MEMORY_ROOT>\prompts\workflow_seven_step.md
WORKFLOW_VERSION = WORKFLOW["version"]            # 1.0
WORKFLOW_STEPS = WORKFLOW["steps"]                # ①..⑦ 七步
WORKFLOW_PLATFORMS = WORKFLOW["platforms"]        # 四端
WORKFLOW_SCRIPTS = WORKFLOW["scripts"]            # {端: scripts\wf_*.ps1}
WORKFLOW_GATE_SCRIPT = WORKFLOW["gate_script"]    # eval\workflow_gate.py

def get_junction_skills_paths():
    """返回活跃端点的 skills junction 路径列表（跳过 null）。"""
    return [JUNCTION_PATHS_RAW[ep]["skills"]
            for ep in ENDPOINTS
            if JUNCTION_PATHS_RAW.get(ep, {}).get("skills")]

def get_junction_memory_paths():
    """返回活跃端点的 memory junction 路径列表（跳过 null）。"""
    return [JUNCTION_PATHS_RAW[ep]["memory"]
            for ep in ENDPOINTS
            if JUNCTION_PATHS_RAW.get(ep, {}).get("memory")]

def get_junction_pairs():
    """返回 (label, skills_path, memory_path) 元组列表，供 cross_layer_audit 使用。"""
    pairs = []
    for ep in ENDPOINTS:
        jp = JUNCTION_PATHS_RAW.get(ep, {})
        sk = jp.get("skills")
        mem = jp.get("memory")
        if sk:
            pairs.append((f"{ep}_skills", sk, GLOBAL_SKILLS_ROOT))
        if mem:
            pairs.append((f"{ep}_memory", mem, GLOBAL_MEMORY_ROOT))
    return pairs

# === 主线 ===
MAINLINES = _C["mainlines"]
MAINLINE_COUNT = len(MAINLINES)                    # 6
MAINLINES_SCORED = [m for m in MAINLINES if m["kind"] == "scored"]   # ①②③
MAINLINES_METRIC = [m for m in MAINLINES if m["kind"] == "metric"]   # ④⑤⑥

# === 碎片化 ===
FRAGMENT_MAX_BYTES = _C["fragment"]["max_bytes"]   # 4096
FRAGMENT_RULE = _C["fragment"]["rule"]

# === 评分卡 ===
# ⚠️ 命名口径（2026-09-24 对标轮收口）：不带 ACTIVE 的 SCORECARD_TOTAL/PASS_LINE/
#    LINE_PASS/LINE_TOTAL/DIM_PASS_RATE 恒为 **track_150 遗留口径**，仅供 scorecard.py
#    三线 50 分制评分器使用。任何**渲染层**（STATUS / index.md / 报告）必须改用下方
#    SCORECARD_ACTIVE_*，否则 active_track 切到 200 后会出现「182.5/200 配 120/150 达标线」
#    这类分母错配（实测根因：generate_index 渲染 track_150、aggregate_status 恒取 150）。
_track = _C["scorecard"]["track_150"]
SCORECARD_TRACK_150 = _track
SCORECARD_TOTAL = _track["total"]                  # 150（遗留口径，禁用于渲染）
SCORECARD_PASS_LINE = _track["pass_line"]          # 120（遗留口径，禁用于渲染）
SCORECARD_LINE_PASS = _track["line_pass"]          # 40
SCORECARD_LINE_TOTAL = _track["line_total"]        # 50
SCORECARD_DIM_PASS_RATE = _track["dim_pass_rate"]  # 0.80
SCORECARD_TRACK_200 = _C["scorecard"]["track_200"]
SCORECARD_PASS_PCT = _C["scorecard"]["pass_pct"]
SCORECARD_ACTIVE_TRACK = _C["scorecard"]["active_track"]

# 渲染层唯一口径：随 active_track 派生（缺字段回落 track_150，与 status_report R213 同法）
_ACTIVE_TRACK_DICT = (SCORECARD_TRACK_200 if SCORECARD_ACTIVE_TRACK == "track_200"
                      else _track)
SCORECARD_ACTIVE_TOTAL = _ACTIVE_TRACK_DICT.get("total", SCORECARD_TOTAL)
SCORECARD_ACTIVE_PASS_LINE = _ACTIVE_TRACK_DICT.get("pass_line", SCORECARD_PASS_LINE)
SCORECARD_ACTIVE_PASS_PCT = _ACTIVE_TRACK_DICT.get("pass_pct", SCORECARD_PASS_PCT)

# === 行为规则核心（2026-09-22：status_report 原硬编码 V30/44锚点 → 真相源派生） ===
BEHAVIOR_CORE = _C["behavior_core"]
BEHAVIOR_CORE_VERSION = BEHAVIOR_CORE["version"]    # "V41"
BEHAVIOR_CORE_ANCHORS = BEHAVIOR_CORE["anchors"]    # 22
BEHAVIOR_CORE_VALID = BEHAVIOR_CORE["valid"]        # 22
BEHAVIOR_CORE_SOURCE = BEHAVIOR_CORE["source"]      # <MEMORY_ROOT>\core\behavior_core.md

# === 主线⑤ 注意力税权重（R217 用户拍板: Top-10 加权纳入，双轨披露） ===
LINE5_WEIGHTS = _C["line5_weights"]  # {"dilution":0.5,"hit_top1":0.25,"hit_top10":0.25}

# === L1 注入硬预算棘轮（C25，P1E-2，2026-09-24） ===
INJECT_BUDGET = _C["inject_budget"]
INJECT_BUDGET_BASELINE = INJECT_BUDGET["baseline_bytes"]  # 棘轮基线（只许下调）
INJECT_BUDGET_HARD_CAP = INJECT_BUDGET["hard_cap_bytes"]  # 绝对上限（防基线失控放宽）
INJECT_BUDGET_FILES = INJECT_BUDGET["files"]              # [{id,path,bytes}] P0 强制注入区

# === 路径 ===
# R207 N2 单源收口（2026-09-02）: 由 :31-32 GLOBAL_*_ROOT 派生，消除同文件双定义点。
# 原实现从 truth_constants.json "paths" 段读取，与 ROOT 常量构成两个真相源——
# 一旦漂移，import config（ROOT 版）与旧引用（json 版）拿到不同值。
# 注: json 的 "paths" 段现为冗余镜像（无 py 消费者），待 json 大版本清理时移除。
GLOBAL_MEMORY = GLOBAL_MEMORY_ROOT
GLOBAL_SKILLS = GLOBAL_SKILLS_ROOT

# === 便捷：路由消费平台（走 skill_content 路由的端点） ===
# 2026-09-23 OC（OpenCode）纳入（用户裁定）：与 WB/TC/CX 同走 skill_content 路由；
# 事前核验 151 skills 无仅 oc 独占项，纳入后维度检查行为无变化
# 排除 cx（CX 不走 junction skills，直读 global_skills）
ROUTER_PLATFORMS = tuple(ep for ep in ENDPOINTS if ep not in ("cx",))

# === 废弃端点全集（retired + incompatible；2026-09-23 起减去当前在役端：
# 代号 oc 虽在 retired 留痕（OpenClaw 2026-09-21 退役史实保留），但已被 OpenCode 接管复用，
# 在役优先，死端判定不得含在役端） ===
DEAD_PLATFORMS = (set(ENDPOINTS_RETIRED.keys()) | set(ENDPOINTS_INCOMPATIBLE.keys())) - set(ENDPOINTS)
