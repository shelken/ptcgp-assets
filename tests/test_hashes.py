"""感知哈希算法一致性测试

保证 ptcgp-assets 的 scripts/generate_hashes.py 内联算法与游戏端
ptcgp-auto 的 src/ptcgp_auto_v2/utils/perceptual_hash.py 算法产出完全一致。

两份代码是同一算法的独立拷贝（方案 A），靠本测试防止漂移。
任一方改动算法，本测试会失败，必须同步另一边并更新 ALGO_VERSION。

前置：
- 游戏端 ptcgp-auto 仓库本地路径，通过环境变量 PTCGP_AUTO_SRC 指向其 src 目录
  （默认 ../ptcgp-auto/src，相对本仓库根）。
- 运行环境需有游戏端依赖（cv2/scipy/numpy/PIL），建议在游戏端 venv 中运行：
    PTCGP_AUTO_SRC=/path/to/ptcgp-auto/src \
      /path/to/ptcgp-auto/.venv/bin/python -m pytest tests/test_hashes.py
  或用 unittest：
    PTCGP_AUTO_SRC=/path/to/ptcgp-auto/src \
      /path/to/ptcgp-auto/.venv/bin/python -m unittest tests.test_hashes
"""

import json
import os
import sys
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_hashes import (  # noqa: E402
    ALGO_VERSION,
    calculate_perceptual_hash,
    encode_hash_to_base64,
    pil_to_color_pixels,
)

# 卡图样本目录（取 zh-TW/A1 前几张）
SAMPLE_DIR = REPO_ROOT / "images" / "zh-TW" / "cards-by-set" / "A1"
# 生成产物
HASH_JSON = REPO_ROOT / "hashes" / "zh-TW" / "A1.json"


def _load_game_side_perceptual_hash():
    """动态加载游戏端算法，失败则跳过测试"""
    game_src = os.environ.get("PTCGP_AUTO_SRC")
    if not game_src:
        # 默认相对路径：与 ptcgp-auto 同级或在其旁边的常见布局
        default = REPO_ROOT.parent / "ptcgp-auto" / "src"
        if default.exists():
            game_src = str(default)

    if not game_src or not Path(game_src).exists():
        return None

    sys.path.insert(0, str(game_src))
    # 强制重新导入，避免与 assets 端同名函数混淆
    import importlib

    mod = importlib.import_module("ptcgp_auto_v2.utils.perceptual_hash")
    return mod


class TestHashConsistency(unittest.TestCase):
    """assets 端与游戏端算法一致性"""

    @classmethod
    def setUpClass(cls):
        cls.game_mod = _load_game_side_perceptual_hash()
        if cls.game_mod is None:
            raise unittest.SkipTest(
                "未找到游戏端 ptcgp-auto src，设置 PTCGP_AUTO_SRC 环境变量指向其 src 目录"
            )
        if not SAMPLE_DIR.exists():
            raise unittest.SkipTest(f"卡图样本目录不存在: {SAMPLE_DIR}")

    def _sample_files(self, n=5):
        files = sorted(SAMPLE_DIR.glob("*.png"), key=lambda p: int(p.stem))[:n]
        self.assertTrue(files, "没有可用的样本卡图")
        return files

    def test_algorithm_constants_match(self):
        """常量必须一致"""
        self.assertEqual(self.game_mod.HASH_SIZE, 96)
        self.assertEqual(self.game_mod.FREQ_SIZE, 8)

    def test_single_card_hash_identical(self):
        """单张卡图两端算出的 base64 hash 必须完全相同"""
        game_ph = self.game_mod
        for card_file in self._sample_files():
            with self.subTest(card=card_file.name):
                img = Image.open(card_file)

                assets_cp = pil_to_color_pixels(img)
                assets_hash = encode_hash_to_base64(calculate_perceptual_hash(assets_cp))

                # PIL Image 已被 assets 端 resize 改变，重新打开给游戏端
                img2 = Image.open(card_file)
                game_cp = game_ph.pil_to_color_pixels(img2)
                game_hash = game_ph.encode_hash_to_base64(
                    game_ph.calculate_perceptual_hash(game_cp)
                )

                self.assertEqual(
                    assets_hash,
                    game_hash,
                    f"{card_file.name} 两端 hash 不一致，算法已漂移",
                )

    def test_generated_json_matches_game_side(self):
        """已生成的 hashes JSON 中每张卡的 hash 与游戏端实时计算一致"""
        if not HASH_JSON.exists():
            self.skipTest(f"未生成 {HASH_JSON}，先跑 just generate-hashes-set A1")

        game_ph = self.game_mod
        with open(HASH_JSON, encoding="utf-8") as f:
            payload = json.load(f)

        self.assertEqual(payload["_algo_version"], ALGO_VERSION)
        cards = payload["cards"]

        for card_file in self._sample_files():
            number = card_file.stem
            with self.subTest(card=number):
                self.assertIn(number, cards, f"{number} 不在生成的 JSON 中")

                img = Image.open(card_file)
                game_cp = game_ph.pil_to_color_pixels(img)
                game_hash = game_ph.encode_hash_to_base64(
                    game_ph.calculate_perceptual_hash(game_cp)
                )

                self.assertEqual(
                    cards[number],
                    game_hash,
                    f"A1/{number} JSON 中的 hash 与游戏端不一致",
                )


if __name__ == "__main__":
    unittest.main()
