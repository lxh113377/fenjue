#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_truth_consistency.py — 焚诀单一真相源 CI 门禁
=====================================================================
校验维度数**以 main() 内 checks 注册表为准**（当前 C1~C29；2026-09-24 对标轮把
文档里的「24 维 / C1~C28」硬计数删掉 —— 计数写死即必然漂移，同 C29 治的病灶）。
确保 truth_constants.json 常量源与所有派生物一致。
失败时退出码 1，成功退出码 0。

R276/R277 变更（2026-09-22）:
  - 新增 C17：实体排除清单跨消费方一致（`consistency_consumers.check_entities`）
  - 新增 C18：多写入方产物契约一致（`cross_writer_idempotence.check_static`，静态层）
    两者均**同目录 import 复用**、**每次 verify 必跑**、**无 SKIP 逃生门**
    （门禁脚本缺失即 FAIL，防"删掉门禁即绕过"）。
    动态层（`cross_writer_idempotence --run`，交替真实执行生成器）不在本门禁内，
    由每日自动化独立步骤执行。

R193 变更:
  - C1 增加 disk_manifest 模式：CI（--skip-external）用入库 manifest 全量跑，不再 SKIP
  - C2 用入库 BGE 三件套全量跑，不再 SKIP
  - 新增 C10：注册表 == BGE == skill_content 三方集合相等 + eval/skill_ids.json
    零残留 + npy/tfidf 形状校验（本地跑，CI 保持 SKIP）
  - 新增 C11（R195）：workflow 共享规范存在、版本与 truth_constants 一致、
    在役端 wf_*.ps1 脚本路径合法（本地跑，CI 保持 SKIP）
  - 新增 C12（R196）：workflow 规范任务卡字段 == workflow_gate.TASK_CARD_HEADERS
    （防模板漂移，本地跑，CI 保持 SKIP）
  - 新增 C13（R198.6）：skill frontmatter version == 版本历史首行版本号
    （防版本信息漂移，本地跑，CI 保持 SKIP；2026-08-16 D1-D3 修正后固化）
  - 新增 C14（R213）：关键决策产物时效（STATUS/评分卡/盲测产物 mtime ≤ 7 天）
    防「旧快照当现状」——2026-09-06 实测 STATUS 停更 20 天，期间评分卡口径
    由 track_150 切到 track_200，绿(149.5/150 达标)实为红(150.1/200 未达标)。

接入点:
  - pre-commit hook
  - 周维护 Step 0
  - CI (.github/workflows/ci.yml)

用法:
  python eval/verify_truth_consistency.py           # 全量校验
  python eval/verify_truth_consistency.py --json     # JSON 输出
  python eval/verify_truth_consistency.py --skip-external  # 跳过仓库外检查(CI用)
