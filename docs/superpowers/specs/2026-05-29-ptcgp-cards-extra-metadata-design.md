# PTCGP cards.extra metadata 自动更新设计

## 目标

完成一条从运行中 PTCGP 游戏导出卡牌 metadata，并更新本仓库 JSON 文件的稳定链路。

边界：

```text
frida-test = 设备 / Frida / IL2CPP / MemoryDatabase exporter
ptcgp-assets = 调用 exporter / 转换为 cards.extra 兼容结构 / 校验 / 落盘
```

最终正式产出：

```text
metadata/cards/<language>/cards.extra.json
```

例如当前繁中环境：

```text
metadata/cards/zh-TW/cards.extra.json
```

不做：

- 不让 `ptcgp-assets` import `frida-test` 内部 TypeScript 模块
- 不把 Frida 逻辑塞进 `fetch_cards.py`
- 不提交 raw exporter JSON
- 不生成 rules JSON
- 不做上游在线拉取作为脚本硬依赖
- 本轮不处理 `goodWith`

## 架构

`frida-test` 提供稳定 CLI：

```bash
npx tsx src/cli/index.ts ptcgp export-metadata --out -
```

`ptcgp-assets` 提供一个简单入口：

```bash
uv run python scripts/update_cards_extra.py --frida-test-dir /path/to/frida-test
```

`ptcgp-assets` 内部执行 exporter，读取 stdout JSON，转换并写入：

```text
metadata/cards/<language>/cards.extra.json
```

CLI stdout 只放 JSON。日志、诊断、错误走 stderr，避免污染管道。

当前链路是一次性 exporter，不是常驻服务：

```text
attach -> dump raw JSON -> stdout marker 完整 -> 主动结束 Frida CLI
```

如果日志在 `emit:done` 后出现 `Failed to load script: operation was cancelled` 且 exit code 为 0，这是主动结束 Frida CLI 的副作用，不代表导出失败。常驻模式需要另建 daemon/RPC 入口，不能把这条一次性 CLI 当长期 session 使用。

## frida-test 设计

新增 PTCGP 专用命令组：

```text
ptcgp export-metadata --out -
```

不需要 `--package-id`。`ptcgp` 命令组已经限定目标应用，包名在内部固定为：

```text
jp.pokemon.pokemontcgp
```

不需要 `--lang`。语言从运行中游戏读取：

```text
Lettuce.Infrastructure.Localization.CardLocalizationSystem
-> gc.choose
-> get_LanguageType()
```

语言规范化规则：

```text
language = String(runtimeLanguage).replaceAll("_", "-")
```

例：

```text
zh_TW -> zh-TW
en_US -> en-US
ja_JP -> ja-JP
```

建议实现位置：

```text
src/cli/commands/ptcgp.ts
src/features/pokemon/metadata/
  export-metadata.ts
  memory-database-exporter.ts
  injected-exporter.ts
  types.ts
```

职责：

- CLI 层：连接设备、attach PTCGP、注入 IL2CPP 脚本、输出 exporter JSON，并在 JSON 完整后结束 Frida CLI
- injected exporter：只读取并开放 `MemoryDatabase`、本地化 raw text、pack join、语言；不做最终字段加工
- 类型层：定义稳定 raw exporter JSON schema

### 关键数据来源

主数据从 `Lettuce.Dto.MasterData.MemoryDatabase` 读取。

关键表：

```text
PokemonCardTable
PokemonTable
TrainerCardTable
TrainerTable
CharacterTable
ExpansionCollectionNumberTable
PackMasterTable
PackTableMasterTable
PackTableLabelMasterTable
PackTableCardMasterTable
```

本地化：

```text
LocalizationTextContext._Data
Kvrom.KvromDictionary<string,string>.get_Item(Il2Cpp.string(msid))
```

pack join：

```text
PackTableCardMaster.CardID
-> PackTableLabelMaster.PackTableLabelID
-> PackTableMaster.PackTableID
-> PackMaster.PackID
```

raw exporter 不做 pack 过滤和显示名加工。它输出 `packId`、`expansionId`、raw localized `PackMaster.NameMSID` 文本、`FeaturedCardIDs`。

