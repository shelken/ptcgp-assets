# PTCGP 卡牌静态资源

本项目用于存放 Pokémon TCG Pocket（PTCGP）的卡牌静态资源。

## 数据来源

卡牌图片资源来自 [PokeOS](https://www.pokeos.com/)，通过 API 获取并整理存放。

## 目录结构

```
images/
├── zh-TW/
│   └── cards-by-set/
│       └── [set_code]/
│           └── [number].png
└── en-US/
    └── cards-by-set/
        └── [set_code]/
            └── [number].png
```

- `zh-TW`：繁体中文卡牌
- `en-US`：英文卡牌
- `[set_code]`：卡包代码（如 A1, A2, PROMO-A 等）
- `[number]`：卡牌编号

## 使用方式

直接通过 GitHub Raw 链接访问图片：

```
https://raw.githubusercontent.com/[用户名]/[仓库名]/main/images/[语言]/cards-by-set/[set_code]/[number].png
```

例如：
```
https://raw.githubusercontent.com/username/ptcgp-assets/main/images/zh-TW/cards-by-set/A1/1.png
```

## 资源获取

使用 `fetch_cards.py` 脚本从 PokeOS 获取最新卡牌资源：

```bash
# 安装依赖
uv pip install -e .

# 下载所有系列卡牌
uv run python fetch_cards.py

# 下载指定系列
uv run python fetch_cards.py --series a

# 更多参数
uv run python fetch_cards.py --help
```

### 智能探测模式

脚本针对 **PokeOS API 返回卡牌数量为 0 的集合**（如 PROMO-B）会自动启用探测模式：

- 从 #1 开始递增探测
- 成功下载则继续下一个编号
- 连续遇到 **3 次 404** 则停止该语言探测
- 上限 **200 张**，防止无限循环

此机制确保即使 API 数据不完整，也能尽可能获取可用资源。

## 开发指南

### 稀疏检出（Sparse Checkout）- 排除模式

由于本仓库包含大量图片文件（`images/` 目录），为避免下载整个仓库，建议使用 **Git 稀疏检出** 模式：

```bash
# 1. 克隆仓库，但只获取元数据，不下载文件内容
git clone --filter=blob:none --no-checkout https://github.com/shelken/ptcgp-assets.git

cd ptcgp-assets

# 2. 启用稀疏检出（非 cone 模式，支持排除语法）
git sparse-checkout init

# 3. 设置排除规则：只排除 images/ 目录，保留其他所有文件
cat > .git/info/sparse-checkout << 'EOF'
/*
!images/
EOF

# 4. 检出 main 分支（只下载你指定的文件）
git checkout main
```

**效果**：本地只有工作所需的脚本和配置，没有 `images/` 目录，节省磁盘空间和下载时间。

**排除模式说明**：
- `/*` - 包含所有文件和目录
- `!images/` - 排除 images/ 目录
- 自动包含根目录下所有代码文件，无需逐个列出

### 临时查看图片目录

如果需要临时查看某个卡包的图片：

```bash
# 临时添加特定目录到本地（在排除模式下）
cat > .git/info/sparse-checkout << 'EOF'
/*
!images/
images/zh-TW/cards-by-set/A1/
EOF
git checkout main

# 使用完成后恢复
# 或者恢复完整仓库
git sparse-checkout disable
```

### 提交新文件

稀疏检出模式下可以正常提交代码：

```bash
# 修改或添加文件（如 fetch_cards.py）
git add fetch_cards.py
git commit -m "fix: xxx"
git push origin main
```

**注意**：推送后，远程仓库会正常更新，但不会影响本地的稀疏检出设置。

## 已知问题

由于 PokeOS 自身数据源缺失，**A 系列**存在以下卡牌无法下载：

| 卡包 | 语言 | 缺失编号 |
|------|------|----------|
| A1a | 中文 | #63 |
| A2a | 中文 | #75 |
| PROMO-A | 双语 | #109, #110, #111, #112, #113, #114, #115, #116, #117 |

**共 20 张缺失**（A1a 1张 + A2a 1张 + PROMO-A 18张）。

运行脚本时会输出详细失败链接列表，便于确认具体缺失资源。

## 协议

本项目仅用于技术学习和个人使用。
