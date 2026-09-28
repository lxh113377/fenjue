# -*- coding: utf-8 -*-
"""verify_checks.registry_layer — 检查函数族（P1-16 拆包，2026-09-23）。

状态/助手经 `_root.<name>` 晚绑定（ctx 单例 = verify_truth_consistency），
monkeypatch(vtc, <state>/<check>) 契约不变。
"""
import glob
import json
import os
import re
import subprocess
import sys

import verify_truth_consistency as _root  # noqa: E402  # ctx 单例


def check_c1_registry_vs_disk(skip_external=False):
    """C1: 注册表 skill 集 == 磁盘 SKILL.md 集。

    CI（--skip-external 或 global_skills 不可达）走 disk_manifest.json 全量模式；
    本地磁盘可达时做磁盘扫描 + manifest 双交叉校验。
    """
    try:
        uni = _root.load_registry_uni()  # P1-2: 单次加载缓存（原 5 处重复 json.load）
        reg_keys = set(uni.get('skills', {}))
    except Exception as e:
        return ('FAIL', f'unified-skills-index.json 读取失败: {e}')
    dm_path = os.path.join(_root.REGISTRY, 'disk_manifest.json')
    manifest_names = None
    if os.path.exists(dm_path):
        try:
            dm = _root.load_json(dm_path)
            manifest_names = {s['name'] for s in dm.get('skills', [])}
            if dm.get('count') != len(manifest_names):
                return ('FAIL', f'disk_manifest count={dm.get("count")} != 实际 {len(manifest_names)}')
        except Exception as e:
            return ('FAIL', f'disk_manifest.json 读取失败: {e}')
    if skip_external or not os.path.isdir(_root.GLOBAL_SKILLS):
        if manifest_names is None:
            return ('FAIL', 'disk_manifest.json 缺失（CI 全量 C1 依赖）')
        if manifest_names != reg_keys:
            missing = sorted(reg_keys - manifest_names)[:5]
            extra = sorted(manifest_names - reg_keys)[:5]
            return ('FAIL', f'manifest={len(manifest_names)} 注册表={len(reg_keys)}'
                    f' | manifest漏收(注册表有但manifest无):{missing}'
                    f' | manifest多出(注册表无,即磁盘未入库):{extra}')
        return ('PASS', f'注册表 == disk_manifest ({len(reg_keys)} skills, CI 全量)')
    # 本地磁盘扫描（global_skills + OC 插件目录）
    from config import SYSTEM_DIRS as system_dirs  # 单一真相源（原硬拷贝收口）
    disk = set()
    for d in os.listdir(_root.GLOBAL_SKILLS):
        full = os.path.join(_root.GLOBAL_SKILLS, d)
        if (os.path.isdir(full) and d not in system_dirs
                and os.path.exists(os.path.join(full, 'SKILL.md'))):
            disk.add(d)
    # OC 插件目录作为合法 SKILL.md 来源（R168 决策：OC 插件专属 skill 不在 global_skills）
    plugin_root = _root.PLUGIN_SKILLS_DIR
    if os.path.isdir(plugin_root):
        for d in os.listdir(plugin_root):
            full = os.path.join(plugin_root, d)
            if os.path.isdir(full) and os.path.exists(os.path.join(full, 'SKILL.md')):
                disk.add(d)
    missing_in_disk = reg_keys - disk
    if manifest_names is not None:
        # 真问题才判 FAIL：manifest 含磁盘无（孤儿） / 注册表含但 manifest 未收录
        # 磁盘多出非注册表技能（OC 插件、global_skills 其他技能）属正常，不判 FAIL
        orphan_in_manifest = manifest_names - disk
        reg_not_in_manifest = reg_keys - manifest_names
        if orphan_in_manifest or reg_not_in_manifest:
            return ('FAIL', f'disk_manifest 与磁盘/注册表不一致'
                    f' | manifest多出(磁盘无孤儿):{sorted(orphan_in_manifest)[:5]}'
                    f' | manifest漏收(注册表有但manifest无):{sorted(reg_not_in_manifest)[:5]}')
    if missing_in_disk:
        # 仅注册表技能在磁盘缺失才判 FAIL；磁盘多出非注册表技能属正常
        detail = f'注册表={len(reg_keys)} 磁盘={len(disk)}'
        detail += f' | 磁盘缺(注册表有但磁盘无): {sorted(missing_in_disk)[:5]}'
        return ('FAIL', detail)
    return ('PASS', f'注册表 == 磁盘 ({len(reg_keys)} skills)')


