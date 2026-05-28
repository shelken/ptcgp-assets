import json
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.update_cards_extra import convert_export, parse_exporter_stdout, run_exporter, write_cards_extra


class UpdateCardsExtraTests(unittest.TestCase):
    def test_converts_pokemon_and_fossil_to_flibustier_compatible_shape(self):
        export = {
            "schemaVersion": 1,
            "language": "zh-TW",
            "cards": [
                {
                    "kind": "pokemon",
                    "set": "A1",
                    "number": 1,
                    "name": "妙蛙種子",
                    "rarity": "C",
                    "image": "cPK_10_000010_00_FUSHIGIDANE_C.webp",
                    "packs": ["超夢", "高級擴充包ex"],
                    "pokemon": {
                        "element": "Grass",
                        "stage": "Basic",
                        "health": 70,
                        "retreatCost": 1,
                        "weakness": "Fire",
                        "evolvesFrom": None,
                    },
                },
                {
                    "kind": "trainer",
                    "set": "A1",
                    "number": 216,
                    "name": "貝殼化石",
                    "rarity": "C",
                    "image": "cTR_10_000080_00_KAINOKASEKI_C.webp",
                    "packs": ["皮卡丘"],
                    "trainer": {"type": "Fossil"},
                },
            ],
        }

        self.assertEqual(
            convert_export(export),
            [
                {
                    "set": "A1",
                    "number": 1,
                    "name": "妙蛙種子",
                    "rarity": "C",
                    "image": "cPK_10_000010_00_FUSHIGIDANE_C.webp",
                    "packs": ["超夢", "高級擴充包ex"],
                    "element": "grass",
                    "type": "pokemon",
                    "stage": "basic",
                    "health": 70,
                    "retreatCost": 1,
                    "weakness": "Fire",
                    "evolvesFrom": None,
                },
                {
                    "set": "A1",
                    "number": 216,
                    "name": "貝殼化石",
                    "rarity": "C",
                    "image": "cTR_10_000080_00_KAINOKASEKI_C.webp",
                    "packs": ["皮卡丘"],
                    "type": "Fossil",
                    "stage": "basic",
                },
            ],
        )

    def test_preserves_exporter_pack_names_without_guessing_from_language(self):
        export = {
            "schemaVersion": 1,
            "language": "en-US",
            "cards": [
                {
                    "kind": "trainer",
                    "set": "A4b",
                    "number": 1,
                    "name": "Example",
                    "rarity": "C",
                    "image": "example.webp",
                    "packs": ["Deluxe Pack ex"],
                    "trainer": {"type": "Item"},
                }
            ],
        }

        [card] = convert_export(export)

        self.assertEqual(card["packs"], ["Deluxe Pack ex"])

    def test_parses_exporter_stdout_with_leading_tool_noise(self):
        export = {"schemaVersion": 1, "language": "zh-TW", "cards": []}
        stdout = "◇ injected env (8) from .env\n" + json.dumps(export, ensure_ascii=False)

        self.assertEqual(parse_exporter_stdout(stdout, "", "tsx ptcgp export-metadata"), export)

    def test_parse_error_includes_stdout_and_stderr_preview(self):
        with self.assertRaisesRegex(ValueError, "stdout preview: not json"):
            parse_exporter_stdout(
                "not json",
                "Error: Expected one MemoryDatabase instance, got 0",
                "tsx ptcgp export-metadata",
            )

    def test_rejects_duplicate_set_number(self):
        export = {
            "schemaVersion": 1,
            "language": "zh-TW",
            "cards": [
                {
                    "kind": "trainer",
                    "set": "A1",
                    "number": 1,
                    "name": "A",
                    "rarity": "C",
                    "image": "a.webp",
                    "packs": [],
                    "trainer": {"type": "Item"},
                },
                {
                    "kind": "trainer",
                    "set": "A1",
                    "number": 1,
                    "name": "B",
                    "rarity": "C",
                    "image": "b.webp",
                    "packs": [],
                    "trainer": {"type": "Item"},
                },
            ],
        }

        with self.assertRaisesRegex(ValueError, "duplicate card key: A1 #1"):
            convert_export(export)

    def test_run_exporter_fails_fast_on_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}")
            (root / "src/cli").mkdir(parents=True)
            (root / "src/cli/index.ts").write_text("")

            with patch("scripts.update_cards_extra.subprocess.run") as run:
                run.side_effect = subprocess.TimeoutExpired(
                    cmd="tsx ptcgp export-metadata",
                    timeout=120,
                    output="partial stdout",
                    stderr="partial stderr",
                )

                with self.assertRaisesRegex(TimeoutError, "timed out after 120s"):
                    run_exporter(root)

    def test_writes_to_language_directory_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = write_cards_extra(
                Path(tmp),
                "zh-TW",
                [{"set": "A1", "number": 1, "name": "妙蛙種子"}],
            )

            self.assertEqual(output, Path(tmp) / "metadata/cards/zh-TW/cards.extra.json")
            self.assertEqual(
                json.loads(output.read_text()),
                [{"set": "A1", "number": 1, "name": "妙蛙種子"}],
            )


if __name__ == "__main__":
    unittest.main()
