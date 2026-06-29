# scripts 使用说明

本目录主要给新用户使用两类更新脚本：

- `update_metadata.py`：从运行中的游戏导出卡牌与卡包 metadata。
- `update_pack_images.py`：从 PTCGP bridge 导出卡包图片，生成全语言 WebP。

## 前置条件

- 使用 `uv` 运行 Python 脚本。
- 游戏需要在模拟器中启动，并进入主页。
- `frida-test` 需要能连接目标设备，并已准备好 `frida-server`。
- 如果要更新图片，本地需要能看到 `images/`，不要把 `images/` 从 sparse checkout 中排除。

## 更新 metadata

用途：生成或更新：

```text
metadata/cards/<language>/cards.extra.json
metadata/sets/<language>/sets.json
```

运行：

```bash
uv run python scripts/update_metadata.py --frida-test-dir ../frida-test
```

说明：

- `--frida-test-dir` 指向本地 `frida-test` 仓库。
- 脚本会调用 `frida-test` 的 `ptcgp export-metadata`。
- 如果游戏刚启动还没进主页，脚本可能提示稍后重试；先让游戏进入主页再跑。

## 更新卡包图片

用途：生成或更新：

```text
images/<language>/packs/<skuId>.webp
images/<language>/packs-logos/<skuId>.webp
```

先在 `frida-test` 启动 bridge：

```bash
npx tsx src/cli/index.ts frida prepare --serial 127.0.0.1:5645
npx tsx src/cli/index.ts ptcgp bridge --serial 127.0.0.1:5645 --port 8765
```

再在本仓库运行：

```bash
uv run python scripts/update_pack_images.py --bridge-url http://127.0.0.1:8765 --output .
```

默认行为：

- 导出全部普通包。
- 生成所有支持语言。
- 卡包本体图输出为 `160x256`。
- 卡包 logo 保留游戏资源原尺寸。
- 脚本按小批次请求 bridge，避免一次性传输过大导致 Frida RPC 断开。

调试单个卡包：

```bash
uv run python scripts/update_pack_images.py \
  --bridge-url http://127.0.0.1:8765 \
  --sku-id A1_1 \
  --output /tmp/ptcgp-pack-check
```

## 常用检查

统计输出数量：

```bash
find images -path '*/packs/*.webp' -type f | wc -l
find images -path '*/packs-logos/*.webp' -type f | wc -l
```

抽查图片尺寸：

```bash
uv run python - <<'PY'
from pathlib import Path
from PIL import Image
for path in [
    Path('images/en-US/packs/A1_1.webp'),
    Path('images/en-US/packs-logos/A1_1.webp'),
    Path('images/zh-TW/packs/A1_1.webp'),
    Path('images/zh-TW/packs-logos/A1_1.webp'),
]:
    image = Image.open(path).convert('RGBA')
    print(path, image.size, image.getchannel('A').getbbox())
PY
```

## 其他脚本

`verify_metadata_coverage.py` 用于校验 metadata 覆盖情况，不是日常更新入口。

## 生成卡牌感知哈希

用途：为每张卡牌预计算感知哈希 JSON，供 ptcgp-auto 游戏端拉取，避免新用户下载全量卡图本地算哈希。

输出：

```text
hashes/<locale>/<set_code>.json
```

JSON 格式：

```json
{
  "_algo_version": "v1",
  "cards": { "1": "<base64_hash>", "2": "<base64_hash>" }
}
```

运行（默认处理 zh-TW 全系列）：

```bash
just generate-hashes
# 或指定单系列
just generate-hashes-set A1
```

前置：本地需检出 `images/`（非 sparse 排除模式），且 `uv sync` 已装 numpy/scipy。

**修改算法必须同步游戏端并更新 `ALGO_VERSION`**，并跑一致性测试：

```bash
PTCGP_AUTO_SRC=/path/to/ptcgp-auto/src \
  /path/to/ptcgp-auto/.venv/bin/python -m pytest tests/test_hashes.py
```

测试会比对 assets 端内联算法与游戏端 `perceptual_hash.py` 的产出，防止两份代码漂移。
