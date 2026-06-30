#!/usr/bin/env python3
"""從 frida-test 匯出 PTCGP metadata，寫入 cards.extra.json 與 sets.json。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

EXPORT_COMMAND = [
    "./node_modules/.bin/tsx",
    "src/cli/index.ts",
    "ptcgp",
    "export-metadata",
    "--out",
    "-",
]
EXPORT_TIMEOUT_SECONDS = 120
GAME_LAUNCHED_MESSAGE = (
    "Game was launched. Enter the game home screen, then run export again. "
    "Cold-start attach can freeze Unity/IL2CPP before MemoryDatabase is loaded."
)
NORMAL_PACK_MARKER = "_00_000"
LANGUAGE_KEY_MAP = {
    "en-US": "en",
    "zh-TW": "zh",
    "zh-CN": "zh",
    "ja-JP": "ja",
    "ko-KR": "ko",
    "fr-FR": "fr",
    "de-DE": "de",
    "es-ES": "es",
    "it-IT": "it",
    "pt-BR": "pt",
}
TEXT_TOKEN_RE = re.compile(r"\[Text:([^\s\]]+)([^\]]*)\]")
TEXT_TOKEN_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


class ExportDeferred(RuntimeError):
    pass


@dataclass(frozen=True)
class ConversionContext:
    localization_texts: dict[str, str]
    expansion_names_by_id: dict[str, list[str]]
    normal_pack_count_by_expansion_id: dict[str, int]
    full_pack_names_by_expansion_id: dict[str, list[str]]
    card_name_by_key: dict[str, str]
    pack_name_by_key: dict[str, str]


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


def optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return require_str(value, field)


def require_clean_str(value: Any, field: str) -> str:
    text = require_str(value, field)
    if is_corrupt_text(text):
        raise ValueError(f"{field} contains replacement characters: {text}")
    return text


def require_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    return value


def require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be an array of strings")
    return value


def require_object_list(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{field} must be an array of objects")
    return value


def preview_text(value: str, limit: int = 800) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...<truncated>"


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


def is_corrupt_text(value: str | None) -> bool:
    return isinstance(value, str) and "�" in value


def parse_text_token_attributes(raw_attributes: str) -> dict[str, str]:
    return {match.group(1): match.group(2) for match in TEXT_TOKEN_ATTR_RE.finditer(raw_attributes)}


def render_char_token(value: str | None) -> str:
    if value in {"FOUR-PER-EM-SPACE", "SPACE"}:
        return " "
    return ""


def render_localized_rich_text(text: str | None, localization_texts: dict[str, str]) -> str | None:
    if text is None:
        return None

    def replace_token(match: re.Match[str]) -> str:
        kind = match.group(1)
        attributes = parse_text_token_attributes(match.group(2))
        value = attributes.get("v")

        if kind == "Char":
            return render_char_token(value)
        if kind == "AdditionalName":
            resolved = localization_texts.get(value or "")
            if resolved is not None:
                return render_localized_rich_text(resolved, localization_texts) or ""
            return (value or "").removeprefix("ADDITIONAL_NAME_")

        return value or ""

    rendered = TEXT_TOKEN_RE.sub(replace_token, text)
    return re.sub(r"\s+", " ", rendered).strip()


def card_lookup_keys(identifier: str | None) -> list[str]:
    if not identifier:
        return []

    without_extension = identifier.removesuffix(".webp")
    without_image_prefix = re.sub(r"^c(?=PK_|TR_)", "", without_extension)
    keys = {identifier, without_extension, without_image_prefix}
    parts = without_image_prefix.split("_")

    if len(parts) >= 4 and parts[0] in {"PK", "TR"}:
        keys.add("_".join(parts[:4]))
        keys.add("_".join(parts[:3]))

    if re.search(r"_(\d{2})$", without_image_prefix):
        keys.add(re.sub(r"_(\d{2})$", "", without_image_prefix))

    return [key for key in keys if key]


def character_lookup_key(character_id: str | None) -> str | None:
    return f"character:{character_id}" if character_id else None


def remember_best_name(names_by_key: dict[str, str], key: str | None, name: str | None) -> None:
    if not key or not name:
        return

    existing = names_by_key.get(key)
    if existing is None or (is_corrupt_text(existing) and not is_corrupt_text(name)):
        names_by_key[key] = name


def build_card_name_lookup(cards: list[dict[str, Any]], localization_texts: dict[str, str]) -> dict[str, str]:
    names_by_key: dict[str, str] = {}

    for card in cards:
        raw_name = card.get("name")
        name = render_localized_rich_text(raw_name, localization_texts) if isinstance(raw_name, str) else None
        for key in [
            *card_lookup_keys(card.get("cardId")),
            *card_lookup_keys(card.get("illustrationId")),
            *card_lookup_keys(card.get("image")),
            character_lookup_key(card.get("characterId")),
        ]:
            remember_best_name(names_by_key, key, name)

        pokemon = card.get("pokemon")
        if isinstance(pokemon, dict):
            evolves_from = render_localized_rich_text(pokemon.get("evolvesFrom"), localization_texts)
            remember_best_name(
                names_by_key,
                character_lookup_key(pokemon.get("evolvesFromCharacterId")),
                evolves_from,
            )

    return names_by_key


def lookup_best_card_name(context: ConversionContext, card: dict[str, Any], fallback: str | None) -> str | None:
    if fallback is not None and not is_corrupt_text(fallback):
        return fallback

    for key in [
        *card_lookup_keys(card.get("cardId")),
        *card_lookup_keys(card.get("illustrationId")),
        *card_lookup_keys(card.get("image")),
    ]:
        name = context.card_name_by_key.get(key)
        if name and not is_corrupt_text(name):
            return name

    return fallback


def lookup_best_character_name(context: ConversionContext, character_id: str | None, fallback: str | None) -> str | None:
    if fallback is not None and not is_corrupt_text(fallback):
        return fallback

    key = character_lookup_key(character_id)
    name = context.card_name_by_key.get(key or "")
    if name and not is_corrupt_text(name):
        return name
    return fallback


def trim_pack_separator(value: str) -> str:
    return re.sub(r"^\s*[:：]\s*", "", value).strip()


def normalize_pack_punctuation(value: str) -> str:
    return re.sub(r"\s*[:：]\s*", " ", value).strip()


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", normalize_pack_punctuation(value)).strip()


def longest_common_prefix(values: list[str]) -> str:
    if not values:
        return ""

    prefix = values[0]
    for value in values[1:]:
        while prefix and not value.startswith(prefix):
            prefix = prefix[:-1]
    return prefix


def common_featured_pack_name_prefix(pack_names: list[str]) -> str | None:
    normalized_names = list(dict.fromkeys(normalized_text(name) for name in pack_names if name))
    if len(normalized_names) < 2:
        return None

    prefix = trim_pack_separator(longest_common_prefix(normalized_names))
    if not prefix:
        return None

    for name in normalized_names:
        suffix = trim_pack_separator(name[len(prefix):])
        if not suffix:
            return None

    return prefix


def common_separated_pack_name_prefix(pack_names: list[str]) -> str | None:
    prefixes = []
    for pack_name in pack_names:
        match = re.match(r"^(.+?)\s*[:：]\s*(.+)$", pack_name)
        if not match:
            return None

        prefix, suffix = match.groups()
        if not suffix.strip():
            return None
        prefixes.append(normalized_text(prefix))

    unique_prefixes = set(prefixes)
    if len(unique_prefixes) != 1:
        return None

    return prefixes[0]


def display_name_from_separated_pack_name(pack_name: str, expansion_prefixes: list[str]) -> str | None:
    match = re.match(r"^(.+?)\s*[:：]\s*(.+)$", pack_name)
    if not match:
        return None

    prefix, suffix = match.groups()
    normalized_prefix = normalized_text(prefix)
    for expansion_prefix in [normalized_text(name) for name in expansion_prefixes]:
        if normalized_prefix == expansion_prefix:
            return normalized_text(suffix)

    return normalized_text(pack_name)


def pack_display_name(
    pack_name: str,
    expansion_names: list[str],
    has_featured_cards: bool,
    related_featured_pack_names: list[str],
) -> str:
    inferred_prefix = common_featured_pack_name_prefix(related_featured_pack_names) if has_featured_cards else None
    prefixes = [*expansion_names, inferred_prefix] if inferred_prefix else expansion_names

    separated_name = display_name_from_separated_pack_name(pack_name, prefixes)
    if separated_name is not None:
        return separated_name

    normalized_pack_name = normalized_text(pack_name)
    for expansion_name in sorted((normalized_text(name) for name in prefixes), key=len, reverse=True):
        if normalized_pack_name == expansion_name:
            return normalized_pack_name
        if not normalized_pack_name.startswith(f"{expansion_name} "):
            continue

        suffix = trim_pack_separator(normalized_pack_name[len(expansion_name):])
        if suffix:
            return normalized_text(suffix)

    return normalized_pack_name


def strip_pokemon_ex_suffix(name: str) -> str:
    return re.sub(r"\s*ex$", "", name, flags=re.IGNORECASE).strip()


def is_normal_pack(pack: dict[str, Any]) -> bool:
    pack_id = pack.get("packId")
    return isinstance(pack_id, str) and NORMAL_PACK_MARKER in pack_id


def pack_expansion_id(pack: dict[str, Any]) -> str | None:
    return optional_str(pack.get("expansionId"), "pack.expansionId")


def require_export_packs(export: dict[str, Any]) -> list[dict[str, Any]]:
    return require_object_list(export.get("packs"), "packs")


def iter_normal_pack_entries(packs: list[dict[str, Any]]):
    for pack in packs:
        if is_normal_pack(pack):
            yield pack


def build_expansion_names_by_id(export: dict[str, Any]) -> dict[str, list[str]]:
    rows = require_object_list(export.get("expansions"), "expansions")
    result: dict[str, list[str]] = {}
    for row in rows:
        expansion_id = require_str(row.get("expansionId"), "expansion.expansionId")
        result[expansion_id] = require_string_list(row.get("names"), "expansion.names")
    return result


def build_normal_pack_count_by_expansion_id(packs: list[dict[str, Any]]) -> dict[str, int]:
    pack_ids_by_expansion: dict[str, set[str]] = {}
    for pack in iter_normal_pack_entries(packs):
        expansion_id = pack_expansion_id(pack)
        pack_id = require_str(pack.get("packId"), "pack.packId")
        if not expansion_id:
            continue
        pack_ids_by_expansion.setdefault(expansion_id, set()).add(pack_id)
    return {expansion_id: len(pack_ids) for expansion_id, pack_ids in pack_ids_by_expansion.items()}


def pack_lookup_keys(pack: dict[str, Any]) -> list[str]:
    keys = []
    pack_id = pack.get("packId")
    name_msid = pack.get("nameMSID")
    if isinstance(pack_id, str):
        keys.append(f"packId:{pack_id}")
    if isinstance(name_msid, str):
        keys.append(f"nameMSID:{name_msid}")
    if isinstance(pack_id, str) and isinstance(name_msid, str):
        keys.append(f"pack:{pack_id}:{name_msid}")
    return keys


def build_pack_name_lookup(packs: list[dict[str, Any]]) -> dict[str, str]:
    names_by_key: dict[str, str] = {}
    for pack in iter_normal_pack_entries(packs):
        raw_name = pack.get("name")
        if not isinstance(raw_name, str):
            continue
        for key in pack_lookup_keys(pack):
            remember_best_name(names_by_key, key, raw_name)
    return names_by_key


def lookup_best_pack_raw_name(context: ConversionContext, pack: dict[str, Any]) -> str:
    raw_name = require_str(pack.get("name"), "pack.name")
    if not is_corrupt_text(raw_name):
        return raw_name

    for key in pack_lookup_keys(pack):
        name = context.pack_name_by_key.get(key)
        if name and not is_corrupt_text(name):
            return name

    return raw_name


def build_full_pack_names_by_expansion_id(packs: list[dict[str, Any]], pack_name_by_key: dict[str, str]) -> dict[str, list[str]]:
    names_by_expansion: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for pack in iter_normal_pack_entries(packs):
        expansion_id = pack_expansion_id(pack)
        if not expansion_id:
            continue
        name = require_str(pack.get("name"), "pack.name")
        for key in pack_lookup_keys(pack):
            candidate = pack_name_by_key.get(key)
            if candidate and not is_corrupt_text(candidate):
                name = candidate
                break
        if name in seen.setdefault(expansion_id, set()):
            continue
        seen[expansion_id].add(name)
        names_by_expansion.setdefault(expansion_id, []).append(name)
    return names_by_expansion


def featured_pack_display_name(pack: dict[str, Any], context: ConversionContext) -> str | None:
    for card_id in require_string_list(pack.get("featuredCardIds"), "pack.featuredCardIds"):
        for key in card_lookup_keys(card_id):
            name = context.card_name_by_key.get(key)
            if not name:
                continue

            display_name = strip_pokemon_ex_suffix(name)
            if not is_corrupt_text(display_name):
                return display_name

    return None


def display_pack_name(pack: dict[str, Any], context: ConversionContext, *, use_featured_name: bool = True) -> str | None:
    if not is_normal_pack(pack):
        return None

    raw_name = lookup_best_pack_raw_name(context, pack)
    expansion_id = pack_expansion_id(pack)
    expansion_names = context.expansion_names_by_id.get(expansion_id or "", [])
    is_multi_pack_expansion = context.normal_pack_count_by_expansion_id.get(expansion_id or "", 0) > 1
    featured_name = featured_pack_display_name(pack, context) if use_featured_name and is_multi_pack_expansion else None
    if featured_name:
        return featured_name

    return pack_display_name(
        raw_name,
        expansion_names,
        has_featured_cards=is_multi_pack_expansion and bool(pack.get("featuredCardIds")),
        related_featured_pack_names=context.full_pack_names_by_expansion_id.get(expansion_id or "", []),
    )


def convert_packs(value: Any, context: ConversionContext) -> list[str]:
    names = set()
    for pack in require_object_list(value, "packs"):
        name = display_pack_name(pack, context)
        if name:
            names.add(require_clean_str(name, "pack name"))
    return sorted(names)


def pack_sku_id(pack: dict[str, Any]) -> str:
    # 变更原因：包图文件以游戏资源 skuId 命名，不能从展示名或排序推断。
    return require_clean_str(pack.get("skuId"), "pack.skuId")


def set_pack_entry(pack: dict[str, Any], context: ConversionContext, code: str, set_name: str) -> dict[str, str] | None:
    name = set_pack_display_name(pack, context, code, set_name)
    if not name:
        return None
    return {
        "name": require_clean_str(name, "set pack name"),
        "skuId": pack_sku_id(pack),
    }


def build_conversion_context(export: dict[str, Any], cards: list[dict[str, Any]]) -> ConversionContext:
    localization_texts = export.get("localizationTexts")
    if not isinstance(localization_texts, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in localization_texts.items()
    ):
        raise ValueError("localizationTexts must be an object of strings")

    top_level_packs = require_export_packs(export)
    pack_name_by_key = build_pack_name_lookup(top_level_packs)

    return ConversionContext(
        localization_texts=localization_texts,
        expansion_names_by_id=build_expansion_names_by_id(export),
        normal_pack_count_by_expansion_id=build_normal_pack_count_by_expansion_id(top_level_packs),
        full_pack_names_by_expansion_id=build_full_pack_names_by_expansion_id(top_level_packs, pack_name_by_key),
        card_name_by_key=build_card_name_lookup(cards, localization_texts),
        pack_name_by_key=pack_name_by_key,
    )


def converted_card_name(card: dict[str, Any], context: ConversionContext) -> str:
    raw_name = require_str(card.get("name"), "name")
    rendered = render_localized_rich_text(raw_name, context.localization_texts)
    name = lookup_best_card_name(context, card, rendered)
    return require_clean_str(name, "name")


def convert_pokemon(card: dict[str, Any], context: ConversionContext) -> dict[str, Any]:
    pokemon = card.get("pokemon")
    if not isinstance(pokemon, dict):
        raise ValueError(f"pokemon payload missing for {card.get('set')} #{card.get('number')}")

    record: dict[str, Any] = {
        "set": require_str(card.get("set"), "set"),
        "number": require_int(card.get("number"), "number"),
        "name": converted_card_name(card, context),
        "rarity": require_str(card.get("rarity"), "rarity"),
        "image": require_image(card.get("image")),
        "packs": convert_packs(card.get("packs"), context),
        "element": map_value(ENERGY_TYPES, pokemon.get("element"), "element"),
        "type": "pokemon",
        "stage": map_value(STAGES, pokemon.get("stage"), "stage"),
        "health": require_int(pokemon.get("health"), "health"),
        "retreatCost": require_int(pokemon.get("retreatCost"), "retreatCost"),
        "weakness": pokemon.get("weakness"),
    }

    if record["weakness"] is not None:
        record["weakness"] = require_str(record["weakness"], "weakness")

    raw_evolves_from = pokemon.get("evolvesFrom")
    rendered_evolves_from = render_localized_rich_text(raw_evolves_from, context.localization_texts)
    evolves_from = lookup_best_character_name(
        context,
        pokemon.get("evolvesFromCharacterId"),
        rendered_evolves_from,
    )
    record["evolvesFrom"] = None if evolves_from is None else require_clean_str(evolves_from, "evolvesFrom")

    return ordered_record(record)


def require_image(value: Any) -> str:
    image = require_str(value, "image")
    if not image.endswith(".webp"):
        raise ValueError(f"image must end with .webp: {image}")
    return image


def convert_trainer(card: dict[str, Any], context: ConversionContext) -> dict[str, Any]:
    trainer = card.get("trainer")
    if not isinstance(trainer, dict):
        raise ValueError(f"trainer payload missing for {card.get('set')} #{card.get('number')}")

    trainer_type = map_value(TRAINER_TYPES, trainer.get("type"), "trainer type")
    record: dict[str, Any] = {
        "set": require_str(card.get("set"), "set"),
        "number": require_int(card.get("number"), "number"),
        "name": converted_card_name(card, context),
        "rarity": require_str(card.get("rarity"), "rarity"),
        "image": require_image(card.get("image")),
        "packs": convert_packs(card.get("packs"), context),
        "type": trainer_type,
    }

    if trainer_type == "Fossil":
        record["stage"] = "basic"

    return ordered_record(record)


def natural_key(card: dict[str, Any]) -> tuple[str, int]:
    return (card["set"], card["number"])


def natural_code_key(code: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", code)]


def natural_text_key(value: str) -> list[int | str]:
    return natural_code_key(value)


def convert_cards_extra(export: dict[str, Any]) -> list[dict[str, Any]]:
    if export.get("schemaVersion") != 3:
        raise ValueError("frida-test exporter schemaVersion must be 3 raw metadata")

    language = require_str(export.get("language"), "language")
    if "_" in language:
        raise ValueError(f"language must use hyphen form: {language}")

    cards = export.get("cards")
    if not isinstance(cards, list):
        raise ValueError("cards must be an array")
    if not all(isinstance(card, dict) for card in cards):
        raise ValueError("card must be an object")

    context = build_conversion_context(export, cards)
    converted: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for card in cards:
        kind = require_str(card.get("kind"), "kind")
        if kind == "pokemon":
            record = convert_pokemon(card, context)
        elif kind == "trainer":
            record = convert_trainer(card, context)
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


def language_key(language: str) -> str:
    if language not in LANGUAGE_KEY_MAP:
        raise ValueError(f"unsupported language: {language}")
    return LANGUAGE_KEY_MAP[language]


def expansion_display_name(expansion: dict[str, Any]) -> str:
    code = require_str(expansion.get("expansionId"), "expansion.expansionId")
    names = require_string_list(expansion.get("names"), "expansion.names")
    for name in names[:2]:
        if name.strip():
            return require_clean_str(name, "expansion.name")
    # 变更原因：PROMO-A/B 在 MemoryDatabase 中没有本地化名，sets 仍需稳定输出可识别名称。
    return code


def pack_names_for_expansion(top_level_packs: list[dict[str, Any]], context: ConversionContext, code: str) -> list[str]:
    names = []
    seen = set()
    for pack in top_level_packs:
        if pack_expansion_id(pack) != code or not is_normal_pack(pack):
            continue
        name = lookup_best_pack_raw_name(context, pack)
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def set_pack_display_name(
    pack: dict[str, Any],
    context: ConversionContext,
    code: str,
    set_name: str,
) -> str | None:
    if not is_normal_pack(pack):
        return None

    raw_name = lookup_best_pack_raw_name(context, pack)
    if code.startswith("PROMO-"):
        # 变更原因：PROMO pack 的 Vol. 名称是原始业务名，不能被 common-prefix 逻辑裁成数字。
        return normalized_text(raw_name)

    # 变更原因：ExpansionTable 只有 code 时，sets.json 仍要用 PackMaster 推导出的系列名剥离子包前缀。
    return pack_display_name(
        raw_name,
        [set_name],
        has_featured_cards=False,
        related_featured_pack_names=[],
    )


def inferred_set_name_from_pack_names(code: str, expansion: dict[str, Any], pack_names: list[str]) -> str | None:
    if code.startswith("PROMO-") or not pack_names:
        return None

    if len(pack_names) > 1:
        # 变更原因：B1 这类包名的冒号前缀才是系列名，先归一成空格会把后缀里的 Mega 误并入系列名。
        separated_prefix = common_separated_pack_name_prefix(pack_names)
        if separated_prefix:
            return require_clean_str(separated_prefix, "set name")

    names = [require_clean_str(normalized_text(name), "pack name") for name in pack_names]
    if len(names) > 1:
        prefix = common_featured_pack_name_prefix(names)
        if prefix:
            return require_clean_str(prefix, "set name")
        return None

    [raw_name] = pack_names
    match = re.match(r"^(.+?)\s*[:：]\s*(.+)$", raw_name)
    expansion_names = require_string_list(expansion.get("names"), "expansion.names")
    if match:
        prefix, _ = match.groups()
        normalized_prefix = normalized_text(prefix)
        if normalized_prefix in {normalized_text(name) for name in expansion_names if name.strip()}:
            return require_clean_str(normalized_prefix, "set name")

    return require_clean_str(normalized_text(raw_name), "set name")


def set_display_name(expansion: dict[str, Any], pack_names: list[str]) -> str:
    code = require_str(expansion.get("expansionId"), "expansion.expansionId")
    inferred_name = inferred_set_name_from_pack_names(code, expansion, pack_names)
    if inferred_name:
        return inferred_name
    return expansion_display_name(expansion)


def convert_sets(export: dict[str, Any], cards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """從 raw export 和已轉換 cards 生成 sets.json 結構。"""
    language = require_str(export.get("language"), "language")
    name_key = language_key(language)
    expansions = require_object_list(export.get("expansions"), "expansions")
    # 变更原因：sets.json.packs 必须来自 PackMaster 顶层列表，缺失时不能回退到错误的 card.packs 聚合。
    top_level_packs = require_export_packs(export)
    context = build_conversion_context(export, require_object_list(export.get("cards"), "cards"))

    cards_by_set: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        set_code = require_str(card.get("set"), "card.set")
        cards_by_set.setdefault(set_code, []).append(card)

    grouped: dict[str, list[dict[str, Any]]] = {}
    seen_codes: set[str] = set()
    for expansion in expansions:
        code = require_str(expansion.get("expansionId"), "expansion.expansionId")
        if code in seen_codes:
            raise ValueError(f"duplicate set code: {code}")
        seen_codes.add(code)

        set_cards = cards_by_set.get(code, [])
        if not set_cards:
            continue

        pack_names = pack_names_for_expansion(top_level_packs, context, code)
        display_name = set_display_name(expansion, pack_names)
        pack_entries_by_name = {
            entry["name"]: entry
            for pack in top_level_packs
            if pack_expansion_id(pack) == code and is_normal_pack(pack)
            for entry in [set_pack_entry(pack, context, code, display_name)]
            if entry is not None
        }
        packs = sorted(
            pack_entries_by_name.values(),
            key=lambda item: natural_text_key(item["name"]),
        )
        record = {
            "code": code,
            "releaseDate": None,
            "count": len(set_cards),
            "name": {name_key: display_name},
            "packs": packs,
        }
        grouped.setdefault(code[0], []).append(record)

    return {
        group_key: sorted(group_items, key=lambda item: natural_code_key(item["code"]))
        for group_key, group_items in sorted(grouped.items(), key=lambda item: item[0])
    }


def collect_stream(stream: TextIO, chunks: list[str], echo: bool) -> None:
    try:
        for chunk in iter(stream.readline, ""):
            chunks.append(chunk)
            if echo:
                sys.stderr.write(chunk)
                sys.stderr.flush()
    finally:
        stream.close()


def run_exporter(frida_test_dir: Path) -> dict[str, Any]:
    if not frida_test_dir.is_dir():
        raise ValueError(f"frida-test dir does not exist: {frida_test_dir}")
    if not (frida_test_dir / "package.json").is_file():
        raise ValueError(f"frida-test dir missing package.json: {frida_test_dir}")
    if not (frida_test_dir / "src/cli/index.ts").is_file():
        raise ValueError(f"frida-test dir missing src/cli/index.ts: {frida_test_dir}")

    command_display = " ".join(EXPORT_COMMAND)
    # Frida 卡住时必须实时看到内层阶段日志；capture_output 会把关键 stderr 吞到超时后。
    sys.stderr.write(f"[update-metadata] running: {command_display}\n")
    sys.stderr.flush()
    started_at = time.monotonic()
    process = subprocess.Popen(
        EXPORT_COMMAND,
        cwd=frida_test_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("failed to capture frida-test exporter output")

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    # stdout 里有最终 JSON，不能直接转发；stderr 只放诊断日志，可以实时透出。
    stdout_thread = threading.Thread(target=collect_stream, args=(process.stdout, stdout_chunks, False))
    stderr_thread = threading.Thread(target=collect_stream, args=(process.stderr, stderr_chunks, True))
    stdout_thread.start()
    stderr_thread.start()

    try:
        return_code = process.wait(timeout=EXPORT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        # 超时后先杀子进程再拼 preview，否则 Frida/tsx 残留会继续占着设备会话。
        process.kill()
        process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        elapsed = time.monotonic() - started_at
        raise TimeoutError(
            f"frida-test exporter timed out after {elapsed:.1f}s\n"
            f"command: {command_display}\n"
            f"stdout preview: {preview_text(stdout)}\n"
            f"stderr preview: {preview_text(stderr)}"
        ) from error

    stdout_thread.join()
    stderr_thread.join()
    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)
    elapsed = time.monotonic() - started_at
    sys.stderr.write(f"[update-metadata] exporter exited with code {return_code} after {elapsed:.1f}s\n")
    sys.stderr.flush()

    if GAME_LAUNCHED_MESSAGE in stderr:
        raise ExportDeferred(GAME_LAUNCHED_MESSAGE)

    if return_code != 0:
        raise RuntimeError(
            "frida-test exporter failed\n"
            f"command: {command_display}\n"
            f"exit code: {return_code}\n"
            f"stdout preview: {preview_text(stdout)}\n"
            f"stderr preview: {preview_text(stderr)}"
        )

    return parse_exporter_stdout(stdout, stderr, command_display)


def write_cards_extra(root: Path, language: str, cards: list[dict[str, Any]]) -> Path:
    require_str(language, "language")
    out_path = root / "metadata" / "cards" / language / "cards.extra.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(out_path)
    return out_path


def write_sets(root: Path, language: str, sets: dict[str, list[dict[str, Any]]]) -> Path:
    require_str(language, "language")
    out_path = root / "metadata" / "sets" / language / "sets.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(sets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(out_path)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update PTCGP metadata from frida-test")
    parser.add_argument(
        "--frida-test-dir",
        type=Path,
        default=None,
        help="frida-test 仓库目录（缺省时自动探测，优先 FRIDA_TEST_DIR 环境变量）",
    )
    args = parser.parse_args(argv)

    # 缺省自动探测，避免硬编码路径
    if args.frida_test_dir is None:
        from scripts.resolve_env import resolve_frida_test_dir
        args.frida_test_dir = resolve_frida_test_dir()

    try:
        export = run_exporter(args.frida_test_dir)
    except ExportDeferred as error:
        print(error, file=sys.stderr)
        return 0

    cards = convert_cards_extra(export)
    sets = convert_sets(export, cards)
    language = require_str(export.get("language"), "language")
    cards_output = write_cards_extra(Path.cwd(), language, cards)
    sets_output = write_sets(Path.cwd(), language, sets)
    print(f"wrote {cards_output}")
    print(f"wrote {sets_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
