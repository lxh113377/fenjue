# 第三方组件与许可证清单

本仓对外子集**不捆绑任何第三方源码**（无 vendoring、无 git submodule）。
下表只列运行期通过包管理器拉取的依赖，以及它们的许可证归属。

| 组件 | 用途 | 许可证 | 获取方式 |
|---|---|---|---|
| numpy | 数值计算，TF-IDF 向量的底层 | BSD-3-Clause | `pip install -r requirements.txt` |
| scikit-learn | TF-IDF 向量化与余弦相似度（`eval/hitrate_cli.py`） | BSD-3-Clause | 同上 |
| pytest | 测试运行器 | MIT | `pip install -r requirements-ci.txt` |
| scipy | sklearn 的传递依赖 | BSD-3-Clause | 由 pip 解析 |
| joblib | sklearn 的传递依赖 | BSD-3-Clause | 由 pip 解析 |
| threadpoolctl | sklearn 的传递依赖 | BSD-3-Clause | 由 pip 解析 |

完整 CI 链另需 `onnxruntime`（Apache-2.0，语义层 BGE 后端）与 `flask`（BSD-3，
反馈 API），二者**不在最小可跑路径上**，未装也能跑 README 的第一条命令。

## 权属声明

- 本仓代码与文档为作者个人原创，以 MIT 许可分发，版权归 `LICENSE` 所列署名人。
- `examples/skills/*.md` 与 `examples/queries.json` 是为演示评估链而**新写的合成数据**，
  不含任何真实用户内容、真实技能正文或生产语料。
- 作者私有工作区中的技能包正文、会话日志、记忆语料**未随本子集分发**。
