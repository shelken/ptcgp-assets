#!/usr/bin/env python3
"""校验本地 cards.extra.json 是否覆盖 flibustier 原版结构。"""

from __future__ import annotations

import argparse
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASELINE_URL = "https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/cards.extra.json"
BASELINE_PATH = Path("/tmp/cards.extra.json")
DEFAULT_CANDIDATE = Path("metadata/cards/en-US/cards.extra.json")
ENUM_STRING_KEYS = {"rarity", "type"}
GAME_AUTHORITATIVE_KEYS = {
    "packs",
    "element",
    "stage",
    "health",
    "retreatCost",
    "weakness",
    "evolvesFrom",
    "goodWith",
}


@dataclass
class CompareReport:
    missing_cards: list[dict[str, Any]]
    differences: list[dict[str, Any]]
    extra_count: int

    @property
    def ok(self) -> bool:
        return not self.missing_cards and not self.differences


def load_json_array(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"{path} item #{index} must be an object")
    return data


def card_key(card: dict[str, Any]) -> tuple[str, int]:
    set_name = card.get("set")
    number = card.get("number")
    if not isinstance(set_name, str) or not isinstance(number, int):
        raise ValueError(f"card key must be (string set, integer number): {card}")
    return (set_name, number)


def index_cards(cards: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for card in cards:
        key = card_key(card)
        if key in result:
            raise ValueError(f"duplicate card key: {key[0]} #{key[1]}")
        result[key] = card
    return result


def should_compare_string(key: str) -> bool:
    return key in ENUM_STRING_KEYS


def compare_field(
    key: str, baseline_value: Any, candidate: dict[str, Any]
) -> dict[str, Any] | None:
    if key in GAME_AUTHORITATIVE_KEYS:
        return None

    if key not in candidate:
        return {"key": key, "baseline": baseline_value, "candidate": "<missing>"}

    candidate_value = candidate[key]
    if isinstance(baseline_value, list):
        if not isinstance(candidate_value, list):
            return {
                "key": key,
                "baselineType": "list",
                "candidateType": type(candidate_value).__name__,
            }
        if len(baseline_value) != len(candidate_value):
            return {
                "key": key,
                "baselineCount": len(baseline_value),
                "candidateCount": len(candidate_value),
            }
        return None

    if isinstance(baseline_value, int) and not isinstance(baseline_value, bool):
        if candidate_value != baseline_value:
            return {
                "key": key,
                "baseline": baseline_value,
                "candidate": candidate_value,
            }
        return None

    if isinstance(baseline_value, str) and should_compare_string(key):
        if candidate_value != baseline_value:
            return {
                "key": key,
                "baseline": baseline_value,
                "candidate": candidate_value,
            }
        return None

    return None


def compare_cards(
    baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]
) -> CompareReport:
    baseline_by_key = index_cards(baseline)
    candidate_by_key = index_cards(candidate)
    missing_cards: list[dict[str, Any]] = []
    differences: list[dict[str, Any]] = []

    for key in sorted(baseline_by_key):
        baseline_card = baseline_by_key[key]
        candidate_card = candidate_by_key.get(key)
        if candidate_card is None:
            missing_cards.append(
                {
                    "set": key[0],
                    "number": key[1],
                    "name": baseline_card.get("name"),
                }
            )
            continue

        field_differences = []
        for field_key, baseline_value in baseline_card.items():
            difference = compare_field(field_key, baseline_value, candidate_card)
            if difference is not None:
                field_differences.append(difference)

        if field_differences:
            differences.append(
                {
                    "set": key[0],
                    "number": key[1],
                    "name": baseline_card.get("name"),
                    "fields": field_differences,
                }
            )

    extra_count = len(set(candidate_by_key) - set(baseline_by_key))
    return CompareReport(
        missing_cards=missing_cards, differences=differences, extra_count=extra_count
    )


def download_baseline(url: str, path: Path) -> None:
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read()
    path.write_bytes(body)


def print_report(report: CompareReport) -> None:
    print(f"extra cards: {report.extra_count}")

    if report.missing_cards:
        print("\nmissing cards:")
        for card in report.missing_cards:
            print(f"  {card['set']} #{card['number']} {card.get('name', '')}")

    if report.differences:
        print("\nfield differences:")
        for card in report.differences:
            print(f"  {card['set']} #{card['number']} {card.get('name', '')}")
            for field in card["fields"]:
                print(f"    {field}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify local cards.extra.json is a parent set of upstream"
    )
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--baseline-url", default=BASELINE_URL)
    parser.add_argument("--baseline-path", type=Path, default=BASELINE_PATH)
    args = parser.parse_args(argv)

    download_baseline(args.baseline_url, args.baseline_path)
    baseline = load_json_array(args.baseline_path)
    candidate = load_json_array(args.candidate)
    report = compare_cards(baseline, candidate)
    print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
