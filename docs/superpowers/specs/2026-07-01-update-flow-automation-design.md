# 新系列更新流程自动化设计

## 目标

新系列上线后，用户只需「确保 bs air 游戏更新到最新版本并进游戏主页」，运行一次 `just update-all` 即可完成全部资源更新流程：下载卡牌图、生成 hash、导出 metadata、导出卡包图片、校验产出。无需手动传 frida-test 路径、手动启动 bridge、手动指定 port。

## 原则

- 能自动探测/判断的，不写死硬编码
- 不为不存在的需求写兜底
- 最小修改范围，脚本保持单职责

## 现状（已验证）

| 脚本 | 职责 | 幂等性 | 现状痛点 |
|---|---|---|---|
| `fetch_cards.py` | 从 PokeOS 下载卡牌图 | ✅ 文件存在即 skip | 无 |
| `scripts/update_metadata.py` | 调 frida-test 导出 cards.extra + sets.json | ✅ tmp+replace 原子覆盖 | 需手动传 `--frida-test-dir` |
| `scripts/update_pack_images.py` | 调 bridge 导出卡包图 | ✅ 覆盖写 | 需手动启动 bridge、传 bridge-url |
| `scripts/generate_hashes.py` | 生成感知哈希 | ✅ 全量重算覆盖 | 默认只 zh-TW，需手动跑 |
| `scripts/verify_metadata_coverage.py` | 校验 metadata 覆盖 | — | 输出仅 pass/fail，不够可观测 |

**关键技术事实（已查 frida-test 源码验证）：**

- `ptcgp export-metadata` 是一次性 raw exporter，一次导出**当前游戏运行语言**的 metadata。exporter 内部已内置 `prepareFridaServer` + `chooseTargetDevice` + BlueStacks config 解析，frida/设备选择由 frida-test 自管。
- bridge 只暴露 `POST /ptcgp/run` 一个端点，无 health check。`update_pack_images.py` 的 `wait_for_bridge` 已用 `ptcgp.packImages.raw limit=1` 探测请求判断 bridge 是否就绪。
- bridge 一次 RPC 能拿全 9 语言 pack 图片（PACK_IMAGE_LANGUAGES 写死在 injected-runtime），卡包图天然全语言。
- 卡牌图走外部 PokeOS 下载，与游戏运行态无关，要几种语言下几种。
- frida-test 实际位置 `~/Code/active/frida-test`（"active" 暗示会移动，不能写死）。
- adb 设备 `192.168.10.1:5555` 已连，BlueStacks 在 `/Applications/BlueStacks.app`。

## 范围边界

**本轮做（方案 A）：**

- metadata 维持当前游戏语言导一次（通常 zh-TW 或 en-US）
- 卡牌图、hash、卡包图走全语言自动（语言集合按 `images/<语言>/` 实际目录发现，不写死）
- frida-test 目录自动探测（L2）
- bridge port 自动探测/复用/按需拉起（L2）
- hash 按 set 增量生成（H2）
- 设备步骤 fail-fast + 本地步骤可重试 + 最后汇总报告（F2）

**本轮不做（另立项）：**

- frida-test 侧支持全语言 metadata 输出。需要重新分析游戏 IL2CPP 数据结构，确认是否存在多语言数据并存的途径（LocalizationTextContext 能否按需加载非当前语言、或有无按 locale 的静态本地化表）。属跨仓库改动，不在本轮。
- bs air 自动拉起。冷启动后游戏没进主页 frida attach 会卡死游戏（frida-test AGENTS.md 硬约束），自动拉起反而踩坑。bs air 启动 + 游戏进主页由用户手动确认。

## 编排架构

```
just update-all
   ├─ just update-online   (无设备依赖，可随时重跑)
   │    ├─ ① 下载卡牌图     fetch_cards.py (语言按 images/ 发现)
   │    └─ ② 增量生成 hash  generate_hashes.py (H2: set mtime 比较, 语言自动发现)
   └─ just update-device    (需设备+游戏进主页)
        ├─ ③ 探测 frida-test 目录 (L2 搜索链)
        ├─ ④ export metadata (复用 frida-test 内置 frida/设备选择)
        ├─ ⑤ 探测 bridge port → 复用或拉起 → 导出 pack 图片
        ├─ ⑥ 校验产出 + 汇总报告 (verify_metadata_coverage.py 增强)
        └─ (设备步骤 fail-fast)
```

### 入口拆分理由

设备相关步骤（metadata/pack）失败率高（游戏没进主页/设备没连），拆成 `update-online` + `update-device` 两个独立入口 + `update-all` 串两者，让用户能单独重跑设备步骤而不必重跑下载。

## L2 自动探测

### frida-test 目录探测（`scripts/resolve_env.py`）

搜索链（取第一个通过校验的，全部失败报错退出并提示设置 `FRIDA_TEST_DIR`）：

```
$FRIDA_TEST_DIR (环境变量优先)
  → ~/Code/active/frida-test
  → ~/Code/frida-test
  → ../frida-test (相对仓库根)
  → 兄弟目录里含 package.json + src/cli/index.ts 的第一个
```

校验条件：目录存在 + 含 `package.json` + 含 `src/cli/index.ts`（复用 `update_metadata.py` 现有校验）。

