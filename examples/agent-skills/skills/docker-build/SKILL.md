---
name: docker-build
description: 镜像构建：镜像越构建越慢、或者体积失控时。流水线里的作业调度问题（那条走 ci-pipeline）。
triggers: 构建 镜像 dockerfile 层 缓存 依赖 docker 体积
---

# 镜像构建（Agent Skills 标准目录格式示例）

## 何时使用

镜像越构建越慢、或者体积失控时。流水线里的作业调度问题（那条走 ci-pipeline）。

## 不做

- 不接真实生产数据；本件是合成示例，用于让评估链零私有语料可跑。