def check_c3_platform_tiers():
    """C3: platform_tiers 在役端**键集** == truth_constants.ENDPOINTS（含 standby，不比 tier 取值）。

    2026-09-24 对标轮措辞收口：原判据名/文档称「活跃端」，但实现把 primary/standby/active
    一并算入 —— tr=standby 因此在册即过。语义本身是有意为之（端清单对账要比全集），
    但名字不许说破没比的东西；若要校 tier 取值本身，须另立项（属人决策：standby 是否算在役）。
    """
    try:
        tiers = _root.load_json(os.path.join(_root.REGISTRY, 'platform_tiers.json'))
    except Exception as e:
        return ('FAIL', f'platform_tiers.json 读取失败: {e}')
    # 支持 dict 格式: {"tiers": {"wb":"active",...}}
    tiers_dict = tiers.get('tiers', tiers) if isinstance(tiers, dict) else {}
    tier_active = {k for k, v in tiers_dict.items()
                   if v in ('primary', 'standby', 'active') and k not in ('retired', 'incompatible')}
    expected = set(_root.ENDPOINTS)
    missing = expected - tier_active
    extra = tier_active - expected
    if missing or extra:
        return ('FAIL', f'tiers={sorted(tier_active)} expected={sorted(expected)}'
                f' missing={sorted(missing)} extra={sorted(extra)}')
    return ('PASS', f'platform_tiers 活跃端 == _root.ENDPOINTS ({sorted(expected)})')


def check_c4_registry_completeness():
    """C4: registry 缺活跃端 platform-*.json / 残留废弃端。"""
    # 端点 ID → 注册表文件名映射（tr 在注册表中为 tc，cx 在注册表中为 codex）
    _ep_to_file = {'wb': 'wb', 'tr': 'tc', 'cx': 'codex', 'cc': 'cc', 'oc': 'oc', 'hm': 'hm'}
    issues = []
    # 活跃端须有 platform-{regkey}.json
    for ep in _root.ENDPOINTS:
        regkey = _ep_to_file.get(ep, ep)
        p = os.path.join(_root.REGISTRY, f'platform-{regkey}.json')
        if not os.path.exists(p):
            issues.append(f'缺 platform-{regkey}.json (endpoint={ep})')
    # 废弃端不应有 platform-*.json
    for dead in _root.DEAD_PLATFORMS:
        p = os.path.join(_root.REGISTRY, f'platform-{dead}.json')
        if os.path.exists(p):
            issues.append(f'残留 platform-{dead}.json（应删除）')
    if issues:
        return ('FAIL', '; '.join(issues))
    return ('PASS', f'注册表完整: {_root.ENDPOINTS} 无残留')

def check_c6_cross_platform_map_consistency(skip_external=False):
    """C6: 仓库 cross_platform_map.json 与 global_memory 版双源一致。

    双文件架构（R170）：
    - 仓库版 = 安装状态注册表（role: install_state，含 skills 字段）
    - GM 版 = 路由名映射（role: routing_name_mapping，含 platform_routing）
    GM 版通过 install_state_ref 字段引用仓库版；C6 校验引用指向正确且版本号一致。
    """
    repo_path = os.path.join(_root.REGISTRY, 'cross_platform_map.json')
    gm_path = os.path.join(_root.GLOBAL_MEMORY, 'cross_platform_map.json')
    if skip_external or not os.path.exists(gm_path):
        return ('SKIP', 'global_memory 版不可达（CI 环境）')
    if not os.path.exists(repo_path):
        return ('FAIL', '仓库 cross_platform_map.json 不存在')
    try:
        repo_data = _root.load_json(repo_path)
        gm_data = _root.load_json(gm_path)
        repo_ver = repo_data.get('version', '?')
        gm_ver = gm_data.get('version', '?')
        gm_ref = gm_data.get('install_state_ref', '')
        # 校验 GM 版的 install_state_ref 指向仓库版
        if gm_ref and 'cross_platform_map.json' in gm_ref:
            # GM 版正确引用了仓库版作为 install_state 权威源
            # 校验 GM 版 note 中引用的版本号包含仓库版
            gm_note = gm_data.get('note', '')
            ref_versions = re.findall(r'V(\d+\.\d+)', gm_note)
            if not ref_versions:
                # R247 反空过（2026-09-26 实测）：原判据为 `if ref_versions and repo_ver not in
                # ref_versions`，当 GM note 里一个版本号都没有时 ref_versions==[] 直接短路
                # return PASS —— 即「无从比对也判过」。零命中不得判过，改为点名 FAIL。
                return ('FAIL', f'GM note 未引用任何仓库版版本号，install_state 引用无从核验'
                                f'（零命中不判过，R247）；需在 GM cross_platform_map.json 的 note '
                                f'中登记 V{repo_ver}')
            if repo_ver not in ref_versions:
                return ('FAIL', f'GM note 引用 V{ref_versions} 不含仓库 V{repo_ver}（需同步 GM note）')
            return ('PASS', f'双源一致: 仓库 install_state V{repo_ver} ← GM routing_name_mapping V{gm_ver}')
        # 无 install_state_ref → 回退到版本号直接比对
        if repo_ver != gm_ver:
            return ('FAIL', f'仓库 V{repo_ver} != global_memory V{gm_ver}（无 install_state_ref，需手动同步）')
        return ('PASS', f'双源一致 V{repo_ver}')
    except Exception as e:
        return ('FAIL', f'双源校验异常: {e}')



