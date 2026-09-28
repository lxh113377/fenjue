# -*- coding: utf-8 -*-
"""verify_checks.skill_layer — 检查函数族（P1-16 拆包，2026-09-23）。

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


def check_c13_skill_version_consistency(skip_external=False):
    """C13(R198.6): skill frontmatter version == 版本历史首行版本号。

    背景：2026-08-16 实测三 skill frontmatter 版本与版本历史首行漂移
    （A-memory-start 10.6.2 vs V10.7.0；A-prompt-better 1.3.0 vs V1.2；
    A-project-handoff 3.9.2 vs 3.9.4），且批量入库在无门禁下改写派生件。
    本检查在提交阶段拦截版本信息不一致，防下游派生文件与源版本漂移。
    规则：解析 SKILL.md frontmatter 的 version 字段，与版本历史区（## 版本历史）
    首条版本记录比对；无版本历史区时跳过该项（社区源可无历史）。
    """
    if skip_external or not _root.external_root_reachable(_root.GLOBAL_SKILLS):
        return ('SKIP', 'global_skills 不可达（CI 环境，C13 保持本地）')
    try:
        uni = _root.load_registry_uni()  # P1-2: 单次加载缓存（原 5 处重复 json.load）
        reg_skills = set(uni.get('skills', {}).keys())
        if not reg_skills:
            return ('FAIL', '注册表 skills 为空，无法枚举 C13 检查对象')
        mismatch, skipped = [], []
        checked = 0
        for name in sorted(reg_skills):
            md_path = os.path.join(_root.GLOBAL_SKILLS, name, 'SKILL.md')
            if not os.path.exists(md_path):
                continue  # 磁盘缺失由 C1 管，C13 只查存在项
            try:
                with open(md_path, encoding='utf-8', errors='replace') as f:
                    text = f.read()
            except Exception as e:
                skipped.append(f'{name}(读取失败:{e!r})')
                continue
            fm_ver = _root._parse_frontmatter_version(text)
            if fm_ver is None:
                skipped.append(f'{name}(无 version 字段)')
                continue
            hist_ver = _root._parse_version_history_first(text)
            if hist_ver is None:
                skipped.append(f'{name}(无版本历史区)')
                continue
            checked += 1
            if not _root._versions_equivalent(fm_ver, hist_ver):
                mismatch.append(f'{name}: frontmatter {fm_ver} vs 历史最大 {hist_ver}')
        if mismatch:
            return ('FAIL', f'版本漂移 {len(mismatch)} 个: ' + '; '.join(mismatch[:8]))
        return ('PASS', f'frontmatter 版本 == 版本历史最大版本（{checked} skill 一致, {len(skipped)} 跳过）')
    except Exception as e:
        return ('FAIL', f'C13 校验异常: {e}')


def check_c20_skill_portability(skip_external=False):
    """C20（2026-09-23 P0-1）：技能可移植性棘轮 —— SKILL.md 绝对路径引用只许降不许升。

    对标产出：Superpowers 有 `test-skill-structure.sh` 检查 local path leakage，本仓此前为零。
    棘轮语义：新增技能含绝对路径 -> FAIL；既有技能 code/inline 计数上升 -> FAIL；
    基线缺失 / 基线为空 / 扫描面为空 -> FAIL（R247：无处可比不得判过）。
    CI（--skip-external 且技能盘不可达）→ SKIP（C10/C13 同口径）；
    CI 侧的新增 deny 由 `--diff` 闸（run_gate portability，可移植）承担。
    """
    _root._ensure_eval_path()
    try:
        import portability_ratchet as pr
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'门禁脚本不可用（禁止以 SKIP 绕过）: {e}')
    try:
        if skip_external and not pr.skills_root_reachable():
            return ('SKIP', '技能盘不可达（CI 环境，C20 保持本地；新增 deny 走 --diff 闸）')
        failures, notes, summary = pr.check()
    except Exception as e:  # noqa: BLE001
        return ('FAIL', f'portability_ratchet.check 异常: {e}')
    if failures:
        return ('FAIL', f'{len(failures)} 项超基线: ' + ' | '.join(failures[:3]))
    return ('PASS', summary)


def check_c23_skill_doc_landing(skip_external=False, decls=None, skills_root=None, baseline=None):
    """C23: 技能文档落点声明必须真实存在且被 noise 认可（P2-6，2026-09-23）。

    decls / baseline 仅供测试注入（同 C16 的 files= 模式），默认真实扫描面 _root.GLOBAL_SKILLS。
    D-48（轮七）：扫描面在技能盘上，技能盘不可达时**不得**报成「声明面收缩」（CI 实测把
    「没有 <SKILLS_ROOT>」冒充「18 条声明被清空」，R247 反例）。注入 decls= 时是纯夹具面，
    照旧全量判，不受降级影响。
    """
    if decls is None and skills_root is None:
        if not _root.external_root_reachable(_root.GLOBAL_SKILLS):
            if skip_external:
                return ('SKIP', '技能盘不可达（CI 环境，C23 保持本地；C20/C25 同口径）: %s'
                        % _root.GLOBAL_SKILLS)
            return ('FAIL', 'W0 技能盘不存在: %s（判据面无从核验）' % _root.GLOBAL_SKILLS)
    if decls is None:
        decls = _root._c23_scan(skills_root)
    base = _root.C23_BASELINE_DECLS if baseline is None else baseline
    if len(decls) < base:
        return ('FAIL', 'W1 声明面收缩（%d < 基线 %d）→ 判据面可能被清空，R247'
                % (len(decls), base))
    issues, checked = [], 0
    for rel, no, root, token, line in decls:
        if _root._c23_is_history(rel, line):
            continue
        checked += 1
        if root in _root.C23_BANNED_ROOTS:
            issues.append('W3 %s:%d 落点 %s 在禁作落点清单（noise VIOL 面）' % (rel, no, root))
        elif _root.C23_VIOL_RE.search(root) and root not in _root.C23_OK_ROOTS and root not in _root.C23_TOOL_OK:
            issues.append('W3 %s:%d 落点 %s 命中 noise VIOL 模式且非认可回收区' % (rel, no, root))
        ok, where = _root._c23_exists(token)
        if ok is False:
            issues.append('W2 %s:%d 落点路径不存在（最近存在祖先=%s）' % (rel, no, where))
    if issues:
        return ('FAIL', '; '.join(issues[:5]))
    return ('PASS', '落点声明 %d 条（现行受检 %d）真实存在且被 noise 认可' % (len(decls), checked))