pack 过滤和显示名在 `ptcgp-assets/scripts/update_cards_extra.py` 完成：

```text
只保留 PackID 包含 "_00_000"
排除 "_01_000" 派生保底包
PackMaster.NameMSID 是完整本地化展示名，不是最终短 pack 名。
同一 expansion 有多个 `_00_000` 普通包时，使用 PackMaster.FeaturedCardIDs 的第一个可解析 CardID 作为封面卡：CardID -> raw card rows -> Character.DisplayNameMSID raw text；取封面卡名作为 pack 名，卡名末尾 ex 要剥离，例如 Mega Altaria ex -> Mega Altaria。
同一 expansion 只有一个 `_00_000` 普通包时，即使 FeaturedCardIDs 非空，也保留 PackMaster.NameMSID 的完整名称，只规范化冒号，例如 Deluxe Pack: ex -> Deluxe Pack ex。
不要按最后一个空格、冒号后缀或最长公共前缀猜 pack 名。
```

示例：

```text
Genetic Apex Pikachu      -> Pikachu
Mega Rising Mega Altaria  -> Mega Altaria
Deluxe Pack: ex           -> Deluxe Pack ex
```

图片字段：

```text
image = <CardTable row>.IllustrationID + ".webp"
```

具体：

```text
PokemonCard.IllustrationID + ".webp"
TrainerCard.IllustrationID + ".webp"
```

不使用 `CardID + CharacterID + Rarity` 拼接，不从上游继承。

## ptcgp-assets 设计

新增脚本：

```text
scripts/update_cards_extra.py
```

命令：

```bash
uv run python scripts/update_cards_extra.py --frida-test-dir /path/to/frida-test
```

流程：

```text
1. 检查 --frida-test-dir 存在，并包含 package.json / src/cli/index.ts
2. 在该目录执行 ptcgp export-metadata --out -
3. 解析 stdout JSON
4. 读取 language
5. 转换 cards 为 flibustier cards.extra 兼容数组
6. 校验输出
7. 用临时文件 + rename 写 metadata/cards/<language>/cards.extra.json
```

可新增 just target：

```text
update-cards-extra frida_test_dir:
    uv run python scripts/update_cards_extra.py --frida-test-dir '{{ frida_test_dir }}'
```

为保持简单，第一版不加 `--source-file`、不加多语言参数、不加规则文件。

## 输出格式

最终 JSON 顶层为数组，兼容：

```text
https://github.com/flibustier/pokemon-tcg-pocket-database/blob/main/dist/cards.extra.json
```

字段顺序按上游常见顺序：

```text
set
number
name
rarity
image
packs
element
type
stage
health
retreatCost
weakness
evolvesFrom
```

本轮不生成 `goodWith`。它不阻断最终 JSON；后续若确认游戏内明确来源，再单独补。

允许输出比 flibustier 多 key。flibustier 原版仅作为结构参考；当游戏导出的 candidate 与 flibustier 值冲突时，以 candidate 为准。

语言本地化字段：

- `name` 使用当前游戏语言
- `packs` 使用当前游戏语言，并只保留 pack 名本身；例如 `最強的基因 皮卡丘 -> 皮卡丘`
- 如果同一张卡同时属于普通卡包和高级扩充包，`packs` 同时列出这些入口；这是正确数据

## 映射规则

### 通用字段

```text
set      <- ExpansionCollectionNumber.ExpansionID
number   <- ExpansionCollectionNumber.CollectionNumber
name     <- raw exporter localized card name; ptcgp-assets renders [Text:...] rich-text tokens
rarity   <- card row Rarity string
image    <- card row IllustrationID + ".webp"
packs    <- ptcgp-assets builds all normalized pack sources for this CardID from raw pack entries
```

同一 `CardID` 可属于多个 expansion。导出时按 `ExpansionCollectionNumber` 展开为多条最终记录；`packs` 表示该 `CardID` 的所有获取来源，所以 A4b 复刻行和原始 expansion 行可以共享彼此的 pack 来源。主键：

```text
(set, number)
```

排序：

```text
set 自然顺序 + number 升序
```

若同一 `(set, number)` 重复，失败。

### Pokémon

