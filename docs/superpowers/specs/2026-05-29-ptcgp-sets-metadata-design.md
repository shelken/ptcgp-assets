# PTCGP sets metadata 自动更新设计

## 目标

在现有 cards.extra 自动更新链路上，同步生成 `sets.json`，让 ptcgp-auto 后续可以从 ptcgp-assets 拉取系列 metadata，替代 flibustier `dist/sets.json`。

最终产物：

```text
metadata/sets/<language>/sets.json
```

例如：

```text
metadata/sets/en-US/sets.json
metadata/sets/zh-TW/sets.json
```

本轮不提取发布日期；`releaseDate` 固定写 `null`。

## 边界

职责边界保持不变：

```text
frida-test = 设备 / Frida / IL2CPP / MemoryDatabase raw exporter
ptcgp-assets = 调用 exporter / 转换 JSON / 校验 / 落盘
ptcgp-auto = 消费 ptcgp-assets JSON 并写入本地数据库
```

不做：

- 不让 ptcgp-assets import frida-test 内部 TypeScript 模块
- 不让 frida-test 输出 flibustier 格式
- 不从 flibustier baseline 填充 name、count 或 releaseDate
- 不提交 raw exporter JSON
- 不新增独立 verify 脚本文件
- 不新增兼容 wrapper；脚本改名后直接更新调用方

## 数据来源

frida-test 当前 raw exporter 已输出 sets 所需数据：

```text
schemaVersion
language
expansions
cards
```

关键 raw 字段：

```text
expansions[].expansionId
expansions[].nameMSID
expansions[].longNameMSID
expansions[].names
cards[].set
cards[].packs
```

`expansions` 来自游戏 `MemoryDatabase` 的 `ExpansionTable`，名称来自 `LocalizeMasterExpansionName`。

`count` 不读额外表字段，直接从 raw card rows 按 `set` 聚合。这样与最终 cards.extra 输出使用同一张卡集合，避免两个来源不一致。

`packs` 复用现有 pack 显示名逻辑：只保留普通包，使用现有 `display_pack_name()` / `display_pack_name` 相关上下文处理 FeaturedCardIDs、扩充包名前缀和富文本名称。

## 输出格式

输出兼容 flibustier `dist/sets.json` 顶层结构：

```json
{
  "A": [
    {
      "code": "A1",
      "releaseDate": null,
      "count": 286,
      "name": { "en": "Genetic Apex" },
      "packs": ["Charizard", "Mewtwo", "Pikachu"]
    }
  ],
  "B": []
}
```

字段规则：

| 字段 | 规则 |
| --- | --- |
| `code` | expansion id；只输出至少有卡牌的 expansion |
| `releaseDate` | 固定 `null` |
| `count` | 从 converted cards 按 `set` 聚合数量 |
| `name` | 对象格式，key 使用 flibustier 短语言 key |
| `packs` | 按 set 聚合 normal pack display names，去重后稳定排序 |

顶层分组：

- 用 `code[0]` 分组，例如 `A1/A1a -> A`，`B1 -> B`
- 组内按自然顺序排序，避免纯字符串排序导致 `A10` 排在 `A2` 前

## 语言 key 映射

`name` 必须保持对象格式，兼容 ptcgp-auto 现有 `label_data` 逻辑。

映射规则：

| runtime language | output key |
| --- | --- |
| `en-US` | `en` |
| `zh-TW` | `zh` |
| `zh-CN` | `zh` |
| `ja-JP` | `ja` |
| `ko-KR` | `ko` |
| `fr-FR` | `fr` |
| `de-DE` | `de` |
| `es-ES` | `es` |
| `it-IT` | `it` |
| `pt-BR` | `pt` |

遇到未映射语言时 fail-fast，不输出猜测 key。

名称值优先级：

```text
LongNameMSID 本地化值 -> NameMSID 本地化值 -> fail-fast
```

不从 flibustier baseline 继承其他语言名。当前运行语言生成当前语言的 name key；后续可通过切换模拟器语言多次生成所有语言文件。

## ptcgp-assets 改动

重命名现有脚本：

```text
scripts/update_cards_extra.py -> scripts/update_metadata.py
tests/test_update_cards_extra.py -> tests/test_update_metadata.py
scripts/verify_cards_extra_parent.py -> scripts/verify_metadata_coverage.py
tests/test_verify_cards_extra_parent.py -> tests/test_verify_metadata_coverage.py
```

`update_metadata.py` 执行流程：

```text
1. 检查 --frida-test-dir
2. 执行 frida-test ptcgp export-metadata --out -
3. 解析 raw exporter JSON
4. 转换 cards.extra.json
5. 转换 sets.json
6. 原子写 metadata/cards/<language>/cards.extra.json
7. 原子写 metadata/sets/<language>/sets.json
```

主要函数：

