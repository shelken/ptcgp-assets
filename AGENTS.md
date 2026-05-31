# Agent 工作指南

## 图片与稀疏检出规则

- 新 clone 可以用 sparse checkout 排除 `images/`，避免首次拉取全部图片。
- 如果本地已经有 `images/`，不要擅自把它排除或收起。
- 需要查看、生成、校验图片时，本地必须保留对应 `images/` 目录。
- 只有用户明确要求减少本地图片时，才允许临时收窄 sparse 规则。
- 临时收窄后，任务结束前要按用户需要恢复图片可见性。

## 项目背景

- **数据来源**: [PokeOS](https://www.pokeos.com/) API
- **用途**: 存放 PTCGP 卡牌静态资源，通过 GitHub Raw 链接作为图床使用
- **管理**: 使用 `fetch_cards.py` 脚本自动下载和更新

## 技术栈

- Python 3.12+
- uv (依赖管理)
- aiohttp (异步下载)
- Git 稀疏检出
