import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.update_metadata import (
    GAME_LAUNCHED_MESSAGE,
    ExportDeferred,
    convert_cards_extra,
    convert_sets,
    main,
    parse_exporter_stdout,
    run_exporter,
    write_cards_extra,
    write_sets,
)


class CompletedProcess:
    def __init__(self, stdout: str, stderr: str, return_code: int) -> None:
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.return_code = return_code

    def wait(self, timeout: int | None = None) -> int:
        return self.return_code

    def kill(self) -> None:
        raise AssertionError("completed process should not be killed")


class TimeoutProcess:
    def __init__(self) -> None:
        self.stdout = io.StringIO("partial stdout")
        self.stderr = io.StringIO("partial stderr")
        self.waits = 0
        self.killed = False

    def wait(self, timeout: int | None = None) -> int:
        self.waits += 1
        if timeout is not None:
            raise subprocess.TimeoutExpired(cmd="tsx ptcgp export-metadata", timeout=timeout)
        return -9

    def kill(self) -> None:
        self.killed = True


def raw_export(
    cards: list[dict],
    *,
    expansions: list[dict] | None = None,
    localization_texts: dict[str, str] | None = None,
    packs: list[dict] | None = None,
):
    if packs is None:
        packs = []
        seen_pack_ids = set()
        for card in cards:
            for card_pack in card.get("packs", []):
                pack_id = card_pack.get("packId")
                if pack_id in seen_pack_ids:
                    continue
                seen_pack_ids.add(pack_id)
                packs.append(card_pack)

    return {
        "schemaVersion": 3,
        "language": "zh-TW",
        "localizationTexts": localization_texts or {},
        "expansions": expansions or [{"expansionId": "A1", "names": ["最強的基因"]}],
        "packs": packs,
        "cards": cards,
    }


def pack(pack_id: str, expansion_id: str, name: str, featured_card_ids: list[str] | None = None) -> dict:
    return {
        "packId": pack_id,
        "expansionId": expansion_id,
        "nameMSID": f"MSID_{pack_id}",
        "name": name,
        "featuredCardIds": featured_card_ids or [],
    }


def pokemon_card(
    *,
    set_id: str = "A1",
    number: int = 1,
    name: str = "妙蛙種子",
    card_id: str = "PK_10_000010",
    illustration_id: str = "cPK_10_000010_00_FUSHIGIDANE_C",
    packs: list[dict] | None = None,
    stage: str = "Basic",
    evolves_from: str | None = None,
    evolves_from_character_id: str | None = None,
) -> dict:
    return {
        "kind": "pokemon",
        "cardId": card_id,
        "set": set_id,
        "number": number,
        "name": name,
        "nameMSID": f"CARD_NAME_{number}",
        "characterId": f"CHAR_{number}",
        "rarity": "C",
        "illustrationId": illustration_id,
        "image": f"{illustration_id}.webp",
        "packs": packs or [],
        "pokemon": {
            "element": "Grass",
            "stage": stage,
            "health": 70,
            "retreatCost": 1,
            "weakness": "Fire",
            "evolvesFrom": evolves_from,
            "evolvesFromMSID": None,
            "evolvesFromCharacterId": evolves_from_character_id,
        },
    }


def trainer_card(*, packs: list[dict] | None = None) -> dict:
    return {
        "kind": "trainer",
        "cardId": "TR_10_000080",
        "set": "A1",
        "number": 216,
        "name": "貝殼化石",
        "nameMSID": "TRAINER_NAME_216",
        "characterId": "TRAINER_CHAR_216",
        "rarity": "C",
        "illustrationId": "cTR_10_000080_00_KAINOKASEKI_C",
        "image": "cTR_10_000080_00_KAINOKASEKI_C.webp",
        "packs": packs or [],
        "trainer": {"type": "Fossil"},
    }


