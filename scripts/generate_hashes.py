#!/usr/bin/env python3
"""
生成卡牌感知哈希 JSON

遍历 images/<locale>/cards-by-set/<set_code>/<number>.<ext>，为每张卡牌计算
感知哈希，输出 hashes/<locale>/<set_code>.json。

游戏端 (ptcgp-auto) 优先拉取这些 JSON 入库，避免新用户下载几个 G 的卡图
本地算哈希。本脚本内联的哈希算法与游戏端 src/ptcgp_auto_v2/utils/perceptual_hash.py
保持一致（DCT 感知哈希，HASH_SIZE=96，FREQ_SIZE=8），由 tests/test_hashes.py
保证不漂移。

JSON 格式:
{
  "_algo_version": "v1",
  "cards": {
    "1": "<base64_hash>",
    "2": "<base64_hash>"
  }
}

key 为卡牌编号（不补零，与 images 文件名及数据库 cards.number 对齐）。
"""

import argparse
import base64
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
from PIL import Image
from tqdm import tqdm

# ============ 感知哈希算法（与游戏端 perceptual_hash.py 一致） ============
# 修改任一常量或算法步骤，必须同步游戏端并更新 _ALGO_VERSION。
ALGO_VERSION = "v1"
HASH_SIZE = 96  # 预处理后的图片尺寸
FREQ_SIZE = 8  # DCT 频率尺寸


@dataclass
class ColorPixels:
    """颜色像素数据"""

    r: List[int]
    g: List[int]
    b: List[int]


def pil_to_color_pixels(pil_image: Image.Image) -> ColorPixels:
    """从 PIL Image 转换为 ColorPixels：去 Alpha + resize(cubic) + 取 RGB"""
    if pil_image.mode == "RGBA":
        pil_image = pil_image.convert("RGB")
    elif pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")

    pil_image = pil_image.resize((HASH_SIZE, HASH_SIZE), Image.Resampling.BICUBIC)

    rgb = np.array(pil_image)

    color_pixels = ColorPixels(
        r=[0] * (HASH_SIZE * HASH_SIZE),
        g=[0] * (HASH_SIZE * HASH_SIZE),
        b=[0] * (HASH_SIZE * HASH_SIZE),
    )

    flat = rgb.reshape(-1, 3)
    for idx, (r, g, b) in enumerate(flat):
        color_pixels.r[idx] = int(r)
        color_pixels.g[idx] = int(g)
        color_pixels.b[idx] = int(b)

    return color_pixels


def _compute_dct(pixels: List[int]) -> List[float]:
    """计算二维 DCT，取左上 FREQ_SIZE×FREQ_SIZE 低频系数"""
    from scipy.fftpack import dct

    n = int(np.sqrt(len(pixels)))
    if n * n != len(pixels):
        raise ValueError("像素长度不是平方数")

    img = np.array(pixels, dtype=np.float32).reshape(n, n)
    dct_rows = dct(img, type=2, norm="ortho", axis=0)
    dct_2d = dct(dct_rows, type=2, norm="ortho", axis=1)
    return dct_2d[:FREQ_SIZE, :FREQ_SIZE].flatten().tolist()


def calculate_perceptual_hash(color_pixels: ColorPixels) -> np.ndarray:
    """计算感知哈希，返回 uint32 数组"""
    dct_r = _compute_dct(color_pixels.r)
    dct_g = _compute_dct(color_pixels.g)
    dct_b = _compute_dct(color_pixels.b)

    total_bits = 3 * (len(dct_r) - 1)
    buffer_len = int(np.ceil(total_bits / 32))
    arr = np.zeros(buffer_len, dtype=np.uint32)

    j = 0
    for channel_dct in (dct_r, dct_g, dct_b):
        avg = float(np.mean(channel_dct[1:]))
        for i in range(1, len(channel_dct)):
            if channel_dct[i] > avg + 1e-15:
                idx = j // 32
                bit = j % 32
                arr[idx] |= np.uint32(1 << bit)
            j += 1

    return arr