### bridge port 探测 + 复用/拉起

```
1. 检测 8765 是否监听
2. 发 ptcgp.packImages.raw limit=1 探测请求
   ├─ 成功 → bridge 在跑，复用，不拉起
   └─ 失败 → 用 --bridge-command 拉起 bridge
            (命令: ./node_modules/.bin/tsx src/cli/index.ts ptcgp bridge)
            → wait_for_bridge 轮询探测请求，超时报错
3. bridge 生命周期由 update_pack_images.py 的 --bridge-command 机制管理
   (复用其现有 start_bridge/wait_for_bridge/terminate，不改)
```

`resolve_env.py` 只负责探测和判断，输出 `frida_test_dir` 和 `bridge_url`（以及是否需要拉起 bridge 的标志），不负责实际启动 bridge——实际启动仍由 `update_pack_images.py` 的 `--bridge-command` 机制完成。

## H2 hash 增量

对每个 set：

```
hash_json = hashes/<locale>/<set>.json
set 图片目录 mtime = max(images/<locale>/cards-by-set/<set>/* 的 mtime)
if hash_json 存在 and hash_json.mtime >= set 图片目录 mtime:
    skip (打印 "skip A1, 未变动")
else:
    重算该 set, 覆盖写
```

### 语言发现（不写死）

扫描 `images/` 下的子目录（zh-TW, en-US, ...），对每个语言目录扫描 `cards-by-set/<set>/`，对每个 set 跑 H2 增量逻辑。卡牌图只下 zh-TW/en-US 就只生成这两套 hash；多下一种语言自动跟进，无需改配置。

## 失败语义（F2）

- **设备步骤（metadata/pack）fail-fast**：一旦失败基本是"游戏没进主页/设备没连"硬故障，继续重试无意义，快速暴露错误并退出。
- **本地步骤（下载/hash）可重试**：失败保留已下载/已生成产物，下次重跑即可，不阻断流程。
- **最后汇总报告**：明确列出每个语言的 metadata/卡牌图/hash/pack 各自状态，不靠 exit code 猜。

### 汇总报告定性

metadata 在汇总里标"❌ 未导出"**不算失败、只算"待补"提示**——方案 A 本就只导当前游戏语言，其他语言 metadata 缺失是预期状态，不是故障。校验脚本增强输出为多语言汇总，列出每个语言各项状态。

## 脚本改动清单

| 文件 | 改动 |
|---|---|
| `scripts/resolve_env.py` | **新增**：frida-test 目录探测 + bridge port 探测/拉起判断 |
| `scripts/generate_hashes.py` | 改：`--locale` 可选 + 缺省多语言循环；加 H2 mtime 增量跳过 |
| `scripts/update_metadata.py` | 改：`--frida-test-dir` 可选，缺省调 `resolve_env` |
| `scripts/update_pack_images.py` | 改：`--bridge-command`/`--bridge-cwd` 缺省调 `resolve_env` |
| `scripts/verify_metadata_coverage.py` | 改：增强输出为多语言汇总报告 |
| `justfile` | 重组为分层入口（update-all / update-online / update-device） |
| `README.md` | 更新"新系列更新流程"为一键说明 |

### 脚本签名变更

- `update_metadata.py`：`--frida-test-dir` 改为可选，缺省时调 `resolve_env` 探测
- `update_pack_images.py`：`--bridge-url` 已有默认值 8765，保持；`--bridge-command`/`--bridge-cwd` 缺省时调 `resolve_env` 提供
- `generate_hashes.py`：`--locale` 改为可选，缺省时扫描 `images/` 下所有语言

## justfile 结构

```just
default:
    @just --list

# === 一键全流程 ===
update-all:
    just update-online
    just update-device

# === 无设备依赖（可随时重跑）===
update-online:
    uv run fetch_cards.py
    uv run python scripts/generate_hashes.py
    @echo "✅ online 完成"

# === 需设备 + 游戏进主页 ===
update-device:
    #!/usr/bin/env bash
    set -euo pipefail
    FRIDA_TEST_DIR=$(uv run python scripts/resolve_env.py --frida-test-dir) \
      uv run python scripts/update_metadata.py
    BRIDGE_URL=$(uv run python scripts/resolve_env.py --bridge-url) \
      uv run python scripts/update_pack_images.py --bridge-url "$BRIDGE_URL"
    uv run python scripts/verify_metadata_coverage.py
```

## 幂等性（已验证，无需改造）

四个脚本天然幂等，`update-all` 可安全重复执行：

- `fetch_cards.py`：文件存在即 skip
- `generate_hashes.py`：整 set 重算覆盖写，输入不变输出不变
- `update_metadata.py`：tmp 写入 + replace 原子覆盖
- `update_pack_images.py`：write_webp 直接覆盖写

## 后续待办（不在本轮）

- frida-test 全语言 metadata 支撑：分析游戏 IL2CPP 数据结构，确认 LocalizationTextContext 能否按需加载非当前语言，或是否存在按 locale 的静态本地化表。若有，在 frida-test 侧新增按 locale 提取的 raw exporter，ptcgp-assets 侧去掉方案 A 的"单语言"限制。
