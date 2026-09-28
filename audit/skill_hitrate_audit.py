#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skill_hitrate_audit.py — 全网 skill 命中率安全聚合审计器
=========================================================
方法论: audit-runner-safe-aggregate 的「反掩盖(anti-mask)」安全聚合范式
  - 逐行精确匹配带 [FAIL]/[PASS] 标签的明细行, 白名单只豁免「命中行」而非整段
  - 绝不因别处出现合法豁免项而吞掉同段其他真失败 (audit_all.py R84 教训)
  - 致命错误全局优先, 计数行不会被误抓

输入: <MEMORY_ROOT>/skill_content/.json  (L1 runtime triggers — 命中率真正用的层)
输出: 每 skill 一行 [PASS]/[FAIL] 明细 + 末尾安全聚合总评(不假绿)
"""
import json
import glob
import os
import re
import sys

SKILL_CONTENT = r"<MEMORY_ROOT>\skill_content"

# ---- 停用词: 仅纯语法/连接功能词 (不含任何领域动作/对象词) ----
EN_STOP = set("""the a an and or for with this that from when if else while of to in on at by as is are
was were be been being it its he she they them we you your our their my i me him her whom which who
what why how whose where whether not no nor so but yet then than once because although though however
therefore thus also just only very even still more most less few many much such same other another
each every some any all both either neither one two three into over under above below upon through
during without within along among around across behind beside beyond inside outside toward towards
until before after between up down off near far here there now""".split())

# 中文纯功能词/虚词 (垃圾触发词); 领域名词(代码/开发/网站/微信/研究/管理...)一律算自然
ZH_FUNCTION_WORDS = set("""的 了 在 是 有 不 本 其 之 中 上 下 前 后 内 外 对 从 到 和 与 或 及 等
一个 一些 所有 每个 该 此 其中 包括 例如 比如 等等 之类 相关 各种 提供 实现 场景 适用 覆盖 含
核心 主要 基本 完整 标准 通用 专用 定制 自动 手动 每次 任何 唯一 权威 来源 基于 针对 面向 当你
要求 提到 说 问 想 使用 用于 创建 处理 支持 帮助 工具 技能 通过 以及 或者 并且 但是 如果 因为
所以 已经 还是 虽然 可能 应该 不要 没有 什么 怎么 为什么 这个 那个 当用户 用户 需要 进行 可以
这些 那些 一种 这样 那样 我们 你们 他们 它们 自己 哪些 如何 能否 是否 一下 的话""".split())

# 品牌/工具/主题型名字 token — 用户会直接键入, 应视为合法触发词(不算碎片)
MEANINGFUL_NAME_TOKENS = set("""figma docx pptx notion obsidian github gsap whisper deploy openclaw skill
json node local preflight canvas cli asr tts ocr npu api sdk ui ux web git docker k8s code data qoderwork
test debug agent mail wechat tencent cloudbase mcp prompt memory audit handoff router bootstrap
canva midjourney comfyui playwright puppeteer selenium figma unreal blender houdini nuke ae pr
ps ai id lr capture davinci resolve ableton logic protools reaper fl studio reason cubase nuendo
chartjs echarts threejs babylon unity terraform ansible jenkins grafana prometheus argo helm
kafka rabbitmq elasticsearch redis mysql mongo nginx pm2 graphql grpc protobuf websocket oauth
jwt saml ldap smtp imap pop3 ftp sftp ssh vpn dns dhcp http https wmi com activex directx cuda
opencl vulkan opengl webgl tensorflow pytorch sklearn pandas numpy matplotlib seaborn plotly""".split())

def is_name_fragment(trig, skill_name):
    """触发词是 skill 名 kebab 拆分的"无语义通用碎片"才算垃圾。
    品牌/工具/主题型 token(figma/docx/notion/obsidian/github/...)用户会直接键入, 视为合法触发词。"""
    toks = [t for t in re.split(r"[-_]", skill_name.lower()) if t]
    low = trig.lower()
    if low in toks:
        if low in MEANINGFUL_NAME_TOKENS:
            return False
        return True
    return False

def trig_quality(trig, skill_name):
    """返回 ('natural'|'garbage', reason)
    判定哲学: 触发词只要"用户会真实输入且语义关联 skill"即自然。
      - 垃圾 = ①skill名kebab拆分碎片(无语义扩展) ②纯英文停用词 ③中文单字/纯虚词
      - 自然 = 其余一切: 中文2+字领域词(代码/开发/网站/微信/研究/管理...)、英文技术短词(debug/test/web/http)、引号短语等
    """
    t = trig.strip()
    if len(t) < 2 or len(t) > 25:
        return ("garbage", "length")
    low = t.lower()
    if is_name_fragment(t, skill_name):
        return ("garbage", "name_fragment")
    if low in EN_STOP:
        return ("garbage", "en_stop")
    # 中文: 单字功能词或纯虚词集 => 垃圾; 其余(含2-3字领域名词) => 自然
    if re.search(r"[\u4e00-\u9fff]", t):
        if len(t) == 1 or t in ZH_FUNCTION_WORDS:
            return ("garbage", "zh_function")
        return ("natural", "")
    # 英文/数字/符号: 非停用词非名字碎片 => 自然 (debug/test/web/http 等技术短词均算)
    if re.match(r"^[A-Za-z0-9_.-]+$", t):
        return ("natural", "")
    return ("natural", "")

def audit_skill(skill):
    name = skill.get("name", "")
    trigs = skill.get("triggers", []) or []
    if not trigs:
        return ("FAIL", "空triggers(退化为skill名)")
    nat = gar = 0
    details = []
    for tg in trigs:
        q, r = trig_quality(tg, name)
        if q == "natural":
            nat += 1
        else:
            gar += 1
            details.append(f"{tg}[{r}]")
    if nat == 0:
        return ("FAIL", f"全垃圾:{','.join(details)}")
    if gar > 0:
        return ("WEAK", f"垃圾{nat}/{len(trigs)}混:{','.join(details)}")
    return ("PASS", f"自然{nat}/{len(trigs)}")

def main():
    files = sorted(glob.glob(os.path.join(SKILL_CONTENT, "*.json")))
    total = 0
    pass_n = weak_n = fail_n = 0
    fail_lines = []   # 逐行明细(anti-mask)
    for f in files:
        if os.path.basename(f) == "skill_ids.json":
            continue
        data = json.load(open(f, encoding="utf-8"))
        for s in data.get("skills", []):
            total += 1
            verdict, detail = audit_skill(s)
            line = f"[{verdict}] {s['name']}: {detail}"
            if verdict == "PASS":
                pass_n += 1
            elif verdict == "WEAK":
                weak_n += 1
                fail_lines.append(line)   # 弱也计入需关注
            else:
                fail_n += 1
                fail_lines.append(line)
    # ---- 安全聚合总评(逐行匹配, 不整段豁免) ----
    print("=" * 70)
    print(f"SKILL HITRATE AUDIT — 总样本 {total}")
    print(f"  [PASS] 全自然 : {pass_n}")
    print(f"  [WEAK] 混合   : {weak_n}")
    print(f"  [FAIL] 命中率崩溃: {fail_n}")
    print(f"  健康率(PASS/(TOTAL)): {pass_n/total*100:.1f}%")
    print(f"  含弱/崩命中率堪忧: {(weak_n+fail_n)/total*100:.1f}%")
    print("=" * 70)
    print(f"待测明细行(需修复): {len(fail_lines)}")
    for ln in fail_lines:
        print("  " + ln)
    # 致命判定: 任何崩溃即总评 FAIL(不假绿)
    if fail_n > 0:
        print(f"\n[AGGREGATE] FAIL — {fail_n} 个 skill 命中率崩溃, 必须修复")
        sys.exit(1)
    elif weak_n > 0:
        print(f"\n[AGGREGATE] WEAK — 无崩溃但 {weak_n} 个混合, 建议优化")
        sys.exit(0)
    else:
        print("\n[AGGREGATE] PASS — 全部 skill 命中率健康")
        sys.exit(0)

if __name__ == "__main__":
    main()
