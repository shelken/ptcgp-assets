# cards.extra metadata

本目录存放从运行中的 PTCGP 游戏导出的卡牌 metadata。

## 文件

```text
metadata/cards/<language>/cards.extra.json
```

当前已生成：

```text
metadata/cards/zh-TW/cards.extra.json
```

## 数据准则

- 游戏 `MemoryDatabase` 是事实来源。
- 与 flibustier 原版不一致时，以本目录产物为准。
- flibustier 原版只作为结构和历史格式参考，不作为数值真值。
- `name`、`packs` 使用当前游戏语言。
- 同一张卡如果同时属于普通卡包和高级扩充包，`packs` 会同时列出；这是正确数据。
- Pokémon 的 `evolvesFrom` 一律保留；没有进化来源时写 `null`。
- 本轮不生成 `goodWith`。

## 枚举字段

| 输出 key | 输出值 | 游戏来源 / 规则 | 说明 |
| --- | --- | --- | --- |
| `rarity` | `C`, `U`, `R`, `RR`, `AR`, `SA`, `SAR`, `SSA`, `SR`, `IM`, `S`, `SSR`, `UR` | `PokemonCard.Rarity` / `TrainerCard.Rarity` | 游戏 enum 还可能有 `UNSPECIFIED`，正式输出不应出现。当前产物实际出现：`C`, `U`, `R`, `RR`, `AR`, `SAR`, `SR`, `IM`, `S`, `SSR`, `UR`。 |
| `element` | `grass`, `fire`, `water`, `lightning`, `psychic`, `fighting`, `darkness`, `metal`, `dragon`, `colorless` | `Pokemon.PokemonTypes[0]`，转小写 | 完全按当前产物格式；不跟随 flibustier 后期出现的首字母大写写法。 |
| `type` | `pokemon`, `supporter`, `item`, `tool`, `Fossil`, `stadium` | Pokémon 固定 `pokemon`；Trainer 来自 `Trainer.TrainerType` 映射 | `Fossil` 保持大写，兼容原版常见写法。`PokemonTool` 输出为 `tool`。 |
| `stage` | `basic`, `1`, `2` | `Pokemon.EvolutionStage` 映射 | `Basic -> basic`，一阶输出数字 `1`，二阶输出数字 `2`。不使用 flibustier 后期局部出现的 `0`。 |
| `weakness` | `Fire`, `Water`, `Lightning`, `Psychic`, `Fighting`, `Darkness`, `Metal`, `Grass`, `UNSPECIFIED`, `null` | `Pokemon.WeaknessType` | 不做 `Darkness -> Dark` 映射；按当前游戏 enum / candidate 产物为准。 |

## TrainerType 映射

| 游戏 `TrainerType` | 输出 `type` |
| --- | --- |
| `Supporter` | `supporter` |
| `Item` | `item` |
| `PokemonTool` | `tool` |
| `Fossil` | `Fossil` |
| `Stadium` | `stadium` |
| `UNSPECIFIED` | 不应输出 |

## 校验脚本

```bash
uv run python scripts/verify_cards_extra_parent.py
```

脚本会把 flibustier 原版下载到：

```text
/tmp/cards.extra.json
```

对比口径：

- 按 `(set, number)` 对齐。
- 本目录产物多出的卡只计数。
- 本目录产物缺少原版卡时输出 `set`、`number`、`name`。
- list 只比较长度。
- number 比较数值。
- enum string 会输出差异，但差异不代表本目录产物错误；当前规则以游戏导出的 candidate 为准。
- `name`、`image`、`evolvesFrom` 等非 enum string 不比较字符串值。
