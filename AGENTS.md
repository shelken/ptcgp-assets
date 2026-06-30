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

## Agents Remind

### 更新流程架构

- 入口分层：`just update-all` = `just update-online`（无设备依赖）+ `just update-device`（需设备+游戏主页）。新增步骤时归入对应层，不要新增独立 recipe。
- 环境探测收口在 `scripts/resolve_env.py`：frida-test 目录、bridge command/cwd 的探测逻辑只在这一处，脚本/justfile 不硬编码路径。新增需探测的环境项，扩展 resolve_env。
- 语言集合不写死：按 `images/<语言>/cards-by-set` 实际目录发现（`generate_hashes.py` 的 `discover_locales`），新增语言下载卡牌图后自动跟进，无需改配置。
- 设备步骤 fail-fast：`update-device` 用 `set -euo pipefail`，一步挂即报错退出，不静默继续。
- 四个脚本天然幂等（文件存在跳过 / 覆盖写 / tmp+replace），`update-all` 可安全重复执行，不要为幂等加额外防护代码。
- metadata 只导出当前游戏运行语言（方案 A），其他语言 metadata 缺失是预期状态，不是故障，汇总报告中用「—」而非「❌」表示。
