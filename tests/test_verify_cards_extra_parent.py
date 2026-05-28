import unittest

from scripts.verify_cards_extra_parent import compare_cards


class VerifyCardsExtraParentTests(unittest.TestCase):
    def test_reports_missing_extra_and_changed_values(self):
        baseline = [
            {
                "set": "A1",
                "number": 1,
                "name": "Bulbasaur",
                "rarity": "C",
                "packs": ["Mewtwo"],
                "element": "grass",
                "type": "pokemon",
                "health": 50,
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
                "health": 70,
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
                        {"key": "packs", "baselineCount": 1, "candidateCount": 2},
                        {"key": "health", "baseline": 50, "candidate": 70},
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


if __name__ == "__main__":
    unittest.main()
