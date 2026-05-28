import json
import tempfile
import unittest
from pathlib import Path

from scripts.update_cards_extra import convert_export, parse_exporter_stdout, write_cards_extra


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
                    "packs": ["最強的基因 超夢", "高級擴充包ex"],
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
                    "packs": ["最強的基因 皮卡丘"],
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

    def test_keeps_english_deluxe_pack_ex_name(self):
        export = {
            "schemaVersion": 1,
            "language": "en-US",
            "cards": [
                {
                    "kind": "pokemon",
                    "set": "A1",
                    "number": 1,
                    "name": "Bulbasaur",
                    "rarity": "C",
                    "image": "cPK_10_000010_00_FUSHIGIDANE_C.webp",
                    "packs": ["Genetic Apex Mewtwo", "Deluxe Pack ex"],
                    "pokemon": {
                        "element": "Grass",
                        "stage": "Basic",
                        "health": 70,
                        "retreatCost": 1,
                        "weakness": "Fire",
                        "evolvesFrom": None,
                    },
                }
            ],
        }

        [card] = convert_export(export)

        self.assertEqual(card["packs"], ["Mewtwo", "Deluxe Pack ex"])

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