class UpdateCardsExtraTests(unittest.TestCase):
    def test_converts_raw_pokemon_and_fossil_to_flibustier_compatible_shape(self):
        export = raw_export(
            [
                pokemon_card(
                    packs=[
                        pack("A1_MEWTWO_00_000", "A1", "最強的基因: 超夢"),
                        pack("A4b_EX_00_000", "A4b", "高級擴充包ex"),
                    ]
                ),
                trainer_card(packs=[pack("A1_PIKACHU_00_000", "A1", "最強的基因: 皮卡丘")]),
            ],
            expansions=[
                {"expansionId": "A1", "names": ["最強的基因"]},
                {"expansionId": "A4b", "names": ["A4b"]},
            ],
        )

        self.assertEqual(
            convert_cards_extra(export),
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

    def test_script_renders_card_rich_text_tokens(self):
        export = raw_export(
            [
                pokemon_card(
                    name='[Text:AdditionalName v="ADDITIONAL_NAME_Paldea" type="region"][Text:Char v="FOUR-PER-EM-SPACE"]Wooper',
                    stage="Stage1",
                    evolves_from='[Text:AdditionalName v="ADDITIONAL_NAME_Paldea" type="region"][Text:Char v="FOUR-PER-EM-SPACE"]Wooper',
                    evolves_from_character_id="CHAR_1",
                )
            ],
            localization_texts={"ADDITIONAL_NAME_Paldea": "Paldean"},
        )

        [card] = convert_cards_extra(export)

        self.assertEqual(card["name"], "Paldean Wooper")
        self.assertEqual(card["evolvesFrom"], "Paldean Wooper")

    def test_script_derives_multi_pack_names_from_featured_cards(self):
        export = raw_export(
            [
                pokemon_card(
                    set_id="B1",
                    number=1,
                    name="凱羅斯",
                    card_id="PK_10_010830",
                    illustration_id="cPK_10_010830_00_KAILIOS_C",
                    packs=[
                        pack("B1_BLAZIKEN_00_000", "B1", "Mega Rising: Mega Blaziken", ["PK_10_011180_00"]),
                        pack("B1_GYARADOS_00_000", "B1", "Mega Rising: Mega Gyarados", []),
                    ],
                ),
                pokemon_card(
                    set_id="B1",
                    number=300,
                    name="Mega Blaziken ex",
                    card_id="PK_10_011180",
                    illustration_id="cPK_10_011180_00_BURSYAMOex_RR",
                ),
            ],
            expansions=[{"expansionId": "B1", "names": ["Mega Rising"]}],
        )

        cards = convert_cards_extra(export)
        target = next(card for card in cards if card["number"] == 1)

        self.assertEqual(target["packs"], ["Mega Blaziken", "Mega Gyarados"])

    def test_script_keeps_single_pack_expansion_full_name(self):
        export = raw_export(
            [
                trainer_card(
                    packs=[pack("A4b_EX_00_000", "A4b", "Deluxe Pack: ex", ["PK_10_000010_00"])]
                )
            ],
            expansions=[{"expansionId": "A4b", "names": ["A4b"]}],
        )

        [card] = convert_cards_extra(export)

        self.assertEqual(card["packs"], ["Deluxe Pack ex"])

    def test_script_uses_clean_pack_name_for_corrupt_duplicate_source(self):
        export = raw_export(
            [
                pokemon_card(
                    number=1,
                    packs=[pack("A4a_UNKNOWN_00_000", "A4a", "未知水域")],
                ),
                pokemon_card(
                    number=2,
                    packs=[pack("A4a_UNKNOWN_00_000", "A4a", "未知���域")],
                ),
            ],
            expansions=[{"expansionId": "A4a", "names": ["A4a"]}],
        )

        cards = convert_cards_extra(export)

        self.assertEqual([card["packs"] for card in cards], [["未知水域"], ["未知水域"]])

    def test_script_uses_clean_card_name_for_corrupt_duplicate_source(self):
        export = raw_export(
            [
                pokemon_card(number=1, name="超夢", card_id="PK_10_001500", illustration_id="cPK_10_001500_00_MEWTWO_C"),
                pokemon_card(number=2, name="���夢", card_id="PK_10_001500", illustration_id="cPK_20_001500_00_MEWTWO_AR"),
            ]
        )

        cards = convert_cards_extra(export)

        self.assertEqual([card["name"] for card in cards], ["超夢", "超夢"])

    def test_rejects_corrupt_text_when_no_clean_source_exists(self):
        export = raw_export([pokemon_card(name="���夢")])

        with self.assertRaisesRegex(ValueError, "name contains replacement characters"):
            convert_cards_extra(export)

    def test_parses_exporter_stdout_with_leading_tool_noise(self):
        export = {"schemaVersion": 3, "language": "zh-TW", "cards": []}
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
        export = raw_export(
            [
                trainer_card(),
                {**trainer_card(), "name": "另一張"},
            ]
        )

        with self.assertRaisesRegex(ValueError, "duplicate card key: A1 #216"):
            convert_cards_extra(export)

    def test_run_exporter_fails_fast_on_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}")
            (root / "src/cli").mkdir(parents=True)
            (root / "src/cli/index.ts").write_text("")

            process = TimeoutProcess()
            with (
                patch("scripts.update_metadata.subprocess.Popen", return_value=process),
                patch("scripts.update_metadata.sys.stderr", io.StringIO()),
            ):
                with self.assertRaisesRegex(TimeoutError, "timed out after"):
                    run_exporter(root)

            self.assertTrue(process.killed)

    def test_run_exporter_defers_when_game_was_launched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}")
            (root / "src/cli").mkdir(parents=True)
            (root / "src/cli/index.ts").write_text("")
            process = CompletedProcess(
                stdout="◇ injected env (8) from .env\n",
                stderr=GAME_LAUNCHED_MESSAGE + "\n",
                return_code=0,
            )

            with (
                patch("scripts.update_metadata.subprocess.Popen", return_value=process),
                patch("scripts.update_metadata.sys.stderr", io.StringIO()),
            ):
                with self.assertRaisesRegex(ExportDeferred, "Game was launched"):
                    run_exporter(root)

    def test_main_returns_success_when_export_is_deferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}")
            (root / "src/cli").mkdir(parents=True)
            (root / "src/cli/index.ts").write_text("")
            process = CompletedProcess(
                stdout="◇ injected env (8) from .env\n",
                stderr=GAME_LAUNCHED_MESSAGE + "\n",
                return_code=0,
            )

            with (
                patch("scripts.update_metadata.subprocess.Popen", return_value=process),
                patch("scripts.update_metadata.sys.stderr", io.StringIO()),
            ):
                self.assertEqual(main(["--frida-test-dir", str(root)]), 0)

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

    def test_converts_sets_from_top_level_pack_master_rows(self):
        export = raw_export(
            [],
            expansions=[
                {"expansionId": "A10", "names": ["第十彈", "短名"]},
                {"expansionId": "A2", "names": ["第二彈"]},
                {"expansionId": "B1", "names": ["B 組"]},
                {"expansionId": "C1", "names": ["無卡系列"]},
            ],
            packs=[
                pack("A10_CHARIZARD_00_000", "A10", "第十彈: 噴火龍"),
                pack("A10_MEWTWO_00_000", "A10", "第十彈: 超夢"),
                pack("A2_PIKACHU_00_000", "A2", "第二彈: 皮卡丘"),
            ],
        )
        cards = [
            {"set": "A10", "number": 1, "packs": ["錯誤來源"]},
            {"set": "A10", "number": 2, "packs": ["超夢"]},
            {"set": "A2", "number": 1, "packs": ["錯誤來源"]},
            {"set": "B1", "number": 1, "packs": ["錯誤來源"]},
        ]

        self.assertEqual(
            convert_sets(export, cards),
            {
                "A": [
                    {
                        "code": "A2",
                        "releaseDate": None,
                        "count": 1,
                        "name": {"zh": "第二彈"},
                        "packs": ["皮卡丘"],
                    },
                    {
                        "code": "A10",
                        "releaseDate": None,
                        "count": 2,
                        "name": {"zh": "第十彈"},
                        "packs": ["噴火龍", "超夢"],
                    },
                ],
                "B": [
                    {
                        "code": "B1",
                        "releaseDate": None,
                        "count": 1,
                        "name": {"zh": "B 組"},
                        "packs": [],
                    }
                ],
            },
        )

    def test_convert_sets_does_not_aggregate_mixed_card_pack_sources(self):
        export = raw_export(
            [],
            expansions=[{"expansionId": "A1", "names": ["最強的基因"]}],
            packs=[
                pack("AN001_0010_00_000", "A1", "最強的基因: 超夢"),
                pack("AN001_0020_00_000", "A1", "最強的基因: 噴火龍"),
                pack("AN001_0030_00_000", "A1", "最強的基因: 皮卡丘"),
            ],
        )
        cards = [
            {"set": "A1", "number": 1, "packs": ["超夢", "Mythical Island", "Deluxe Pack ex"]},
            {"set": "A1", "number": 2, "packs": ["噴火龍"]},
        ]

        self.assertEqual(convert_sets(export, cards)["A"][0]["packs"], ["噴火龍", "皮卡丘", "超夢"])

    def test_convert_sets_a1a_single_pack_is_not_polluted_by_a1_card_sources(self):
        export = raw_export(
            [],
            expansions=[{"expansionId": "A1a", "names": ["幻遊島"]}],
            packs=[pack("A1a_MYTHICAL_00_000", "A1a", "幻遊島")],
        )
        cards = [{"set": "A1a", "number": 1, "packs": ["超夢", "幻遊島"]}]

        self.assertEqual(convert_sets(export, cards)["A"][0]["packs"], ["幻遊島"])

    def test_convert_sets_a4b_reprint_rows_do_not_pull_old_packs(self):
        export = raw_export(
            [],
            expansions=[{"expansionId": "A4b", "names": ["A4b"]}],
            packs=[pack("A4b_DELUXE_00_000", "A4b", "Deluxe Pack: ex")],
        )
        cards = [{"set": "A4b", "number": 1, "packs": ["Mewtwo", "Charizard", "Deluxe Pack ex"]}]

        self.assertEqual(convert_sets(export, cards)["A"][0]["packs"], ["Deluxe Pack ex"])

    def test_convert_sets_derives_multi_pack_set_name_from_pack_master_prefix(self):
        export = raw_export(
            [],
            expansions=[{"expansionId": "A1", "names": ["A1"]}],
            packs=[
                pack("AN001_0010_00_000", "A1", "Genetic Apex: Mewtwo"),
                pack("AN001_0020_00_000", "A1", "Genetic Apex: Charizard"),
                pack("AN001_0030_00_000", "A1", "Genetic Apex: Pikachu"),
            ],
        )
        cards = [{"set": "A1", "number": 1, "packs": []}]

        [set_item] = convert_sets(export, cards)["A"]

        self.assertEqual(set_item["name"], {"zh": "Genetic Apex"})
        self.assertEqual(set_item["packs"], ["Charizard", "Mewtwo", "Pikachu"])

    def test_convert_sets_derives_b1_set_name_from_separated_pack_master_prefix(self):
        export = raw_export(
            [],
            expansions=[{"expansionId": "B1", "names": ["B1"]}],
            packs=[
                pack("B1_BLAZIKEN_00_000", "B1", "Mega Rising: Mega Blaziken"),
                pack("B1_GYARADOS_00_000", "B1", "Mega Rising: Mega Gyarados"),
                pack("B1_ALTARIA_00_000", "B1", "Mega Rising: Mega Altaria"),
            ],
        )
        cards = [{"set": "B1", "number": 1, "packs": []}]

        [set_item] = convert_sets(export, cards)["B"]

        self.assertEqual(set_item["name"], {"zh": "Mega Rising"})
        self.assertEqual(set_item["packs"], ["Mega Altaria", "Mega Blaziken", "Mega Gyarados"])

    def test_convert_sets_derives_single_pack_set_name_from_pack_master_name(self):
        export = raw_export(
            [],
            expansions=[{"expansionId": "A1a", "names": ["A1a"]}],
            packs=[pack("A1a_MYTHICAL_00_000", "A1a", "Mythical Island")],
        )
        cards = [{"set": "A1a", "number": 1, "packs": []}]

        self.assertEqual(convert_sets(export, cards)["A"][0]["name"], {"zh": "Mythical Island"})

    def test_convert_sets_promo_name_falls_back_to_code_instead_of_pack_master_name(self):
        export = raw_export(
            [],
            expansions=[{"expansionId": "PROMO-A", "names": []}],
            packs=[pack("PROMO_A_VOL1_00_000", "PROMO-A", "Promo Pack A Series Vol. 1")],
        )
        cards = [{"set": "PROMO-A", "number": 1, "packs": []}]

        self.assertEqual(convert_sets(export, cards)["P"][0]["name"], {"zh": "PROMO-A"})

    def test_convert_sets_promo_keeps_pack_master_name_instead_of_featured_card_name(self):
        export = raw_export(
            [pokemon_card(set_id="PROMO-A", name="Butterfree", card_id="PK_10_000120", number=1)],
            expansions=[{"expansionId": "PROMO-A", "names": []}],
            packs=[pack("PROMO_A_VOL1_00_000", "PROMO-A", "Promo Pack A Series Vol. 1", ["PK_10_000120"])],
        )
        cards = [{"set": "PROMO-A", "number": 1, "packs": ["Butterfree"]}]

        self.assertEqual(convert_sets(export, cards)["P"][0]["packs"], ["Promo Pack A Series Vol. 1"])

    def test_convert_sets_promo_packs_never_strip_common_prefix_to_volume_number(self):
        export = raw_export(
            [
                pokemon_card(set_id="PROMO-A", name="Butterfree", card_id="PK_10_000120", number=1),
                pokemon_card(set_id="PROMO-A", name="Lapras", card_id="PK_10_000130", number=2),
            ],
            expansions=[{"expansionId": "PROMO-A", "names": []}],
            packs=[
                pack("PROMO_A_VOL1_00_000", "PROMO-A", "Promo Pack A Series Vol. 1", ["PK_10_000120"]),
                pack("PROMO_A_VOL2_00_000", "PROMO-A", "Promo Pack A Series Vol. 2", ["PK_10_000130"]),
            ],
        )
        cards = [{"set": "PROMO-A", "number": 1, "packs": ["Butterfree"]}]

        self.assertEqual(
            convert_sets(export, cards)["P"][0]["packs"],
            ["Promo Pack A Series Vol. 1", "Promo Pack A Series Vol. 2"],
        )

    def test_convert_sets_promo_packs_use_natural_sort(self):
        export = raw_export(
            [],
            expansions=[{"expansionId": "PROMO-A", "names": []}],
            packs=[
                pack("PROMO_A_VOL10_00_000", "PROMO-A", "Promo Pack A Series Vol. 10"),
                pack("PROMO_A_VOL2_00_000", "PROMO-A", "Promo Pack A Series Vol. 2"),
                pack("PROMO_A_VOL1_00_000", "PROMO-A", "Promo Pack A Series Vol. 1"),
            ],
        )
        cards = [{"set": "PROMO-A", "number": 1, "packs": []}]

        self.assertEqual(
            convert_sets(export, cards)["P"][0]["packs"],
            [
                "Promo Pack A Series Vol. 1",
                "Promo Pack A Series Vol. 2",
                "Promo Pack A Series Vol. 10",
            ],
        )

    def test_convert_sets_requires_top_level_packs(self):
        export = raw_export([], expansions=[{"expansionId": "A1", "names": ["最強的基因"]}])
        del export["packs"]

        with self.assertRaisesRegex(ValueError, "packs must be an array of objects"):
            convert_sets(export, [{"set": "A1", "number": 1, "packs": ["超夢"]}])

    def test_convert_sets_only_uses_normal_pack_rows(self):
        export = raw_export(
            [],
            expansions=[{"expansionId": "A1", "names": ["最強的基因"]}],
            packs=[
                pack("AN001_0010_00_000", "A1", "最強的基因: 超夢"),
                pack("AN001_0010_01_000", "A1", "最強的基因: 高稀有度"),
            ],
        )
        cards = [{"set": "A1", "number": 1, "packs": ["高稀有度"]}]

        self.assertEqual(convert_sets(export, cards)["A"][0]["packs"], ["超夢"])

    def test_convert_sets_uses_second_name_when_long_name_is_empty(self):
        export = raw_export(
            [],
            expansions=[{"expansionId": "A1", "names": ["", "最強的基因"]}],
        )
        cards = [{"set": "A1", "number": 1, "packs": []}]

        self.assertEqual(convert_sets(export, cards)["A"][0]["name"], {"zh": "最強的基因"})

    def test_convert_sets_uses_expansion_code_when_promo_name_is_missing(self):
        export = raw_export(
            [],
            expansions=[{"expansionId": "PROMO-A", "names": []}],
        )
        cards = [{"set": "PROMO-A", "number": 1, "packs": []}]

        self.assertEqual(convert_sets(export, cards)["P"][0]["name"], {"zh": "PROMO-A"})

    def test_convert_sets_rejects_unknown_language_key(self):
        export = {
            **raw_export([], expansions=[{"expansionId": "A1", "names": ["Genetic Apex"]}]),
            "language": "xx-YY",
        }

        with self.assertRaisesRegex(ValueError, "unsupported language"):
            convert_sets(export, [{"set": "A1", "number": 1, "packs": []}])

    def test_writes_sets_to_language_directory_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = write_sets(Path(tmp), "zh-TW", {"A": [{"code": "A1"}]})

            self.assertEqual(output, Path(tmp) / "metadata/sets/zh-TW/sets.json")
            self.assertEqual(json.loads(output.read_text()), {"A": [{"code": "A1"}]})


if __name__ == "__main__":
    unittest.main()
