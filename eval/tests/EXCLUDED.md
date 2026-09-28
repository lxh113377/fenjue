# 未随对外子集分发的测试模块（具名登记）

源仓在同一 SHA 下共 **90** 个测试模块（数法：摘除前面目录里的
`test_*.py` 件数 = 现存 70 + 摘除 20，
不手抄）。其中下列模块断言的是**作者本机的真仓状态、私有技能根或
182 MB 模型权重**，在对外子集里必然测不到东西——实测失败原文形如
`fatal: not a git repository`、"CI 状态已 76 小时未更新"、junction 未挂载。

处置口径：**摘除模块并在此具名登记，而不是放宽断言**。放宽断言等于造一把
恒绿的尺子，比不测更坏。摘除后对外子集的用例数与通过率见 `README.md`
「测试说明」一节，该数字由**干净 clone 面实跑**得出，不是本表推算。

| 模块 | 状态 | 原因 |
|---|---|---|
| `test_ci_block_reason.py` | 已摘除 | 读真实 GitHub Actions 状态文件，对外子集无该状态面 |
| `test_ci_green_contract.py` | 已摘除 | 断言 .ci/contract.json 已被 git 跟踪，需真仓 git 索引 |
| `test_control_char_lock.py` | 已摘除 | 扫真仓 git ls-files 全表面的控制字符 |
| `test_faces_wiring.py` | 已摘除 | 对真仓台账与取数面做接线对账（5 例） |
| `test_lessons_hitrate.py` | 已摘除 | 需真实 lessons 语料与行为指纹库 |
| `test_reconcile_next_steps.py` | 已摘除 | 对真仓 07 卷做哈希对账 |
| `test_release_notes_lock.py` | 已摘除 | 对真仓 RELEASE-NOTES 面与其 SHA 目标做锁校验（4 例） |
| `test_static_locks_gate.py` | 已摘除 | 断言「本机真面此刻为绿」，本质是机器局域量 |
| `test_truth_consistency.py` | 已摘除 | 其中 3 例（C25/C28 真面）需私有注册表与 CI 可达性 |
| `test_bge_layer.py` | 已摘除 | 需 182 MB BGE ONNX 模型权重与语料 npy，不随包分发 |
| `test_boost_lesson_confidence.py` | 已摘除 | 对真实 lessons 语料做置信度回写 |
| `test_ci_face_degradation.py` | 已摘除 | 扫作者本机技能根，验盘符字面量不得外流 |
| `test_ewa_taint.py` | 已摘除 | 断言作者本机绝对路径集合为「外部」，与占位符化后的面冲突 |
| `test_gate_stub_runner.py` | 已摘除 | 对私有 eval/stubs 全量注册表做覆盖对账 |
| `test_guardrail_checks.py` | 已摘除 | 扫描根取自私有 truth_constants 的机器路径单源 |
| `test_inject_source_guard.py` | 已摘除 | 断言注入面在作者双平台盘符下均为绝对路径 |
| `test_portability_diff.py` | 已摘除 | 对私有技能根（占位符 <SKILLS_ROOT>）全树做可移植性 diff |
| `test_r273_benchmark_round_gates.py` | 已摘除 | 盲测 CI 步依赖私有基准轮产物 |
| `test_routing_index_health.py` | 已摘除 | junction 挂载健康度只能在作者本机判（对外必为未挂载） |
| `test_skill_size_report.py` | 已摘除 | 对私有技能卷的落盘字节与 CRLF 面出报告 |

保留在面的测试仍覆盖：四层路由的直连/Tag/语义层、真相源一致性门禁的纯函数侧、
pre-commit 各闸的隔离桩、命中率评估 CLI、噪声治理与体量治理的判据桩。
