#!/usr/bin/env python3
"""校验本地 metadata 是否覆盖 flibustier 原版结构。"""

from __future__ import annotations

import argparse
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASELINE_CARDS_EXTRA_URL = "https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/cards.extra.json"
BASELINE_CARDS_EXTRA_PATH = Path("/tmp/cards.extra.json")
DEFAULT_CARDS_EXTRA_CANDIDATE = Path("metadata/cards/en-US/cards.extra.json")
BASELINE_SETS_URL = "https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/sets.json"
BASELINE_SETS_PATH = Path("/tmp/sets.json")
DEFAULT_SETS_CANDIDATE = Path("metadata/sets/en-US/sets.json")
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


def load_json_data(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require_object_items(data: Any, path: Path) -> list[dict[str, Any]]:
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


def set_code(set_item: dict[str, Any]) -> str:
    code = set_item.get("code")
    if not isinstance(code, str) or not code:
        raise ValueError(f"set code must be a non-empty string: {set_item}")
    return code


def flatten_sets(sets: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for group_key, items in sets.items():
        if not isinstance(group_key, str):
            raise ValueError(f"set group key must be a string: {group_key}")
        if not isinstance(items, list):
            raise ValueError(f"set group {group_key} must be an array")
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"set group {group_key} item #{index} must be an object")
            result.append(item)
    return result


def index_sets(sets: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in flatten_sets(sets):
        code = set_code(item)
        if code in result:
            raise ValueError(f"duplicate set code: {code}")
        result[code] = item
    return result


def has_non_empty_name(value: Any) -> bool:
    return isinstance(value, dict) and any(
        isinstance(item, str) and item.strip() for item in value.values()
    )


def compare_set_field(
    key: str, baseline_value: Any, candidate: dict[str, Any], code: str
) -> dict[str, Any] | None:
    if key in {"code", "releaseDate", "count"}:
        return None

    if key not in candidate:
        return {"key": key, "baseline": baseline_value, "candidate": "<missing>"}

    candidate_value = candidate[key]
    if key == "packs":
        if code.startswith("PROMO-"):
            return None
        if not isinstance(baseline_value, list) or not isinstance(candidate_value, list):
            return {
                "key": key,
                "baselineType": type(baseline_value).__name__,
                "candidateType": type(candidate_value).__name__,
            }
        if len(baseline_value) != len(candidate_value):
            return {
                "key": key,
                "baselineCount": len(baseline_value),
                "candidateCount": len(candidate_value),
            }
        return None

    if key == "name":
        if not has_non_empty_name(candidate_value):
            return {"key": key, "candidate": candidate_value, "error": "missing non-empty name"}
        return None

    return None


def compare_sets(
    baseline: dict[str, list[dict[str, Any]]], candidate: dict[str, list[dict[str, Any]]]
) -> CompareReport:
    baseline_by_code = index_sets(baseline)
    candidate_by_code = index_sets(candidate)
    missing_sets: list[dict[str, Any]] = []
    differences: list[dict[str, Any]] = []

    for code in sorted(baseline_by_code):
        baseline_set = baseline_by_code[code]
        candidate_set = candidate_by_code.get(code)
        if candidate_set is None:
            missing_sets.append({"code": code, "name": baseline_set.get("name")})
            continue

        field_differences = []
        for field_key, baseline_value in baseline_set.items():
            difference = compare_set_field(field_key, baseline_value, candidate_set, code)
            if difference is not None:
                field_differences.append(difference)

        if field_differences:
            differences.append(
                {
                    "code": code,
                    "name": baseline_set.get("name"),
                    "candidateName": candidate_set.get("name"),
                    "fields": field_differences,
                }
            )

    extra_count = len(set(candidate_by_code) - set(baseline_by_code))
    return CompareReport(
        missing_cards=missing_sets,
        differences=differences,
        extra_count=extra_count,
    )


def download_baseline(url: str, path: Path) -> None:
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read()
    path.write_bytes(body)


def describe_report_item(item: dict[str, Any], target: str) -> str:
    if target == "cards-extra":
        return f"{item['set']} #{item['number']} {item.get('name', '')}"
    if target == "sets":
        if "candidateName" in item:
            return f"{item['code']} baselineName={item.get('name', '')} candidateName={item.get('candidateName', '')}"
        return f"{item['code']} {item.get('name', '')}"
    raise ValueError(f"unsupported report target: {target}")


def print_report(report: CompareReport, target: str) -> None:
    if target not in {"cards-extra", "sets"}:
        raise ValueError(f"unsupported report target: {target}")
    label = "cards" if target == "cards-extra" else "sets"
    print(f"extra {label}: {report.extra_count}")

    if report.missing_cards:
        print(f"\nmissing {label}:")
        for item in report.missing_cards:
            print(f"  {describe_report_item(item, target)}")

    if report.differences:
        print("\nfield differences:")
        for item in report.differences:
            print(f"  {describe_report_item(item, target)}")
            for field in item["fields"]:
                print(f"    {field}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify local metadata coverage")
    subparsers = parser.add_subparsers(dest="target", required=True)

    cards_parser = subparsers.add_parser("cards-extra")
    cards_parser.add_argument("--candidate", type=Path, default=DEFAULT_CARDS_EXTRA_CANDIDATE)
    cards_parser.add_argument("--baseline-url", default=BASELINE_CARDS_EXTRA_URL)
    cards_parser.add_argument("--baseline-path", type=Path, default=BASELINE_CARDS_EXTRA_PATH)

    sets_parser = subparsers.add_parser("sets")
    sets_parser.add_argument("--candidate", type=Path, default=DEFAULT_SETS_CANDIDATE)
    sets_parser.add_argument("--baseline-url", default=BASELINE_SETS_URL)
    sets_parser.add_argument("--baseline-path", type=Path, default=BASELINE_SETS_PATH)

    args = parser.parse_args(argv)

    download_baseline(args.baseline_url, args.baseline_path)
    baseline_data = load_json_data(args.baseline_path)
    candidate_data = load_json_data(args.candidate)

    if args.target == "cards-extra":
        baseline = require_object_items(baseline_data, args.baseline_path)
        candidate = require_object_items(candidate_data, args.candidate)
        report = compare_cards(baseline, candidate)
    else:
        if not isinstance(baseline_data, dict) or not isinstance(candidate_data, dict):
            raise ValueError("sets metadata must contain a JSON object")
        report = compare_sets(baseline_data, candidate_data)

    print_report(report, args.target)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
