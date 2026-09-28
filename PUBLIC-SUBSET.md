# 对外子集的生成口径（可核验声明）

本目录由源仓已提交 SHA `5470b01` 经 `git archive` 生成，**不读工作树**
（源仓常有并发会话在写，工作树不是可信取料面）。

## 取料面（INCLUDE）

- `eval`
- `audit`
- `scripts`
- `skill/registry`
- `skill/tools`
- `publish/fenjue-public`
- `feedback`
- `.github`
- `.ci`
- `requirements-ci.txt`
- `pyproject.toml`
- `.gitattributes`
- `.coveragerc`
- `.pre-commit-config.yaml`

## 排除面（EXCLUDE，正则）

| 模式 | 为什么排除 |
|---|---|
| `^scripts/\.prompt_versions/` | 含个人档案（姓名/班级/学号），无功能作用 |
| `^skill/registry/disk_manifest\.json$` | 本机磁盘快照，换机即假 |
| `^eval/derivative_manifest\.json$` | 派生件的本机指纹 |
| `^audit/20\d\d-` | 带日期的内部审计报告（叙事，非代码） |
| `^skill_tree/audits/` | 同上 |
| `^skill_tree/LESSONS` | 私有经验正文 |
| `^skill_tree/\d{4}-` | 带日期的主线报告 |
| `^eval/\.fingerprint` | 本机行为指纹库 |
| `^eval/_cache/` | 可再生缓存 |
| `^eval/bge_onnx/` | 182 MB 模型权重，不随包分发 |
| `^publish/fenjue-public/docs/showcase\.png$` | 演示截图（体积/无关代码） |
| `^publish/fenjue-public/scripts/check_public_clean\.py$` | 旧清洁门禁把学号/姓名以字符串拼接藏在脚本自身里且扫不到自己，由重写版取代 |
| `__pycache__/` | 生成物 |
| `\.pyc$` | 生成物 |

## 脱敏映射（SCRUB）

只写**类别 → 占位符**，不写正则原文：正则原文里就带着被脱敏的那些值本身，
把清单写成原文等于「记录脱敏的文件自己泄露」（本条为实测自打：首版就这么红了 11 处）。

| 匹配类别 | 替换为 |
|---|---|
| 机器用户目录前缀（盘符 + Users + 本机 uid） | `<USER_HOME>` |
| 本机记忆根绝对路径（盘符 + global_memory） | `<MEMORY_ROOT>` |
| 本机技能库根绝对路径（盘符 + global_skills） | `<SKILLS_ROOT>` |
| 本机 npm 全局根 | `<NPM_GLOBAL>` |
| 学籍号（含被拆成两段的写法） | `<STUDENT_ID>` |
| 权利人真实姓名 | `<OWNER>` |
| 权利人昵称 | `<OWNER_NICK>` |
| 私人 API 代理域名 | `<PROXY_HOST>` |
| uid 以路径段字面量出现（门禁前缀表内） | `'<USER_UID>'` |

## 本次实测计数

- 写入 404 件 / 排除 15 件 / 被脱敏 126 件（替换 818 处）/ 二进制直通 1 件

落盘后**当场复扫**：`VERIFY_PATTERNS` 命中数必须为 0，否则构建器 rc=1。
该复扫有双向自证：往投递面注入一条 uid 串必须判红，还原后必须判绿。
