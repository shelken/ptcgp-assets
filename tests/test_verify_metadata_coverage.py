import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verify_metadata_coverage import compare_cards, compare_sets, print_report


class VerifyMetadataCoverageTests(unittest.TestCase):
    def test_reports_missing_extra_and_non_authoritative_changed_values(self):
        baseline = [
            {
                "set": "A1",
                "number": 1,
                "name": "Bulbasaur",
                "rarity": "C",
                "packs": ["Mewtwo"],
                "element": "Grass",
                "type": "pokemon",
                "stage": 0,
                "health": 50,
                "retreatCost": 1,
                "weakness": "Dark",
                "evolvesFrom": None,
                "goodWith": ["Grass"],
            },
            {
                "set": "A1",
                "number": 2,
                "name": "Ivysaur",
                "rarity": "U",
                "packs": ["Mewtwo"],
                "element": "grass",
                "type": "pokemon",
                "health": 80,
            },
        ]
        candidate = [
            {
                "set": "A1",
                "number": 1,
                "name": "妙蛙種子",
                "rarity": "R",
                "packs": ["超夢", "高級擴充包ex"],
                "element": "grass",
                "type": "pokemon",
                "stage": "basic",
                "health": 70,
                "retreatCost": 2,
                "weakness": "Darkness",
                "evolvesFrom": None,
                "extraKey": "allowed",
            },
            {"set": "A1", "number": 3, "name": "Only in candidate"},
        ]

        report = compare_cards(baseline, candidate)

        self.assertEqual(report.extra_count, 1)
        self.assertEqual(report.missing_cards, [{"set": "A1", "number": 2, "name": "Ivysaur"}])
        self.assertEqual(
            report.differences,
            [
                {
                    "set": "A1",
                    "number": 1,
                    "name": "Bulbasaur",
                    "fields": [
                        {"key": "rarity", "baseline": "C", "candidate": "R"},
                    ],
                }
            ],
        )

    def test_ignores_non_enum_strings_and_accepts_same_list_lengths(self):
        baseline = [
            {
                "set": "A1",
                "number": 1,
                "name": "Bulbasaur",
                "image": "english.webp",
                "packs": ["Mewtwo"],
                "evolvesFrom": "Old name",
                "type": "pokemon",
            }
        ]
        candidate = [
            {
                "set": "A1",
                "number": 1,
                "name": "妙蛙種子",
                "image": "localized.webp",
                "packs": ["超夢"],
                "evolvesFrom": "本地化名稱",
                "type": "pokemon",
            }
        ]

        report = compare_cards(baseline, candidate)

        self.assertEqual(report.extra_count, 0)
        self.assertEqual(report.missing_cards, [])
        self.assertEqual(report.differences, [])

    def test_sets_ignores_game_authoritative_count_and_reports_pack_count_differences(self):
        baseline = {
            "A": [
                {"code": "A1", "releaseDate": "2024-10-30", "count": 2, "name": {"en": "Old"}, "packs": ["Mewtwo"]},
                {"code": "A2", "releaseDate": "2025-01-01", "count": 1, "name": {"en": "Next"}, "packs": []},
            ]
        }
        candidate = {
            "A": [
                {"code": "A1", "releaseDate": None, "count": 3, "name": {"zh": "最強的基因"}, "packs": ["超夢", "皮卡丘"]},
                {"code": "A3", "releaseDate": None, "count": 1, "name": {"zh": "多出"}, "packs": []},
            ]
        }

        report = compare_sets(baseline, candidate)

        self.assertEqual(report.extra_count, 1)
        self.assertEqual(report.missing_cards, [{"code": "A2", "name": {"en": "Next"}}])
        self.assertEqual(
            report.differences,
            [
                {
                    "code": "A1",
                    "name": {"en": "Old"},
                    "candidateName": {"zh": "最強的基因"},
                    "fields": [
                        {"key": "packs", "baselineCount": 1, "candidateCount": 2},
                    ],
                }
            ],
        )

    def test_sets_ignores_release_date_and_name_text_when_candidate_has_non_empty_name(self):
        baseline = {
            "A": [
                {"code": "A1", "releaseDate": "2024-10-30", "count": 2, "name": {"en": "Genetic Apex"}, "packs": ["Mewtwo"]}
            ]
        }
        candidate = {
            "A": [
                {"code": "A1", "releaseDate": None, "count": 2, "name": {"zh": "最強的基因"}, "packs": ["超夢"]}
            ]
        }

        report = compare_sets(baseline, candidate)

        self.assertEqual(report.extra_count, 0)
        self.assertEqual(report.missing_cards, [])
        self.assertEqual(report.differences, [])

    def test_sets_requires_candidate_non_empty_name(self):
        baseline = {"A": [{"code": "A1", "count": 1, "name": {"en": "Genetic Apex"}, "packs": []}]}
        candidate = {"A": [{"code": "A1", "count": 1, "name": {"zh": "   "}, "packs": []}]}

        report = compare_sets(baseline, candidate)

        self.assertEqual(
            report.differences,
            [
                {
                    "code": "A1",
                    "name": {"en": "Genetic Apex"},
                    "candidateName": {"zh": "   "},
                    "fields": [{"key": "name", "candidate": {"zh": "   "}, "error": "missing non-empty name"}],
                }
            ],
        )

    def test_print_report_supports_sets_shape(self):
        baseline = {
            "A": [
                {"code": "A1", "count": 1, "name": {"en": "One"}, "packs": ["Mewtwo"]},
                {"code": "A2", "count": 1, "name": {"en": "Two"}, "packs": []},
            ]
        }
        candidate = {
            "A": [{"code": "A1", "count": 2, "name": {"zh": "一"}, "packs": ["超夢", "皮卡丘"]}]
        }
        report = compare_sets(baseline, candidate)

        with patch("builtins.print") as print_mock:
            print_report(report, "sets")

        lines = [call.args[0] for call in print_mock.call_args_list]
        self.assertIn("extra sets: 0", lines)
        self.assertIn("  A2 {'en': 'Two'}", lines)
        self.assertIn("  A1 baselineName={'en': 'One'} candidateName={'zh': '一'}", lines)

    def test_sets_ignores_promo_pack_count_differences(self):
        baseline = {"P": [{"code": "PROMO-B", "count": 1, "name": {"en": "Promo B"}, "packs": ["Vol. 1", "Vol. 2", "Vol. 3"]}]}
        candidate = {"P": [{"code": "PROMO-B", "count": 9, "name": {"en": "PROMO-B"}, "packs": [str(index) for index in range(9)]}]}

        report = compare_sets(baseline, candidate)

        self.assertEqual(report.differences, [])

    def test_sets_rejects_duplicate_code(self):
        baseline = {"A": [{"code": "A1", "count": 1, "name": {"en": "One"}, "packs": []}]}
        candidate = {"A": [{"code": "A1"}, {"code": "A1"}]}

        with self.assertRaisesRegex(ValueError, "duplicate set code: A1"):
            compare_sets(baseline, candidate)


if __name__ == "__main__":
    unittest.main()