```text
type        = "pokemon"
element     = EnergyType lower-case
stage       = Basic -> "basic", Stage1/One -> 1, Stage2/Two -> 2
health      = Pokemon.HP
retreatCost = Pokemon.RetreatAmount
weakness    = WeaknessType string or null
evolvesFrom = evolves-from Pokémon localized name, or null when absent
```

`element` 写法示例：

```text
Grass -> grass
Fire -> fire
Water -> water
Lightning -> lightning
Psychic -> psychic
Fighting -> fighting
Darkness -> darkness
Metal -> metal
Dragon -> dragon
Colorless -> colorless
```

`weakness` 保持游戏 enum 写法；不做 `Darkness -> Dark` 这类向 flibustier 旧值靠拢的映射。例如：

```text
Fire
Water
Lightning
Psychic
Fighting
Darkness
Metal
Grass
UNSPECIFIED
null
```

### Trainer / Fossil

Trainer 基于：

```text
TrainerCard.TrainerID -> TrainerTable.TrainerID -> TrainerTable.TrainerType
```

TrainerType 映射：

```text
Supporter   -> supporter
Item        -> item
PokemonTool -> tool
Fossil      -> Fossil
Stadium     -> stadium
```

`Fossil` 保持大写，因为 flibustier 使用大写。

Fossil 输出上游兼容形态：

```json
{
  "type": "Fossil",
  "stage": "basic"
}
```

Trainer/Fossil 的 `image` 统一来自：

```text
TrainerCard.IllustrationID + ".webp"
```

## 错误处理

`frida-test` 遇到以下情况直接失败，不输出半成品 raw JSON：

- 找不到 PTCGP 进程
- Frida attach 失败
- 找不到 `MemoryDatabase`
- 找不到 `CardLocalizationSystem` 或语言为空
- 找不到本地化字典
- 关键表缺失
- 任一卡缺 `set`、`number`、`name`、`rarity`、`IllustrationID`、`type`
- `(set, number)` 重复
- 输出 cards 数量为 0

`ptcgp-assets` 遇到以下情况直接失败，不写最终 JSON：

- exporter exit code 非 0
- stdout 不是 JSON
- 缺 `language` 或 `cards`
- `language` 为空
- 最终数组为空
- 字段类型不合法
- enum 映射失败
- `image` 不是 `.webp`
- `(set, number)` 重复

写文件使用临时文件 + rename，避免半写入。

## 校验与核验

脚本内自动校验：

- 顶层输出是数组
- 每条卡有必要字段
- 数字字段是 integer
- `packs` 是 string array
- `image` 非空且以 `.webp` 结尾
- `type` 使用 candidate 规则：`pokemon/supporter/item/tool/Fossil/stadium`
- `stage` 使用 candidate 规则：`basic/1/2`
- `element` 使用 candidate 规则：小写 energy type
- `(set, number)` 不重复

人工/agent 核验：

```text
metadata/cards/<language>/cards.extra.json
vs
flibustier/pokemon-tcg-pocket-database dist/cards.extra.json
```

核验口径：

- flibustier 原版只作为结构和历史格式参考
- candidate 是当前真值；`health`、`retreatCost`、`packs` 等冲突时以 candidate 为准
- `name` 和 `packs` 允许因语言不同而不同
- `goodWith` 本轮忽略
- 游戏有而 flibustier 没有的 key 可以多出
- 核验报告列出差异，差异不自动代表 candidate 错误

## 验证命令

`frida-test`：

```bash
npm run typecheck
```

`ptcgp-assets`：

```bash
uv run python scripts/update_cards_extra.py --help
```

真实链路：

```bash
uv run python scripts/update_cards_extra.py \
  --frida-test-dir /path/to/frida-test
```

抽样检查：

```text
A1 #1:
  name = 妙蛙種子
  image = cPK_10_000010_00_FUSHIGIDANE_C.webp
  element = grass
  type = pokemon
  stage = basic
  health = 游戏导出值
```

## 后续不在本轮范围

- `goodWith` 来源探索与导出
- 多 source 输入模式
- raw JSON fixture
- cards.extra rules 文件
- 自动拉取 flibustier baseline
- 把 exporter 抽成通用多应用接口