"""
import json
import glob
import os
import re
import subprocess
import sys
import time

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
REGISTRY = os.path.join(PROJECT_DIR, 'skill', 'registry')


def external_root_reachable(path):
    r"""D-48（对标轮七）：判「外盘真相根（GM / GS 两个盘符根）在本机是否真的可达」。

    为什么 `os.path.isdir` 不够：POSIX 的反斜杠是**合法文件名字符**，所以「盘符 + 反斜杠 + 目录名」
    这一串在 Linux 上是一条**相对路径**；CI 工作树里被
    `os.makedirs(os.path.join(GLOBAL_MEMORY, "skill_content"))` 造出的同名幽灵目录会让 `isdir`
    返回真 —— 于是「这台机器根本没有 GM 盘」被逐级闸口冒充成「GM 内容坏了 / 路由表不存在 /
    44 条期望死链」。判据必须再加一层「在本平台语义下是绝对路径」，否则「降级面」与「判据面」混谈。
    本机（Windows）行为逐字节不变：那串字面量在 Windows 上本就是绝对路径。
    """
    return bool(path) and os.path.isabs(path) and os.path.isdir(path)


def path_outside_project(path):
    """D-48（对标轮七）：判一条注入清单路径是否指向**仓外**（含 Windows 字面量在 POSIX 上的形态）。

    原 C25 口径只把「前两字符等于 D 盘符」的条目算外盘，CI（POSIX）上用户目录（C 盘）下的
    注入清单条目（如 qd 端 `shell_zc`）既不匹配该前缀、也不是 POSIX 绝对路径，于是被 `join` 到仓根
    后当成仓内文件报「清单内文件缺失」，绕过了注入盘降级。正确口径 = 盘符/UNC 字面量 **或** 解析后落在仓外。
    """
    if re.match(r'^[A-Za-z]:[\\/]', path or '') or (path or '').startswith(r'\\'):
        return True
    resolved = path if os.path.isabs(path) else os.path.join(PROJECT_DIR, path)
    return not os.path.abspath(resolved).startswith(os.path.abspath(PROJECT_DIR) + os.sep)

# C14: 关键决策产物时效看护清单（相对 PROJECT_DIR；缺失或超期均 FAIL）
C14_FRESHNESS_DAYS = 7
C14_WATCH = ('STATUS.md', 'STATUS.part1.md',
             'reports/recheck_scorecard.json', 'ci-blind-eval.json',
             'index.md')  # 2026-09-24 对标轮补入：index.md 曾长期不在看护面（过期 6 处自相矛盾）

# C15: G8「先根因后动手·数据流假设」锚定面（R215）
# 锚定面 v1 = 焚诀 workspace 当日日志 .workbuddy/memory/YYYY-MM-DD.md：
# 日志记录了代码修改痕迹（7+ 位 commit hash 或 rule_editor 字样）但全文无
# 「数据流假设」锚点词 -> FAIL；当日日志不存在 -> SKIP；无代码修改标记 -> PASS。
C15_ANCHOR = '数据流假设'
C15_CODE_MARK_RE = re.compile(r'\b[0-9a-f]{7,40}\b|rule_editor')

# import truth_constants
sys.path.insert(0, EVAL_DIR)
from config import GLOBAL_SKILLS, GLOBAL_MEMORY, SKILL_CONTENT, PLUGIN_SKILLS_DIR  # noqa: E402,F401  # L-1重导出面（晚绑定读者在册），删即红，见test_reexport_surface_guard
from truth_constants import (  # noqa: E402,F401  # L-1重导出面（同上）
    ENDPOINTS, DEAD_PLATFORMS, ENDPOINT_COUNT, MAINLINE_COUNT,
    WORKFLOW_DOC_PATH, WORKFLOW_VERSION, WORKFLOW_PLATFORMS,
    WORKFLOW_SCRIPTS, WORKFLOW_GATE_SCRIPT,
    BEHAVIOR_CORE_VERSION, BEHAVIOR_CORE_ANCHORS, BEHAVIOR_CORE_VALID,
    INJECT_BUDGET_FILES, INJECT_BUDGET_BASELINE, INJECT_BUDGET_HARD_CAP,
    SCORECARD_ACTIVE_TRACK, SCORECARD_ACTIVE_TOTAL, SCORECARD_ACTIVE_PASS_LINE,
    derive_max_gate_id,
)

# P0-1 收口（2026-09-23）：端数/主线数中文标签由真相源派生，禁手抄四端/六端
# （根因：C5/C11 曾硬编码「应为四端」，OC 入役端数 4→6 后把正确的六端误判为废弃字面量）
_CN_NUMS = {3: '三', 4: '四', 5: '五', 6: '六', 7: '七', 8: '八'}
EP_CN_LABEL = _CN_NUMS.get(ENDPOINT_COUNT, str(ENDPOINT_COUNT)) + '端'
ML_CN_LABEL = _CN_NUMS.get(MAINLINE_COUNT, str(MAINLINE_COUNT)) + '大主线'

# C16: 关键产物「内容」一致性（R213 补强，2026-09-22）
# 根因（实测）：STATUS 家族 mtime 新鲜（≤1 天）但**内容过期** —— 仍写 156 skills
# （注册表已 120）、behavior_core V30/44锚点（真值 V41/22）。C14 只验 mtime，
# 故「mtime 新鲜 + 内容过期」可长期假通过（R220 假通过族新形态）。
# C16 把产物里渲染的关键数字与真相源当场比对，堵住该盲区。
C16_WATCH = ('STATUS.md', 'STATUS.part1.md')
# C16 扩展面（2026-09-22，建议 #9）：记忆文档的「当前口径」段也要与真相源对齐。
# R241 共存设计：只扫**带锚点的当前口径行**，历史沿革/已完成条目段一律豁免
# （否则「口径沿革 135→160→156→120→151」这类历史留痕会被误判为过期）。
C16_CURRENT_WATCH = ('memory/01-goal.md', 'memory/07-next-steps.md')
C16_CURRENT_ANCHOR = '当前口径'
C16_CUR_SKILL_RE = re.compile(r'(\d+)\s*skill\b')
C16_CUR_TOTAL_RE = re.compile(r'([\d.]+)\s*/\s*200')
# 域数（2026-09-22 补漏）：C16 原只比 skill 数/端数/behavior_core/总分，域数从这漏出去 ——
# 「13 域 vs 14 域」正是因此长期潜伏（本轮实测：过期快照写 14，三源当场皆 13）。
C16_DOMAIN_RE = re.compile(r'(\d+)\s*域(?!表|数)')
C16_SKILLS_RE = re.compile(r'(\d+)\s*skills')
C16_SKILLROUTING_RE = re.compile(r'(\d+)\s*skill\s*/')
C16_BC_RE = re.compile(r'\|\s*behavior_core\s*\|\s*V(\d+)（(\d+)锚点/(\d+)有效）\s*\|')
C16_ENDPOINT_RE = re.compile(r'(\d+)端同步')
C16_TOTAL_RE = re.compile(r'机器实测综合:\s*([\d.]+)/')
C16_LINE_RE = re.compile(r'=\s*([\d.]+)/33')
C16_ARITH_TOL = 0.15

# C29（2026-09-24 对标轮）：根 index.md 与派生评分产物对账。
# 判据面正则（index.md 由 eval/generate_index.py 渲染，格式变动须同步这里 + 生成器）。
C29_INDEX_REL = 'index.md'
C29_SCORECARD_REL = 'reports/recheck_scorecard.json'
C29_EP_ROW_RE = re.compile(r'\|\s*端点数\s*\|\s*(\d+)')
C29_EP_HEAD_RE = re.compile(r'(\d+)端\(')
C29_EP_CN_HEAD_RE = re.compile(r'([一二三四五六七八九十])端\(')
C29_REGISTRY_RE = re.compile(r'注册表（(\d+)\s*条')
C29_GATE_RE = re.compile(r'C1~C(\d+)')
C29_TRACK_RE = re.compile(r'\|\s*评分卡\s*\|\s*(track_\d+)\s+TOTAL=(\d+)\s+PASS=(\d+)')
C29_TOTAL_RE = re.compile(r'机器实测综合\)?\s*\|\s*([\d.]+)/')
# 评分产物 vs STATUS 总分的容差。**按实测漂移定，不是拍脑袋**（R236 补注③）：
#   2026-09-24 实测同一轮内 scorecard JSON=182.5 / STATUS=182.3，差 0.2 ——
#   根因是主线⑥（技能使用率）由 route_trace.jsonl 驱动，跑一次路由就变一次分，
#   天生非确定；其余五线在同一提交内确定。故取 0.5（≈2× 实测漂移）为界：
#   既拦得住实测过的 7.4 分真脱节（175.1 vs 182.5），又不把"轨迹在动"误判成说谎。
#   若要收紧，前提是先把主线⑥改成读快照而不是读活 trace。
C29_SCORE_TOL = 0.5


from io_utils import load_json  # P1-5: 读写原语唯一实现（原本地 def 收敛）


_UNI_CACHE = None  # (path, (mtime, size), data)


def load_registry_uni():
    """P1-2: unified-skills-index.json 单次加载缓存（路径+mtime+size 键控）。

    根因：C1/C2/C10/C13/C16 各自重复 json.load 同一注册表（实测 5 次/轮）。
    失效键含路径与 (mtime, size)：文件被改/测试 fixture 切换 REGISTRY 时自动
    重载，杜绝进程内脏读（2026-09-23 全量 pytest 实测：无失效键时缓存被
    tmp 注册表 fixture 污染 → C16 假红，本键控修复即为此而设）。"""
    global _UNI_CACHE
    path = os.path.join(REGISTRY, 'unified-skills-index.json')
    try:
        st = os.stat(path)
        key = (st.st_mtime, st.st_size)
    except OSError:
        key = None
    if _UNI_CACHE is not None and _UNI_CACHE[0] == path and _UNI_CACHE[1] == key:
        return _UNI_CACHE[2]
    data = load_json(path)
    _UNI_CACHE = (path, key, data)
    return data














def _parse_frontmatter_version(text: str):
    """从 SKILL.md frontmatter 提取 version 字段（支持 10.6.2 / 1.3.0 / V3.9.4 格式）。"""
    m = re.search(r'(?m)^version:\s*V?(\d+(?:\.\d+){0,3})\s*$', text)
    return m.group(1) if m else None


def _parse_version_history_first(text: str):
    """提取版本历史区（## 版本历史 或 ### 版本历史）的最大版本号。
    兼容两种格式：'| V1.3.0 | 2026-08-16 | ...'（表格）与 '> V10.7.0 (2026-08-16,...)'（引用块）。
    取最大值而非首行：部分 skill 历史按时间升序（旧→新），首行不是最新版本。
    """
    m = re.search(r'(?m)^#{2,3}\s*版本历史\s*$', text)
    if not m:
        return None
    section = text[m.end():]
    candidates = []
    # 表格行: | V1.3.0 | ... 或 | 1.4.1 | ...
    m2 = re.findall(r'(?m)^\|\s*V?(\d+(?:\.\d+){0,3})\s*\|', section)
    candidates.extend(m2)
    # 引用块/列表行: > V10.7.0 (2026-08-16 ...) 或 - V10.7.0 (...
    m3 = re.findall(r'(?m)^(?:>\s*|-\s*|\*+\s*)?V?(\d+(?:\.\d+){0,3})\b', section)
    candidates.extend(m3)
    if not candidates:
        return None
    return max(candidates, key=lambda v: tuple(int(x) for x in v.split('.')))


def _versions_equivalent(a: str, b: str) -> bool:
    """版本号等价比较：去尾部 .0 归一（1.3.0 == 1.3；10.6.2 != 10.7）。"""
    def norm(v: str):
        parts = v.split('.')
        while len(parts) > 1 and parts[-1] == '0':
            parts.pop()
        return tuple(int(x) for x in parts)
    return norm(a) == norm(b)






















# ============================================================
# C17 / C18（2026-09-22，R276 / R277）：两道新门禁接入唯一真相源
# ============================================================
# 【接入方式】同目录 **import 复用**，不 subprocess、不重复实现 ——
#     eval/consistency_consumers.py    · check_entities() → (failures, notes)
#     eval/cross_writer_idempotence.py · check_static()  → (failures, notes)
#   （两个脚本都带 `if __name__ == '__main__'` 守卫，import 不会触发其 main/argparse）
# 【触发条件】**每次 verify 都执行**，纯静态、零副作用、毫秒级 ⇒ 不设 SKIP 逃生门。
#   ⚠️ 门禁脚本缺失/导入失败判 **FAIL 而非 SKIP** —— SKIP 等于给了"删掉门禁即绕过"的后路。
# 【不接入的部分】cross_writer_idempotence 的**动态层**（`--run`：交替真实执行生成器、
#   写盘、数分钟）不适合放进每次 verify，改由每日自动化的独立步骤执行。
# 【自动生效】verify 已被 pre-commit hook / 周维护 Step 0 / CI / 每日 03:00 同步任务调用
#   ⇒ 本项一旦注册即全链路强制生效，无需人工记忆。
def _ensure_eval_path():
    if EVAL_DIR not in sys.path:
        sys.path.insert(0, EVAL_DIR)










def _cgw_run(cgw, failures=None):
    """跑 check_gate_wiring 的检查主体（避开 argparse 的 sys.argv 依赖）。

    面按 cgw.detect_face() 自动判定后走 cgw.run_checks 单实现
    （2026-09-29 L-2 收口：此前本函数是第二份手抄实现，与 cgw.main() 双源，
    改一处漏一处；现两处调用方同走 run_checks）。
    failures：可选的对外报告列表（wrapper 用它把失效原因带出去；不传则内部自用）。
    """
    failures = [] if failures is None else failures
    face = cgw.detect_face()
    fails, _notes, _skips = cgw.run_checks(face)
    failures.extend(fails)
    return 1 if fails else 0




# C22（2026-09-23，P2-3 worktree 试点产出）：junction / 符号链接排除守护。
# 根因（实测）：%TEMP%\fj_worktree_pilot 17 项试点证明 —— junction 会被 git 当作
# 普通目录，其指向的**外部内容会被纳入版本控制**（git status 出现 A jdir/secret.txt，
# git ls-files 含 jdir/secret.txt）。焚诀靠 .gitignore L2-4（/memory /memory_content
# /prompts，注释「符号链接（指向 <MEMORY_ROOT>，不重复跟踪）」）挡住，但该防线
# 此前**无任何机器校验**：规则被删 / 新增 junction 忘登记 / 将来引入 worktree 都会
# 静默把全局记忆与技能库拉进版本控制。
# 三段判据：
#   W1 .gitignore 的「符号链接」声明段存在且 >=1 条规则（防「删规则让判据面变空」）
#   W2 每个实际链接经 git check-ignore 必须命中（git 权威判定；无法验证不得当通过）
#   W3 每个实际链接在声明段有显式规则（防「靠别处规则偶然挡住」）
# 注：链接数为 0 时返回 SKIP（该环境确无风险面），与 R247「判据面被清空不得静默 PASS」
# 区别在于 —— W1 守的声明段随仓库入库，clone 后仍在，判据面不会因环境而失效。
C22_SECTION_ANCHOR = '符号链接'
C22_MAX_DEPTH = 2
C22_SKIP_DIRS = ('.git',)


def _c22_is_junction(path):
    fn = getattr(os.path, 'isjunction', None)
    return bool(fn(path)) if fn else False


def _c22_scan_links(root, max_depth=C22_MAX_DEPTH):
    """扫描 root 下的 junction / symlink；**遇链接不深入**（其指向外部巨树）。"""
    found = []

    def walk(cur, rel, depth):
        if depth > max_depth:
            return
        try:
            entries = sorted(os.scandir(cur), key=lambda e: e.name)
        except OSError:
            return
        for ent in entries:
            if ent.name in C22_SKIP_DIRS or ent.name.startswith('.'):
                continue
            name = ent.name if not rel else rel + '/' + ent.name
            is_j = _c22_is_junction(ent.path)
            if is_j or ent.is_symlink():
                found.append((name, 'junction' if is_j else 'symlink'))
                continue
            if ent.is_dir():
                walk(ent.path, name, depth + 1)

    walk(root, '', 1)
    return found


def _c22_parse_section(ignore_text):
    """解析 .gitignore 中锚点含「符号链接」的声明段，返回其规则列表（去注释与空行）。"""
    rules = []
    in_sec = False
    for raw in (ignore_text or '').splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith('#'):
            if C22_SECTION_ANCHOR in s:
                in_sec = True
            elif in_sec:
                in_sec = False
            continue
        if in_sec:
            rules.append(s)
    return rules


def _c22_git_ignored(repo, names):
    """逐条判定（参数形式）：返回 {name: True/False/None}，None = 无法验证。

    **刻意不用 `check-ignore --stdin`**：2026-09-23 本机实测（诊断脚本 _temp/diag_c22.py）
    发现该模式对 LF 分隔输入判定异常 —— 同仓同规则下逐条 `-v` 三条全命中，
    而 `--stdin` 喂三行只认最后一行、带尾换行则 rc=1 全判否、单独喂任一条也 rc=1。
    若沿用会造成**假 FAIL**（C22 首跑即误报 memory/memory_content 未忽略）。
    参数形式与手动实测一致，故采用；代价为 N 次子进程（N=链接数，通常 <5）。
    """
    out = {}
    for name in names:
        try:
            proc = subprocess.run(['git', '-C', repo, 'check-ignore', '-q', name],
                                  capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', timeout=30)
        except Exception:
            out[name] = None
            continue
        if proc.returncode == 0:
            out[name] = True
        elif proc.returncode == 1:
            out[name] = False
        else:
            out[name] = None
    return out




# C23（2026-09-23 P2-6）：技能文档「产物落点」声明合规 —— 落点必须真实存在且被 noise 认可。
# 根因（本日实测）：A-skill-manager 铁律 #3 声明备份落点 `_bak`（记忆根下），而该目录经 junction
# 在焚诀侧呈「嵌套 _bak」被 noise 二级扫描判 VIOL（清空后目录本身仍报），pre-commit 连拒 6 次；
# 且 2026-09-21 已把代码落点改为 `_trash`，四处文档漏改 → 「声明落点」与「实际可行落点」
# 长期脱节而**无任何机器校验**（典型「改一处漏四处」）。
# 三段：
#   W1 声明面棘轮：落点声明数 >= 基线（防清空判据面，与 R247 同族）
#   W2 真实存在：绝对路径落点的落点根必须存在于磁盘（模板占位符只取静态前缀）
#   W3 noise 认可：落点根不得命中 noise VIOL 面（C23_BANNED_ROOTS），且须在认可集内
# 豁免：历史文件（version-history* / merge-record*）与历史标记行 —— 记载既往事实不算现行声明。
C23_BASELINE_DECLS = 18
# 禁作落点（用户 2026-09-23 裁定：_bak 经 junction 会被 noise 二级扫描判 VIOL，清空后目录本身仍报）
C23_BANNED_ROOTS = ('_bak',)
# noise 认可的回收/临时区（QUARANTINE_DIRS 口径）
C23_OK_ROOTS = ('_trash', '_temp', '_fenjue_backups', '.cleanup', '_archive', '_my-skills')
# 工具约定备份目录（noise 实扫未见报；避免白名单枚举误伤合法落点）
C23_TOOL_OK = ('.rule_backup',)
# noise VIOL 模式（与 scripts/noise_lint.py 同族）：只取高置信段，
# 刻意不含 _tmp/tmp*/_new*/_final —— 那些模式过宽，会把业务目录名误判为落点违规。
C23_VIOL_RE = re.compile(r'(_old|_copy|_backup|_deprecated|_bak|\.bak)')
C23_CTX_RE = re.compile(r'(落点|备份到|归档到|软删|移出到|移至|cp\s*→|mv\s*→|备份\s*[：:]|归档\s*[：:])')
C23_TOKEN_RE = re.compile(r'`([^`\n]{2,100}[\\/])`')
C23_HIST_FILE = ('version-history', 'version_history', 'merge-record')
C23_HIST_MARK = ('原为', '原文备份', '当时', '已废除', '迁移前', '融合时')
C23_MANAGED_PREFIX = ('global_memory', 'global_skills', 'workspace', 'Users', '<USER_UID>', 'Desktop')
_SEP = chr(92)


def _c23_root_of(token):
    """从落点 token 提取「相对受管根的落点根名」。"""
    t = token.strip().strip('`').replace('/', _SEP)
    if _SEP not in t:
        return None
    t = re.sub(r'^[A-Za-z]:', '', t)
    segs = [s for s in t.split(_SEP) if s and s not in ('.', '..')]
    while segs and segs[0] in C23_MANAGED_PREFIX:
        segs.pop(0)
    if not segs:
        return None
    first = segs[0]
    return first if (first.startswith('_') or first.startswith('.') or first.islower()) else None


def _c23_exists(token):
    """绝对路径落点的位置有效性。返回 (True/False/None, 说明)，None = 相对路径不校验。

    两版修正留痕（均实测）：
      ① 首版取「最近存在的静态祖先」→ 会一路退到盘根 `D:/` 而**恒判存在**（假通过）；
      ② 二版精确定位落点根并只校验该层 → 误伤「按需创建」的落点
         （`...\\skill-memory\\removed_skills_backup\\` 只在删技能时才建，文档声明合理却被判 FAIL）。
    终版口径：取最近存在的静态祖先，**但退到盘根即判无效**——
    既拦住完全无效路径，又允许按需创建的落点（其父目录存在即视为挂载位置有效）。
    """
    raw = token.strip().strip('`').replace('/', _SEP)
    t = re.split(r'<[^>]*>', raw)[0].rstrip(_SEP)
    if not re.match(r'^[A-Za-z]:', t):
        return (None, '相对路径')
    cur = t
    while cur:
        if os.path.exists(cur):
            if re.match(r'^[A-Za-z]:' + re.escape(_SEP) + r'?$', cur):
                return (False, '仅退到盘根 ' + cur)
            return (True, cur)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return (False, '(无有效祖先)')


def _c23_scan(skills_root=None):
    """扫描技能文档（.md）中的落点声明：[(rel, line_no, root, token, line)]。"""
    root = skills_root or GLOBAL_SKILLS
    out = []
    for dp, dn, fn in os.walk(root):
        if any(s in dp for s in ('_trash', '_bak', '__pycache__', '.git')):
            dn[:] = []
            continue
        for f in fn:
            if not f.endswith('.md'):
                continue
            p = os.path.join(dp, f)
            try:
                with open(p, encoding='utf-8', errors='replace') as _f:
                    lines = _f.read().splitlines()
            except OSError:
                continue
            rel = os.path.relpath(p, root)
            for no, ln in enumerate(lines, 1):
                if not C23_CTX_RE.search(ln):
                    continue
                for m in C23_TOKEN_RE.finditer(ln):
                    r = _c23_root_of(m.group(1))
                    if r:
                        out.append((rel, no, r, m.group(1), ln))
    return out


def _c23_is_history(rel, line):
    base = os.path.basename(rel)
    return any(h in base for h in C23_HIST_FILE) or any(h in line for h in C23_HIST_MARK)




# C24（2026-09-23 P2-8/6）：direct 内置 fallback 与 direct_map.json 双写一致 ——
# save_direct_map.py --force 不同步即漂移（P1-8 实证：fallback 加 1 条而 json 仍旧时
# direct_route 走旧表）。W1 条数一致 + W2 pattern 集合一致；任一面为空即 FAIL（R247）。


def main():
    skip_external = '--skip-external' in sys.argv
    as_json = '--json' in sys.argv

    # P1 批（2026-09-23）：检查函数一律**调用期按名解析**（globals()）——
    # 根因：直接函数引用使 test_exit_code_all_pass_sets_0 的 monkeypatch 失效，
    # 退出码契约测试被迫跑真检查（受运行环境扰动假红）。生产语义不变。
    checks = [
        ('C1', '注册表 skill 集 == 磁盘 SKILL.md 集', lambda: _check_fn('check_c1_registry_vs_disk')(skip_external)),
        ('C2', 'BGE 索引 skill 集 == 注册表', lambda: _check_fn('check_c2_bge_vs_registry')(skip_external)),
        ('C3', 'platform_tiers 活跃端 == ENDPOINTS', lambda: _check_fn('check_c3_platform_tiers')()),
        ('C4', 'registry 完整性（cx/hm 存在 / mv,td 清除）', lambda: _check_fn('check_c4_registry_completeness')()),
        ('C5', '壳文档无废弃口径字面量', lambda: _check_fn('check_c5_shell_docs_no_stale_literals')()),
        ('C6', '双源 cross_platform_map.json 一致', lambda: _check_fn('check_c6_cross_platform_map_consistency')(skip_external)),
        ('C7', '生成器无裸常量（scorecard/aggregate_status/status_report）', lambda: _check_fn('check_c7_no_bare_constants')()),
        ('C8', '活 workspace 无 _bak_* 目录', lambda: _check_fn('check_c8_no_bak_in_workspace')()),
        ('C9', '活目录无 Temp/ 与重复/备份残留', lambda: _check_fn('check_c9_no_stale_artifacts')()),
        ('C10', '注册表==BGE==skill_content 三方集合+形状', lambda: _check_fn('check_c10_three_way_data_layer')(skip_external)),
        ('C11', 'workflow 规范/版本/' + EP_CN_LABEL + '脚本一致性（R195）', lambda: _check_fn('check_c11_workflow_consistency')(skip_external)),
        ('C12', 'workflow 任务卡字段 == gate TASK_CARD_HEADERS（R196）', lambda: _check_fn('check_c12_task_card_fields')(skip_external)),
        ('C13', 'skill frontmatter 版本 == 版本历史首行（R198.6）', lambda: _check_fn('check_c13_skill_version_consistency')(skip_external)),
        ('C14', '关键决策产物时效 ≤%d 天（R213）' % C14_FRESHNESS_DAYS, lambda: _check_fn('check_c14_artifact_freshness')(skip_external=skip_external)),
        ('C15', '当日日志 G8 数据流假设锚点（R215）', lambda: _check_fn('check_c15_dataflow_assumption')()),
        ('C16', '关键产物内容 == 真相源（补 C14 只验 mtime 盲区）', lambda: _check_fn('check_c16_artifact_content_consistency')(skip_external=skip_external)),
        # C17/C18（2026-09-22）：两道新门禁接入 —— 纯静态、每次必跑
        # D-48（轮七）：二者判据面全在 GM `scripts/` 下，此前**没有** SKIP 分支 ⇒ CI 恒红 7 道之二
        ('C17', '实体排除清单跨消费方一致（R276）', lambda: _check_fn('check_c17_consumer_consistency')(skip_external)),
        ('C18', '多写入方产物契约一致（R277，静态层）', lambda: _check_fn('check_c18_cross_writer_contract')(skip_external)),
        # C19（2026-09-22 R278）：门禁接入点自检 —— 防「声明 N 条、实际 M<N 条」的链路断裂
        ('C19', '门禁接入点真实落地（R278，静态）', lambda: _check_fn('check_c19_gate_wiring')(skip_external)),
        # C20（2026-09-23 P0-1）：技能可移植性棘轮 —— 防新增技能硬编码绝对路径（对标 Superpowers）
        ('C20', '技能可移植性棘轮（绝对路径不许升）', lambda: _check_fn('check_c20_skill_portability')(skip_external)),
        # C21（2026-09-23 用户立规）：提交授权纪律防回滚 —— 活文档不得重现"提交需授权/确认"表述
        ('C21', '提交授权纪律防回滚（自动提交）', lambda: _check_fn('check_c21_no_commit_authorization_rule')()),
        # C22（2026-09-23 P2-3 后续）：junction/符号链接排除守护 —— 防 junction 内容被纳入版本控制
        ('C22', 'junction/链接排除守护（git check-ignore）', lambda: _check_fn('check_c22_junction_exclude')()),
        # C23（2026-09-23 P2-6）：技能文档落点声明合规 —— 真实存在 + noise 认可（防「改一处漏四处」）
        ('C23', '技能文档落点声明（存在性+noise 认可）', lambda: _check_fn('check_c23_skill_doc_landing')(skip_external)),
        # C24（2026-09-23 P2-8/6）：direct 双写一致 —— fallback 改了必须 --force 同步 json（防旧表短路）
        ('C24', 'direct fallback与direct_map.json双写一致', lambda: _check_fn('check_c24_direct_map_consistency')()),
        # C25（2026-09-24 P1E-2）：L1 注入硬预算棘轮 —— P0 强制注入区字节和只许降不许升（对标 OpenClaw/Anthropic 硬预算）
        ('C25', 'L1注入硬预算棘轮（P1E-2）', lambda: _check_fn('check_c25_inject_budget')(skip_external)),
        # C26（2026-09-24 P1E-1）：记忆召回评测集静态健康 —— 结构/死链/基线（跑分归周维护）
        ('C26', '记忆召回评测集健康（P1E-1）', lambda: _check_fn('check_c26_memory_recall_testset')(skip_external)),
        # C27（2026-09-24 P2E-1）：技能内容安全 —— 注入/外传零容忍，dangerous 告警（用户立规全仓无豁免表）
        ('C27', '技能内容安全扫描（P2E-1）', lambda: _check_fn('check_c27_skill_content_security')(skip_external)),
        # C28（2026-09-24 P2E-2）：技能发布合规 —— frontmatter 必填/desc≤1024/字段白名单
        ('C28', '技能发布合规校验（P2E-2）', lambda: _check_fn('check_c28_skill_publish_compliance')(skip_external)),
        # C29（2026-09-24 GitHub 对标轮 P0-14）：index.md + 派生评分产物对账
        #   根因：index.md 不在 C14/C16 看护面（实测 6 处自相矛盾长期存活）；
        #   recheck_scorecard.json 只验 mtime ⇒ 内容可与 STATUS 差 7.4 分仍放行（R268 同族）。
        ('C29', 'index.md 与派生评分产物对账（P0-14）', lambda: _check_fn('check_c29_index_reconciliation')()),
        # C30（2026-09-24 GitHub 对标轮 P1-17）：路由静态表目标存活 + 覆盖空洞棘轮
        #   根因：CONTEXT_SKILL_MAP 7 个目标指向已退役技能 ⇒ 对应意图静默退化为裸 BGE 召回。
        ('C30', '路由静态表目标存活与空洞棘轮（P1-17）', lambda: _check_fn('check_c30_routing_target_liveness')()),
        # C31（2026-09-24 对标轮四 7-E）：注入预算归因台账 —— 治 D-22（并发顶破基线不可归因）
        #   与 D-28（增长源在 global_skills 仓、该仓无 pre-commit ⇒ 提交当时零校验）。
        #   注意：显式关键字传参（R271 实证教训：C30 曾因位置参落到别的名参而恒 PASS）。
        ('C31', 'L1注入预算归因台账（7-E）',
         lambda: _check_fn('check_c31_inject_ledger')(skip_external=skip_external)),
        # C32（2026-09-24 对标轮四 7-C/6-B）：空基线「已初始化」台账 —— 三处 {} / [] /
        #   active_version=0 长期以"空"过关，"扫过且干净"与"根本没扫"在文件里无法区分（R3 D-10）。
        ('C32', '空基线已初始化台账（7-C）',
         lambda: _check_fn('check_c32_empty_baseline_ledger')(skip_external=skip_external)),
        # C33（2026-09-24 对标轮四 7-D/6-C）：GM 记忆路由表健康 —— 八端契约都靠它按需加载，
        #   而 R3 D-11 实测它自 09-21 起是 9 行「待重建」壳（加载链断了 3 天）。现表为生成物。
        ('C33', 'GM记忆路由表健康（7-D）',
         lambda: _check_fn('check_c33_memory_index_routing')(skip_external=skip_external)),
    ]

    results = []
    has_fail = False
    for cid, desc, fn in checks:
        try:
            status, detail = fn()
        except Exception as e:
            status, detail = ('FAIL', f'检查异常: {e}')
        if status == 'FAIL':
            has_fail = True
        results.append({'id': cid, 'desc': desc, 'status': status, 'detail': detail})

    if as_json:
        print(json.dumps({
            'schema': 'fenjue-truth-consistency-v1',
            'ts': __import__('datetime').datetime.now().isoformat(),
            'all_pass': not has_fail,
            'results': results,
        }, ensure_ascii=False, indent=2))
    else:
        for r in results:
            icon = {'PASS': '✅', 'FAIL': '❌', 'SKIP': '⏭️'}[r['status']]
            print(f"{icon} {r['id']}: {r['desc']} — {r['detail']}")
        print('=' * 50)
        n_pass = sum(1 for r in results if r['status'] == 'PASS')
        n_fail = sum(1 for r in results if r['status'] == 'FAIL')
        n_skip = sum(1 for r in results if r['status'] == 'SKIP')
        print(f"真相源校验: {n_pass} PASS / {n_fail} FAIL / {n_skip} SKIP"
              + (' ✅' if not has_fail else ' ❌ 有 FAIL'))
        if has_fail:
            # P1-7: FAIL 必带修复入口（报错即可操作，不让用户对着编号猜）
            print('修复指引: ①派生件缺失/不一致 → python eval/build_indexes.py --apply 后复跑'
                  ' ②壳文档口径 → 查上方 FAIL 行 file:line，改现状断言（历史行加豁免标记）'
                  ' ③注册表漂移 → python eval/build_registry.py --dry-run 先看差异')

    sys.exit(1 if has_fail else 0)




# ── P1-16 拆包（2026-09-23）：检查函数迁 verify_checks/，经 __getattr__ 惰性暴露 ──
_CHECK_HOME = {'check_c1_registry_vs_disk': 'registry_layer', 'check_c3_platform_tiers': 'registry_layer', 'check_c4_registry_completeness': 'registry_layer', 'check_c6_cross_platform_map_consistency': 'registry_layer', 'check_c30_routing_target_liveness': 'registry_layer', 'check_c2_bge_vs_registry': 'data_layer', 'check_c10_three_way_data_layer': 'data_layer', 'check_c5_shell_docs_no_stale_literals': 'doc_layer', 'check_c7_no_bare_constants': 'doc_layer', 'check_c8_no_bak_in_workspace': 'workspace_layer', 'check_c9_no_stale_artifacts': 'workspace_layer', 'check_c22_junction_exclude': 'workspace_layer', 'check_c11_workflow_consistency': 'workflow_layer', 'check_c12_task_card_fields': 'workflow_layer', 'check_c13_skill_version_consistency': 'skill_layer', 'check_c20_skill_portability': 'skill_layer', 'check_c23_skill_doc_landing': 'skill_layer', 'check_c14_artifact_freshness': 'status_layer', 'check_c15_dataflow_assumption': 'status_layer', 'check_c16_artifact_content_consistency': 'status_layer', 'check_c21_no_commit_authorization_rule': 'status_layer', 'check_c29_index_reconciliation': 'status_layer', 'check_c17_consumer_consistency': 'governance_layer', 'check_c18_cross_writer_contract': 'governance_layer', 'check_c19_gate_wiring': 'governance_layer', 'check_c24_direct_map_consistency': 'governance_layer', 'check_c25_inject_budget': 'governance_layer', 'check_c31_inject_ledger': 'governance_layer', 'check_c32_empty_baseline_ledger': 'governance_layer', 'check_c33_memory_index_routing': 'governance_layer', 'check_c26_memory_recall_testset': 'governance_layer', 'check_c27_skill_content_security': 'governance_layer', 'check_c28_skill_publish_compliance': 'governance_layer'}


def _check_fn(name):
    """检查函数晚绑定：模块命名空间优先（monkeypatch 面板），未命中从 verify_checks 惰性加载。"""
    if name in globals():
        return globals()[name]
    return getattr(sys.modules[__name__], name)


def __getattr__(name):
    home = _CHECK_HOME.get(name)
    if home is None:
        raise AttributeError(name)
    import importlib
    mod = importlib.import_module('verify_checks.' + home)
    fn = getattr(mod, name)
    globals()[name] = fn  # 惰性缓存（globals() 优先级不变）
    return fn




if __name__ == '__main__':
    main()