def encode_hash_to_base64(hash_arr: np.ndarray) -> str:
    """将哈希数组编码为 Base64 字符串（与游戏端编码一致）"""
    return base64.b64encode(hash_arr.tobytes()).decode("utf-8")


# ============ 生成逻辑 ============

REPO_ROOT = Path(__file__).resolve().parent.parent
# 游戏端扫描默认走 zh-TW 卡图（zh_Hant -> zh_CN -> zh-TW），hash 同源
DEFAULT_LOCALE = "zh-TW"
CARD_IMAGE_EXTS = (".png", ".webp", ".jpg")


def discover_sets(cards_dir: Path) -> List[str]:
    """发现 cards-by-set 下所有含卡图的 set 目录"""
    if not cards_dir.exists():
        return []
    sets = []
    for item in sorted(cards_dir.iterdir()):
        if item.is_dir() and any(
            item.glob(f"*{ext}") for ext in CARD_IMAGE_EXTS
        ):
            sets.append(item.name)
    return sets


def generate_set_hashes(set_dir: Path, output_path: Path) -> tuple[int, int]:
    """为单个 set 生成哈希 JSON

    Returns:
        (success_count, fail_count)
    """
    set_code = set_dir.name

    card_files = []
    for ext in CARD_IMAGE_EXTS:
        card_files.extend(set_dir.glob(f"*{ext}"))
    # 按编号排序，输出更稳定
    card_files = sorted(card_files, key=lambda p: int(p.stem))

    cards: dict[str, str] = {}
    success = 0
    fail = 0

    for card_file in tqdm(card_files, desc=f"{set_code}", unit="张"):
        number = card_file.stem
        try:
            pil_img = Image.open(card_file)
            color_pixels = pil_to_color_pixels(pil_img)
            hash_arr = calculate_perceptual_hash(color_pixels)
            cards[number] = encode_hash_to_base64(hash_arr)
            success += 1
        except Exception as e:
            print(f"❌ {set_code}/{number}: {e}", file=sys.stderr)
            fail += 1

    payload = {"_algo_version": ALGO_VERSION, "cards": cards}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return success, fail


def main():
    parser = argparse.ArgumentParser(description="生成卡牌感知哈希 JSON")
    parser.add_argument(
        "--locale",
        default=DEFAULT_LOCALE,
        help=f"卡图 locale 目录名（默认 {DEFAULT_LOCALE}）",
    )
    parser.add_argument(
        "--set",
        help="只处理指定 set（如 A1），不指定则处理全部",
    )
    args = parser.parse_args()

    cards_root = REPO_ROOT / "images" / args.locale / "cards-by-set"
    if not cards_root.exists():
        print(f"❌ 卡图目录不存在: {cards_root}", file=sys.stderr)
        print("💡 请确认 images/ 已检出（非 sparse 排除模式）", file=sys.stderr)
        sys.exit(1)

    output_root = REPO_ROOT / "hashes" / args.locale

    if args.set:
        set_dir = cards_root / args.set
        if not set_dir.exists():
            print(f"❌ set 目录不存在: {set_dir}", file=sys.stderr)
            sys.exit(1)
        sets = [args.set]
    else:
        sets = discover_sets(cards_root)
        if not sets:
            print(f"❌ {cards_root} 下未发现任何 set 目录", file=sys.stderr)
            sys.exit(1)

    print(f"发现 {len(sets)} 个 set: {', '.join(sets)}")
    print()

    total_success = 0
    total_fail = 0
    start = time.perf_counter()

    for set_code in sets:
        set_dir = cards_root / set_code
        output_path = output_root / f"{set_code}.json"
        success, fail = generate_set_hashes(set_dir, output_path)
        total_success += success
        total_fail += fail
        print(f"  {set_code}: {success} 成功, {fail} 失败 -> {output_path.relative_to(REPO_ROOT)}")

    elapsed = time.perf_counter() - start
    print()
    print(f"✅ 完成: {total_success} 成功, {total_fail} 失败, 耗时 {elapsed:.1f}s")


if __name__ == "__main__":
    main()