```text
convert_cards_extra(export) -> list[dict]
convert_sets(export, cards) -> dict[str, list[dict]]
write_cards_extra(root, language, cards) -> Path
write_sets(root, language, sets) -> Path
```

`convert_cards_extra()` 可由现有 `convert_export()` 改名而来，避免脚本名和函数名继续只描述 cards.extra。

更新：

```text
justfile
metadata/cards/README.md
```

README 需要说明：同一 exporter 产出 cards.extra 与 sets，验证脚本改为 metadata coverage。

## 覆盖验证

验证脚本改名为：

```text
scripts/verify_metadata_coverage.py
```

命令：

```bash
uv run python scripts/verify_metadata_coverage.py cards-extra
uv run python scripts/verify_metadata_coverage.py sets
```

`coverage` 含义：本地产物 candidate 必须覆盖 flibustier baseline。不是完全相等。

### cards-extra 验证

迁移现有逻辑，不改变比较语义：

- 按 `(set, number)` 对齐
- candidate 多出的卡只计数
- baseline 有而 candidate 缺失则失败
- 游戏权威字段忽略：`packs`, `element`, `stage`, `health`, `retreatCost`, `weakness`, `evolvesFrom`, `goodWith`
- list 只比较长度
- number 必须相等
- enum string 只比较 `rarity`, `type`
- 普通 string 不比较内容

### sets 验证

baseline：

```text
https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/sets.json
```

candidate 默认：

```text
metadata/sets/en-US/sets.json
```

规则：

- 扁平化顶层分组后按 `code` 对齐
- baseline set 必须存在
- candidate 多出的 set 只计数
- duplicate set code 失败
- `releaseDate` 忽略，因为本地产物固定 `null`
- `count` 是 number，必须相等
- `packs` 是 list，只比较长度
- `name` 是 object；不比较本地化字符串内容，只要求 candidate 有至少一个非空 name 值
- `code` 作为主键，不作为普通字段重复比较

## ptcgp-auto 改动

改动范围只限 metadata sync service：

```text
src/ptcgp_auto_v2/services/metadata_sync/flibustier_sync_service.py
```

调整 URL：

```text
SETS_URL -> https://raw.githubusercontent.com/shelken/ptcgp-assets/main/metadata/sets/en-US/sets.json
CARDS_URL -> 仍使用 flibustier dist/cards.json
CARDS_EXTRA_URL -> 继续使用 ptcgp-assets cards.extra.json
```

调整 set name fallback：

```text
en -> zh -> first non-empty string -> code
```

保留现有行为：

```text
label_dict.update(incoming_name)
```

这样 `label_data` 仍存完整 name object。中文 UI 继续优先读 `zh`，英文 UI 继续优先读 `en`；如果后续某个语言文件缺 `en/zh`，也不会退化成 set code。

不改数据库结构，不改 Web API，不改 cards.json 来源。

## 错误处理

保持 fail-fast：

- raw exporter `schemaVersion` 不是 `2`：失败
- `language` 不能映射到短 key：失败
- expansion 没有可用 name：失败
- pack/name 里出现替换字符 `�`：失败
- duplicate set code：失败
- duplicate card key：沿用现有失败
- baseline 需要的 set 在 candidate 中缺失：验证失败

不做静默 fallback，不吞 exporter 错误。

## 测试计划

ptcgp-assets 单元测试：

```bash
uv run pytest tests/test_update_metadata.py tests/test_verify_metadata_coverage.py
```

覆盖：

- cards.extra 原测试全部迁移通过
- `convert_sets()` 输出 grouped dict
- `releaseDate` 为 `null`
- `count` 从 cards 聚合
- `packs` 聚合并去重
- `name` 使用 runtime language short key
- `write_sets()` 路径正确
- sets coverage：缺 set 失败、extra set 计数、`count` 不同失败、`packs` 长度不同失败、`releaseDate` 不比较、`name` 只要求非空值

ptcgp-assets 覆盖验证：

```bash
uv run python scripts/verify_metadata_coverage.py cards-extra
uv run python scripts/verify_metadata_coverage.py sets
```

ptcgp-auto 精准验证：

```bash
uv run ruff check src/ptcgp_auto_v2/services/metadata_sync/flibustier_sync_service.py
```

如果现有 metadata sync 单测覆盖 URL 或 set fallback，更新并运行对应测试。

## 执行顺序

1. 在 ptcgp-assets 改名 update / verify 脚本和测试文件
2. 在 update 脚本中拆分 `convert_cards_extra()`，新增 `convert_sets()` / `write_sets()`
3. 更新 justfile 和 metadata README
4. 实现 coverage 脚本的 `cards-extra` / `sets` 子命令
5. 跑 ptcgp-assets 单元测试
6. 生成或复用 en-US sets.json 后跑 coverage 验证
7. 在 ptcgp-auto 切 `SETS_URL` 并增强 set name fallback
8. 跑 ptcgp-auto 精准 lint / 单测
