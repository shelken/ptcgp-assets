# Agent 工作指南

## 稀疏检出（Sparse Checkout）要求

本仓库包含大量图片文件（`images/` 目录，超过 5000 张图片）。为避免不必要的下载，**必须启用稀疏检出模式**。

### 检查当前是否启用稀疏检出

```bash
# 检查 git config
if git config --get core.sparseCheckout >/dev/null 2>&1; then
    echo "稀疏检出已启用"
else
    echo "稀疏检出未启用，需要启用"
fi
```

### 启用稀疏检出

如果当前未启用，按以下步骤操作：

```bash
# 1. 如果已克隆完整仓库，先清理
git checkout -- .
git clean -fd

# 2. 启用稀疏检出
git sparse-checkout init --cone

# 3. 设置只检出代码文件，排除 images/ 目录
git sparse-checkout set fetch_cards.py README.md pyproject.toml

# 4. 重新检出
git checkout main
```

### 稀疏检出下的工作

启用后，本地只会保留：
- `fetch_cards.py` - 下载脚本
- `README.md` - 项目文档  
- `pyproject.toml` - 依赖配置
- `.git/` - Git 仓库元数据

**不包含** `images/` 目录的任何文件。

### 允许的操作

在稀疏检出模式下，你可以：
- ✅ 修改代码文件（`fetch_cards.py`, `README.md` 等）
- ✅ 添加新脚本或配置文件
- ✅ 正常 commit 和 push
- ✅ 运行下载脚本（图片会保存到本地 `images/` 目录，但不会被 Git 追踪）

### 禁止的操作

- ❌ 不要尝试 `git add images/` - 图片应该通过脚本生成，不应该手动添加到 Git
- ❌ 不要禁用稀疏检出去下载整个仓库（除非特殊情况）

### 需要查看图片时

```bash
# 临时添加特定卡包到本地
git sparse-checkout add images/zh-TW/cards-by-set/A1

# 使用完成后清理（可选）
git sparse-checkout set fetch_cards.py README.md pyproject.toml
```

## 项目背景

- **数据来源**: [PokeOS](https://www.pokeos.com/) API
- **用途**: 存放 PTCGP 卡牌静态资源，通过 GitHub Raw 链接作为图床使用
- **管理**: 使用 `fetch_cards.py` 脚本自动下载和更新

## 技术栈

- Python 3.12+
- uv (依赖管理)
- aiohttp (异步下载)
- Git 稀疏检出
