# PTCGP sets metadata

本目录存放从运行中的 PTCGP 游戏导出的系列 metadata。

## 文件

```text
metadata/sets/<language>/sets.json
```

当前已生成：

```text
metadata/sets/en-US/sets.json
```

## 数据准则

- 游戏 `MemoryDatabase` 是事实来源。
- 与 flibustier 原版不一致时，以本目录产物为准。
- flibustier 原版只作为覆盖验证的 baseline，不作为数值真值，也不用于填充本地产物。
- `name`、`packs` 使用当前游戏语言。
- `releaseDate` 不从游戏提取，固定输出 `null`。

## 字段来源

| 输出 key | 游戏来源 / 规则 | 说明 |
| --- | --- | --- |
| `code` | `Expansion.ExpansionID` | 系列主键，例如 `A1`、`A1a`、`PROMO-A`。 |
| `name` | `Expansion.LongNameMSID` 本地化值优先，其次 `Expansion.NameMSID` 本地化值 | 输出为 flibustier 兼容对象，例如 `{ "en": "Genetic Apex" }`。PROMO 类系列如果缺少本地化名称，需要单独确认游戏内真实来源，不能从 baseline 硬填。 |
| `count` | 已转换 `cards.extra.json` 中同一 `set` 的卡牌数量 | 统计系列内展示卡数量，不从 pack 表反推。 |
| `releaseDate` | 固定 `null` | 当前不从游戏提取发布时间。 |
| `packs` | `PackMasterTable` 顶层 pack 列表，按 `SkuID` 派生 expansion | 只保留 `PackID` 包含 `_00_000` 的普通包；不从 cards.extra 的 `packs` 字段反推。 |

## `packs` 注意点

`sets.json` 的 `packs` 表示系列发布时的子包列表，不是“这个系列下所有卡牌可从哪些包获得”。

不能通过聚合同一 set 下所有 card 的 `packs` 得到 `sets.json.packs`，原因：

- 同一张卡可能同时属于多个 expansion。
- 例如 A1 的卡可能在 A1a 中再次出现。
- cards.extra 的单卡 `packs` 表示该卡的所有获取来源，因此 A1 某张卡的 `packs` 可能出现 A1a 的 pack name。
- 如果从 cards 反推 set 的 packs，会把其他 expansion 的子包错误混入当前 set。

正确来源：frida-test exporter 输出的 top-level `packs`。每条记录来自 `MemoryDatabase.PackMasterTable`，`expansionId` 由 `SkuID.split("_")[0]` 派生。`sets.json.packs` 生成时按当前 set code 筛选 `expansionId`，再只保留 `PackID` 含 `_00_000` 的普通包。

PROMO 类系列如果没有 top-level PackMaster row，`packs` 输出空数组；即使卡牌自身 `packs` 有值，也不从 cards.extra 补。

## 校验脚本

```bash
uv run python scripts/verify_metadata_coverage.py sets
```

sets 对比口径：

- 按 `code` 对齐。
- 本地产物多出的 set 只计数。
- 本地产物缺少 baseline set 时输出 `code`、`name`。
- `releaseDate` 不比较；当前固定输出 `null`。
- `count` 不比较；卡牌数量以游戏 `MemoryDatabase` 为准。
- `packs` 非 PROMO 系列只比较列表长度；`PROMO-*` 系列 packs 数量以游戏 `MemoryDatabase` 为准，不比较 baseline 数量。
- `name` 不比较字符串内容，只要求本地产物存在至少一个非空本地化值。
- 字段差异输出中的 `baselineName` / `candidateName` 只用于定位对象，不代表 `name` 字符串参与比较。
