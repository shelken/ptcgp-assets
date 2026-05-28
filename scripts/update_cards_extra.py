#!/usr/bin/env python3
"""從 frida-test 匯出 PTCGP 卡牌 metadata，寫入 cards.extra.json。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

EXPORT_COMMAND = [
    "./node_modules/.bin/tsx",
    "src/cli/index.ts",
    "ptcgp",
    "export-metadata",
    "--out",
    "-",
]

ENERGY_TYPES = {
    "Grass": "grass",
    "Fire": "fire",
    "Water": "water",
    "Lightning": "lightning",
    "Psychic": "psychic",
    "Fighting": "fighting",
    "Darkness": "darkness",
    "Metal": "metal",
    "Dragon": "dragon",
    "Colorless": "colorless",
}

STAGES: dict[Any, Any] = {
    "Basic": "basic",
    "Stage1": 1,
    "Stage2": 2,
    "One": 1,
    "Two": 2,
    1: 1,
    2: 2,
}

TRAINER_TYPES = {
    "Supporter": "supporter",
    "Item": "item",
    "PokemonTool": "tool",
    "Fossil": "Fossil",
    "Stadium": "stadium",
}

FIELD_ORDER = [
    "set",
    "number",
    "name",
    "rarity",
    "image",
    "packs",
    "element",
    "type",
    "stage",
    "health",
    "retreatCost",
    "weakness",
    "evolvesFrom",
]


def require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field} must be a non-empty string")
    return value


def require_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    return value


def require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be an array of strings")
    return value


def preview_text(value: str, limit: int = 800) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...<truncated>"


def normalize_pack_name(pack_name: str) -> str:
    parts = pack_name.rsplit(" ", 1)
    if len(parts) == 1 or parts[1] == "ex":
        return pack_name
    return parts[1]


def normalize_pack_names(value: Any) -> list[str]:
    return [normalize_pack_name(pack) for pack in require_string_list(value, "packs")]


def parse_exporter_stdout(stdout: str, stderr: str, command: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            raise ValueError("frida-test exporter JSON must be an object")
        return parsed

    raise ValueError(
        "frida-test exporter stdout is not JSON\n"
        f"command: {command}\n"
        f"stdout preview: {preview_text(stdout)}\n"
        f"stderr preview: {preview_text(stderr)}"
    )


def map_value(mapping: dict[Any, Any], value: Any, field: str) -> Any:
    if value not in mapping:
        raise ValueError(f"unsupported {field}: {value}")
    return mapping[value]


def ordered_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in FIELD_ORDER if key in record}


def convert_pokemon(card: dict[str, Any]) -> dict[str, Any]:
    pokemon = card.get("pokemon")
    if not isinstance(pokemon, dict):
        raise ValueError(f"pokemon payload missing for {card.get('set')} #{card.get('number')}")

    record: dict[str, Any] = {
        "set": require_str(card.get("set"), "set"),
        "number": require_int(card.get("number"), "number"),
        "name": require_str(card.get("name"), "name"),
        "rarity": require_str(card.get("rarity"), "rarity"),
        "image": require_image(card.get("image")),
        "packs": normalize_pack_names(card.get("packs")),
        "element": map_value(ENERGY_TYPES, pokemon.get("element"), "element"),
        "type": "pokemon",
        "stage": map_value(STAGES, pokemon.get("stage"), "stage"),
        "health": require_int(pokemon.get("health"), "health"),
        "retreatCost": require_int(pokemon.get("retreatCost"), "retreatCost"),
        "weakness": pokemon.get("weakness"),
    }

    if record["weakness"] is not None:
        record["weakness"] = require_str(record["weakness"], "weakness")

    evolves_from = pokemon.get("evolvesFrom")
    record["evolvesFrom"] = None if evolves_from is None else require_str(evolves_from, "evolvesFrom")

    return ordered_record(record)


def require_image(value: Any) -> str:
    image = require_str(value, "image")
    if not image.endswith(".webp"):
        raise ValueError(f"image must end with .webp: {image}")
    return image


def convert_trainer(card: dict[str, Any]) -> dict[str, Any]:
    trainer = card.get("trainer")
    if not isinstance(trainer, dict):
        raise ValueError(f"trainer payload missing for {card.get('set')} #{card.get('number')}")

    trainer_type = map_value(TRAINER_TYPES, trainer.get("type"), "trainer type")
    record: dict[str, Any] = {
        "set": require_str(card.get("set"), "set"),
        "number": require_int(card.get("number"), "number"),
        "name": require_str(card.get("name"), "name"),
        "rarity": require_str(card.get("rarity"), "rarity"),
        "image": require_image(card.get("image")),
        "packs": normalize_pack_names(card.get("packs")),
        "type": trainer_type,
    }

    if trainer_type == "Fossil":
        record["stage"] = "basic"

    return ordered_record(record)


def natural_key(card: dict[str, Any]) -> tuple[str, int]:
    return (card["set"], card["number"])


def convert_export(export: dict[str, Any]) -> list[dict[str, Any]]:
    language = require_str(export.get("language"), "language")
    if "_" in language:
        raise ValueError(f"language must use hyphen form: {language}")

    cards = export.get("cards")
    if not isinstance(cards, list):
        raise ValueError("cards must be an array")

    converted: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for card in cards:
        if not isinstance(card, dict):
            raise ValueError("card must be an object")

        kind = require_str(card.get("kind"), "kind")
        if kind == "pokemon":
            record = convert_pokemon(card)
        elif kind == "trainer":
            record = convert_trainer(card)
        else:
            raise ValueError(f"unsupported card kind: {kind}")

        key = natural_key(record)
        if key in seen:
            raise ValueError(f"duplicate card key: {key[0]} #{key[1]}")
        seen.add(key)
        converted.append(record)

    if not converted:
        raise ValueError("converted cards must not be empty")

    return sorted(converted, key=natural_key)


def run_exporter(frida_test_dir: Path) -> dict[str, Any]:
    if not frida_test_dir.is_dir():
        raise ValueError(f"frida-test dir does not exist: {frida_test_dir}")
    if not (frida_test_dir / "package.json").is_file():
        raise ValueError(f"frida-test dir missing package.json: {frida_test_dir}")
    if not (frida_test_dir / "src/cli/index.ts").is_file():
        raise ValueError(f"frida-test dir missing src/cli/index.ts: {frida_test_dir}")

    command_display = " ".join(EXPORT_COMMAND)
    result = subprocess.run(
        EXPORT_COMMAND,
        cwd=frida_test_dir,
        check=False,
        text=True,
        capture_output=True,
    )

    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            "frida-test exporter failed\n"
            f"command: {command_display}\n"
            f"exit code: {result.returncode}\n"
            f"stdout preview: {preview_text(result.stdout)}\n"
            f"stderr preview: {preview_text(result.stderr)}"
        )

    return parse_exporter_stdout(result.stdout, result.stderr, command_display)


def write_cards_extra(root: Path, language: str, cards: list[dict[str, Any]]) -> Path:
    require_str(language, "language")
    out_path = root / "metadata" / "cards" / language / "cards.extra.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(out_path)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update PTCGP cards.extra metadata from frida-test")
    parser.add_argument("--frida-test-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    export = run_exporter(args.frida_test_dir)
    cards = convert_export(export)
    language = require_str(export.get("language"), "language")
    output = write_cards_extra(Path.cwd(), language, cards)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
