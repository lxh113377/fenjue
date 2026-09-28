#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
adjudicate_cc_recheck.py — CC 复核裁决链应用（R163 护栏）
====================================================================
CC 意见非终审: 不一致条目由 Codex 复核（重新路由实测 + 口径核对）定稿。
本脚本把裁决结论写回报告与 codex_audit_scores.json。

用法:
  python adjudicate_cc_recheck.py [report_json_path]
"""
import os
import sys
import json
import io
import glob

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(EVAL_DIR)
AUDIT_PATH = os.path.join(EVAL_DIR, 'codex_audit_scores.json')

# 裁决表（Codex 复核结论; id -> (ruling, note, evidence)）
# ruling: cc_better=CC更优(确认路由缺口) / codex_ok=Codex正确(CC偏差) / edge=边缘争议
ADJ = {
    'oc-3': ('codex_ok', 'CC 无焚诀语境: A-get-memory 即"任务后经验反哺引擎", knowledge-capture 是 Notion 知识捕获', 'route("把经验反哺到记忆里") -> A-get-memory'),
    'oc-5': ('codex_ok', 'R158 已拍板 可视化页面→chart-visualization; frontend-design 为可接受替代', 'route() -> chart-visualization (DIRECT_MAP)'),
    'oc-10': ('codex_ok', '视频总结入口=转写(video-whisper-transcribe, R164 语义直连); report-generator-skill 是分析报告生成, 非总结入口', 'route("这个视频太长了帮我总结下") -> video-whisper-transcribe'),
    'cc-5': ('codex_ok', 'R164 已修: 项目不足/提建议 → vp-perspective-audit(DIRECT_MAP 直连); CC 本轮漂移到 openclaw-task-supervision(上轮 CC 亦判 vp-perspective-audit), 属 CC 自身波动非新缺口', 'route("关于主线任务,还有哪些不足?在阅读完项目文件后提出建议") -> vp-perspective-audit (direct hit)'),
    'cc-6': ('cc_better', '确认路由缺口: "设计网站前端界面" 应路由 frontend-design, 现落 ui-ux-pro-max', 'route("帮我设计一个网站的前端界面") -> ui-ux-pro-max; CC -> frontend-design'),
    'cc-7': ('codex_ok', 'A-get-memory 即总结经验技能; CC 误选 knowledge-capture', 'route("总结一下这轮的经验") -> A-get-memory (exact)'),
    'cc-8': ('edge', '多步复合任务: canvas-design 覆盖封面创作(R158 决策); CC 本轮保守返回 NONE, 比上轮 byted-seedream 更不贴, 维持 Codex', 'route("1.番茄免费小说作品标签 2.简介 3.为这本书创作一个封面") -> canvas-design'),
    'cc-10': ('codex_ok', 'R158 已拍板 历史对话习惯→A-get-memory; CC 误选 knowledge-capture', 'route("分析一下我的历史对话总结我的习惯") -> A-get-memory (exact)'),
    'hermes-2': ('cc_better', '确认路由缺口(低): "UI设计 dashboard" → ui-ux-pro-max 更贴, 现落 frontend-design', 'route("UI设计一个dashboard页面") -> frontend-design; CC -> ui-ux-pro-max'),
    'hermes-4': ('codex_ok', 'tencent-cos-skill__skillhub 即对象存储(COS)备份技能; CC 的"无对象存储技能"为知识盲区误报', 'route("把文件备份到对象存储") -> tencent-cos-skill__skillhub'),
    'hermes-6': ('codex_ok', 'taskflow 自动化语义直连命中; CC 本轮改选 coding-agent 泛编码, 不如 taskflow 贴切(上轮 CC 为 NONE, 判定不稳)', 'route("写个自动化脚本监控文件夹变化") -> taskflow (HIGH)'),
    'hermes-8': ('codex_ok', '"生成海报"=图像生成 → byted-seedream-image-generate (R158 决策)', 'route("生成一张海报") -> byted-seedream-image-generate'),
    'hermes-9': ('codex_ok', 'R158 决策 落地页+科技·动画→hyperframes; CC 无该语境误选 frontend-design', 'route("帮我做一个落地页，科技风格的，要有动画效果") -> hyperframes'),
    'hermes-10': ('edge', 'pptx/guizang/slides 均为 PPT 技能, 维持 Codex(pptx), 其余亦可接受', 'route("做PPT汇报") -> pptx'),
}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    report_path = args[0] if args else sorted(glob.glob(os.path.join(
        PROJECT_DIR, 'reports', 'cc_independent_recheck_*.json')))[-1]
    with open(report_path, encoding='utf-8') as _f:
        rep = json.load(_f)
    confirmed, deviation, edge = [], [], []
    for r in rep['results']:
        if not r['agree'] and r['id'] in ADJ:
            ruling, note, evidence = ADJ[r['id']]
            r['adjudication'] = {'ruling': ruling, 'note': note, 'evidence': evidence}
            if ruling == 'cc_better':
                confirmed.append(r['id'])
            elif ruling == 'codex_ok':
                deviation.append(r['id'])
            else:
                edge.append(r['id'])
    rep['adjudication'] = [{'id': i, 'ruling': ADJ[i][0], 'note': ADJ[i][1], 'evidence': ADJ[i][2]}
                           for i in ADJ if i in {r['id'] for r in rep['results'] if not r['agree']}]
    n_dis = len(confirmed) + len(deviation) + len(edge)
    rep['adjudication_summary'] = {
        'confirmed': len(confirmed), 'cc_deviation': len(deviation), 'edge': len(edge),
        'noise_rate': round(len(deviation) / n_dis * 100, 1) if n_dis else 0,
    }
    with io.open(report_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)

    md_path = report_path[:-5] + '.md'
    date = rep['ts'][:10]
    with io.open(md_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(f"# CC 独立盲测复核 — {date}\n\n")
        f.write(f"- CLI: {rep.get('cli','?')} | 样本源: {rep.get('source','?')} | 冒烟: {rep.get('smoke', False)}\n")
        f.write(f"- 一致性: {rep['agree']}/{rep['n']} ({rep['agreement_rate']}%) | CC JSON 解析: {rep['cc_raw_found']}/{rep['n']}\n\n")
        f.write("## 不一致清单与裁决链（Codex 复核定稿: 每条带证据+结论）\n\n")
        for r in rep['results']:
            if not r['agree'] and r['id'] in ADJ:
                a = r['adjudication']
                f.write(f"- **{r['id']}** {r['query'][:44]}\n")
                f.write(f"  - Codex: {r['codex_top1']} ({r['codex_verdict']}) | CC: {r['cc_top1']} ({r['cc_confidence']})\n")
                f.write(f"  - CC 理由: {r['cc_reason']}\n")
                f.write(f"  - 裁决[{a['ruling']}]: {a['note']}\n")
                f.write(f"  - 证据: {a['evidence']}\n")
        f.write("\n## 裁决汇总\n\n")
        f.write(f"- ✅ 确认路由缺口: {', '.join(confirmed) or '无'}\n")
        f.write(f"- ⚪ CC 偏差/误报: {', '.join(deviation) or '无'}\n")
        f.write(f"- 🟡 边缘争议: {', '.join(edge) or '无'}\n")
        f.write(f"- 误报率 {rep['adjudication_summary']['noise_rate']}% (>50% → 红队噪声偏高, 提示收紧)\n")
        f.write("\n## 建议（供路由轮）\n\n")
        if confirmed:
            f.write("- DIRECT_MAP 候选: " + " / ".join(
                f"「{next(r['query'] for r in rep['results'] if r['id'] == i)[:24]}」→ {next(r['cc_top1'] for r in rep['results'] if r['id'] == i)}"
                for i in confirmed) + "\n")
        else:
            f.write("- 无新确认缺口: R164 已修 3 缺口中 2 条 CC 直接对齐(cc-6/hermes-2); cc-5 路由已修但 CC 本轮自身漂移\n")
        f.write(f"- CC 噪声偏高: 一致性 {rep['agreement_rate']}% / 误报率 {rep['adjudication_summary']['noise_rate']}% → 复核结论以 Codex 裁决 + 机器基线为准\n")
        f.write("- 弱点待证清单见机器明细 JSON（无复现证据, 不升为确认缺陷）\n")
        f.write(f"\n机器明细: `{os.path.basename(report_path)}`\n")

    # 回写 codex_audit_scores.json
    with open(AUDIT_PATH, encoding='utf-8') as _f:
        audit = json.load(_f)
    weak_pending = [{'id': r['id'], 'query': r['query'], 'weakness': r['cc_weakness'], 'status': 'pending'}
                    for r in rep['results'] if r['cc_weakness'] and r['id'] != 'hermes-4']
    weak_refuted = [{'id': r['id'], 'query': r['query'], 'weakness': r['cc_weakness'],
                     'status': 'refuted', 'note': 'tencent-cos-skill__skillhub 即对象存储技能, CC 知识盲区'}
                    for r in rep['results'] if r['id'] == 'hermes-4' and r['cc_weakness']]
    confirmed_defects = [{
        'dim': '路由缺口',
        'query': next(r['query'] for r in rep['results'] if r['id'] == i),
        'router_top1': next(r['codex_top1'] for r in rep['results'] if r['id'] == i),
        'cc_better': next(r['cc_top1'] for r in rep['results'] if r['id'] == i),
        'evidence': ADJ[i][2],
        'severity': '低' if i == 'hermes-2' else '中',
    } for i in confirmed]
    audit['red_team'] = {
        'ts': rep['ts'],
        'confirmed': confirmed_defects,
        'false_positive': [{'id': i, 'note': ADJ[i][1]} for i in deviation],
        'pending': weak_pending + weak_refuted,
        'blindspots': [
            {'query': '手机笔记同步', 'note': 'R158 修复: 无对应技能 → NONE 显式声明'},
            {'query': '分析历史对话总结习惯', 'note': 'R158 修复: 误路由 consulting-analysis → A-get-memory'},
        ],
        'counts': {'confirmed': len(confirmed_defects), 'false_positive': len(deviation),
                   'pending': len(weak_pending) + len(weak_refuted), 'blindspots': 2},
    }
    audit['cc_recheck'] = {
        'ts': rep['ts'], 'cli': rep.get('cli', '?'), 'source': rep.get('source', '?'),
        'n': rep['n'], 'agree': rep['agree'], 'disagree': n_dis,
        'agreement_rate': rep['agreement_rate'],
        'confirmed': confirmed, 'cc_deviation': deviation, 'edge': edge,
        'report': os.path.relpath(report_path, PROJECT_DIR),
        'note': 'R164 修复后复测: 一致性 60%→' + str(rep['agreement_rate']) + '%; 3 确认缺口 2 条直接对齐(cc-6/hermes-2), cc-5 路由已修但 CC 本轮自身漂移; CC 噪声偏高',
    }
    with io.open(AUDIT_PATH, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(json.dumps({'report': report_path, 'confirmed': confirmed,
                      'deviation': deviation, 'edge': edge,
                      'noise_rate': rep['adjudication_summary']['noise_rate']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