def check_c30_routing_target_liveness(map_=None, direct_pairs=None, baseline=None,
                                      holes_path=None):
    """C30: 路由静态表目标必须存活 + 覆盖空洞棘轮（2026-09-24 GitHub 对标轮 P1-17）。

    根因（实测）：`memory_layer.CONTEXT_SKILL_MAP` 的 37 个映射里有 7 个指向**已退役、
    注册表无、磁盘无**的 skill（skill-install / skill-creator / cross-platform-skill-sync /
    fenjue-advisor-scoring / fenjue-routing-health-check / skill-hitrate-full-audit /
    skill-routing-test-driven-fix）。它们不会「给不存在的技能加权」（boost 只作用于已在候选集
    内的项），而是让「安装/创建/路由/命中率」等意图**静默退化为裸 BGE 召回**——
    这类「表还在、能力已死」的漂移正是主线⑤ strict Top-1 只有 0.34 的可查成因之一。

    判据（三条，缺一即 FAIL，R247 空面不得当通过）：
      W1 死目标：静态表任一目标不在注册表活跃集（direct_map 的哨兵值 'NONE' 除外）。
      W2 空洞棘轮：CONTEXT_SKILL_MAP 中值为空的标签数 ≤ 基线，且基线只许降不许升；
         新增空洞必须显式写进基线并说明理由（禁「默默留空」）。
      W3 空输入：两面扫描均为 0 条目标 = 判据面失效 → FAIL。
    skip_external（CI 无注册表外的盘）时仍读仓库内注册表，故不 SKIP。
    """
    if holes_path is None:
        holes_path = os.path.join(_root.EVAL_DIR, 'routing_holes_baseline.json')
    try:
        reg = _root.load_registry_uni()
    except Exception as e:
        return ('FAIL', '注册表读取失败（无比对基准）: %s' % e)
    live = set(reg.get('skills', {}))
    if not live:
        return ('FAIL', '注册表 skills 为空（比对基准无效）')

    if map_ is None:
        try:
            import memory_layer
            map_ = memory_layer.CONTEXT_SKILL_MAP
        except Exception as e:
            return ('FAIL', 'CONTEXT_SKILL_MAP 不可导入: %s' % e)
    if direct_pairs is None:
        try:
            direct_pairs = _root.load_json(os.path.join(_root.EVAL_DIR, 'direct_map.json'))
        except Exception as e:
            return ('FAIL', 'direct_map.json 读取失败: %s' % e)

    dead = []
    scanned = 0
    for tag, targets in (map_ or {}).items():
        for sk in targets:
            scanned += 1
            if sk not in live:
                dead.append('CONTEXT_SKILL_MAP[%s]->%s' % (tag, sk))
    pairs = direct_pairs if isinstance(direct_pairs, list) else (
        direct_pairs.get('pairs') if isinstance(direct_pairs, dict) else [])
    for pr in pairs or []:
        if not isinstance(pr, (list, tuple)) or len(pr) < 2:
            continue
        scanned += 1
        tgt = pr[1]
        if tgt == 'NONE':          # 显式「不路由」哨兵，非死目标
            continue
        if tgt not in live:
            dead.append('direct_map:%s->%s' % (str(pr[0])[:24], tgt))
    if scanned == 0:
        return ('FAIL', '两面扫描 0 条目标（判据面为空，不得判过，R247）')
    if dead:
        return ('FAIL', '路由静态表死目标 %d 处: %s' % (len(dead), '; '.join(dead[:8])))

    empty_tags = sorted(k for k, v in (map_ or {}).items() if not v)
    if baseline is None:
        if not os.path.exists(holes_path):
            return ('FAIL', '空洞基线未登记: %s（登记格式 = empty_tags 数组 + reason 字典）'
                    % os.path.basename(holes_path))
        baseline = _root.load_json(holes_path)
    allowed = baseline.get('empty_tags')
    if allowed is None:
        return ('FAIL', '空洞基线缺 empty_tags 字段（判据不可信）')
    new_holes = sorted(set(empty_tags) - set(allowed))
    if new_holes:
        return ('FAIL', '新增覆盖空洞 %s（须显式登记进基线并写理由，禁静默留空）' % new_holes)
    if len(empty_tags) > len(allowed):
        return ('FAIL', '空洞数上升: %d > 基线 %d（棘轮只许降）' % (len(empty_tags), len(allowed)))
    return ('PASS', '路由静态表目标全存活（扫描 %d 目标 / 死 0）；空洞 %d 个 ≤ 基线 %d'
            '（棘轮只降不升）' % (scanned, len(empty_tags), len(allowed)))
