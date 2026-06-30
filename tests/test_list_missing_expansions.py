import unittest
from pathlib import Path

from scripts.list_missing_expansions import (
    discover_repo_expansions,
    find_missing_expansions,
)


class FindMissingExpansionsTest(unittest.TestCase):
    def test_returns_game_expansions_not_in_repo(self) -> None:
        game = ["A1", "A1a", "A2", "B3b"]
        repo = ["A1", "A1a", "A2"]
        missing = find_missing_expansions(game, repo)
        self.assertEqual(missing, ["B3b"])

    def test_returns_empty_when_repo_has_all_game_series(self) -> None:
        game = ["A1", "B3b"]
        repo = ["A1", "B3b", "PROMO-A"]
        self.assertEqual(find_missing_expansions(game, repo), [])

    def test_preserves_game_order_and_skips_repo_only_series(self) -> None:
        # repo 多出的系列（如 PROMO-A 不在游戏列表）不影响结果
        game = ["B3a", "B3b"]
        repo = ["A1", "B3a", "PROMO-X"]
        self.assertEqual(find_missing_expansions(game, repo), ["B3b"])


class DiscoverRepoExpansionsTest(unittest.TestCase):
    def test_returns_sorted_dir_names_under_cards_by_set(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sets_dir = root / "images" / "zh-TW" / "cards-by-set"
            sets_dir.mkdir(parents=True)
            (sets_dir / "B3b").mkdir()
            (sets_dir / "A1").mkdir()
            (sets_dir / "A1a").mkdir()
            # 非目录文件应被忽略
            (sets_dir / "README.txt").write_text("ignore")

            result = discover_repo_expansions(root, "zh-TW")
            self.assertEqual(result, ["A1", "A1a", "B3b"])

    def test_returns_empty_when_sets_dir_missing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = discover_repo_expansions(Path(tmp), "zh-TW")
            self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
