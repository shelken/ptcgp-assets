#!/usr/bin/env python3
"""從 PTCGP bridge 取得卡包資源，輸出全語言 WebP 圖片。"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import UnityPy
from PIL import Image

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.22f1"

SUPPORTED_LANGUAGES = [
    "en-US",
    "ja-JP",
    "zh-TW",
    "de-DE",
    "es-ES",
    "fr-FR",
    "it-IT",
    "ko-KR",
    "pt-BR",
]
REQUEST_TIMEOUT_SECONDS = 180
BRIDGE_START_TIMEOUT_SECONDS = 45


@dataclass(frozen=True)
class PackImageArchive:
    manifest: dict[str, Any]
    root: Path


def crop_pack_icon_canvas(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("pack icon texture has no visible alpha")
    if rgba.width < 160 or rgba.height < 256:
        raise ValueError(f"pack icon texture too small: {rgba.width}x{rgba.height}")
    left = max(0, bbox[2] - 160)
    if left + 160 > rgba.width:
        left = rgba.width - 160
    return rgba.crop((left, 0, left + 160, 256))


def output_paths_for_pack(root: Path, sku_id: str) -> dict[str, list[Path]]:
    return {
        "body": [root / "images" / language / "packs" / f"{sku_id}.webp" for language in SUPPORTED_LANGUAGES],
        "logos": [root / "images" / language / "packs-logos" / f"{sku_id}.webp" for language in SUPPORTED_LANGUAGES],
    }


def request_pack_images_raw(
    bridge_url: str,
    *,
    sku_id: str | None = None,
    limit: int | None = None,
    skip: int | None = None,
) -> bytes:
    params: dict[str, Any] = {}
    if sku_id is not None:
        params["skuId"] = sku_id
    if limit is not None:
        params["limit"] = limit
    if skip is not None:
        params["skip"] = skip
    payload = json.dumps({"method": "ptcgp.packImages.raw", "params": params}).encode("utf-8")
    request = urllib.request.Request(
        f"{bridge_url.rstrip('/')}/ptcgp/run",
        data=payload,
        headers={"content-type": "application/json"},
        method="POST",
    )
    print(f"[pack-images] requesting method=ptcgp.packImages.raw url={bridge_url} params={params}")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"bridge request failed status={error.code}: {body}") from error


def safe_member_path(root: Path, member_name: str) -> Path:
    path = root / member_name
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(f"archive member escapes temp directory: {member_name}")
    return path


def extract_archive(archive_bytes: bytes, root: Path) -> PackImageArchive:
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                raise ValueError(f"archive member must be regular file: {member.name}")
            target = safe_member_path(root, member.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"archive member cannot be read: {member.name}")
            target.write_bytes(source.read())

    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise ValueError("archive missing manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1 or not isinstance(manifest.get("packs"), list):
        raise ValueError("archive manifest has invalid schema")
    return PackImageArchive(manifest=manifest, root=root)


def extract_images_from_bundle(bundle_path: Path) -> list[tuple[str, Image.Image]]:
    env = UnityPy.load(str(bundle_path))
    images: list[tuple[str, Image.Image]] = []
    for obj in env.objects:
        if obj.type.name not in {"Texture2D", "Sprite"}:
            continue
        data = obj.read()
        image = getattr(data, "image", None)
        if image is not None:
            images.append((obj.type.name, image))
    if not images:
        raise ValueError(f"bundle has no Texture2D/Sprite image: {bundle_path}")
    return images


def select_pack_body(bundle_path: Path) -> Image.Image:
    texture_images = [item for item in extract_images_from_bundle(bundle_path) if item[0] == "Texture2D"]
    if not texture_images:
        raise ValueError(f"pack body bundle has no Texture2D: {bundle_path}")
    source = max(texture_images, key=lambda item: item[1].width * item[1].height)[1]
    return crop_pack_icon_canvas(source)


def select_pack_logo(bundle_path: Path) -> Image.Image:
    images = extract_images_from_bundle(bundle_path)
    sprite_images = [item for item in images if item[0] == "Sprite"]
    source = max(sprite_images or images, key=lambda item: item[1].width * item[1].height)[1]
    return source.convert("RGBA")


def write_webp(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="WEBP", quality=95, lossless=False)
    print(f"[pack-images] wrote {path} size={image.width}x{image.height}")


def logo_by_language(pack: dict[str, Any]) -> dict[str, str]:
    logos = pack.get("logos")
    if not isinstance(logos, list):
        raise ValueError(f"pack logos must be list: {pack.get('skuId')}")
    result: dict[str, str] = {}
    for logo in logos:
        if not isinstance(logo, dict):
            raise ValueError(f"pack logo must be object: {pack.get('skuId')}")
        language = logo.get("language")
        bundle_path = logo.get("bundlePath")
        if not isinstance(language, str) or not isinstance(bundle_path, str):
            raise ValueError(f"pack logo missing language/bundlePath: {pack.get('skuId')}")
        result[language] = bundle_path
    missing = [language for language in SUPPORTED_LANGUAGES if language not in result]
    if missing:
        raise ValueError(f"pack missing logos for languages {missing}: {pack.get('skuId')}")
    return result


def convert_archive_bytes(archive_bytes: bytes, output_root: Path) -> int:
    import tempfile

    converted = 0
    with tempfile.TemporaryDirectory(prefix="ptcgp-pack-images-") as temp_dir:
        archive = extract_archive(archive_bytes, Path(temp_dir))
        for pack in archive.manifest["packs"]:
            if not isinstance(pack, dict):
                raise ValueError("pack manifest entry must be object")
            sku_id = pack.get("skuId")
            body = pack.get("body")
            if not isinstance(sku_id, str) or not isinstance(body, dict) or not isinstance(body.get("bundlePath"), str):
                raise ValueError(f"pack manifest missing skuId/body: {pack}")

            print(f"[pack-images] converting skuId={sku_id}")
            body_image = select_pack_body(archive.root / body["bundlePath"])
            for language in SUPPORTED_LANGUAGES:
                write_webp(body_image, output_root / "images" / language / "packs" / f"{sku_id}.webp")

            logos = logo_by_language(pack)
            for language in SUPPORTED_LANGUAGES:
                logo_image = select_pack_logo(archive.root / logos[language])
                write_webp(logo_image, output_root / "images" / language / "packs-logos" / f"{sku_id}.webp")
            converted += 1
    return converted


def convert_from_bridge(
    bridge_url: str,
    output_root: Path,
    *,
    sku_id: str | None,
    limit: int | None,
    chunk_size: int,
) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk-size must be positive")
    if sku_id is not None or limit is not None:
        archive_bytes = request_pack_images_raw(bridge_url, sku_id=sku_id, limit=limit)
        convert_archive_bytes(archive_bytes, output_root)
        return

    skip = 0
    while True:
        archive_bytes = request_pack_images_raw(bridge_url, limit=chunk_size, skip=skip)
        converted = convert_archive_bytes(archive_bytes, output_root)
        if converted == 0:
            break
        skip += converted


def wait_for_bridge(bridge_url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + BRIDGE_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"bridge process exited early with code {process.returncode}")
        try:
            request_pack_images_raw(bridge_url, limit=1)
            return
        except Exception:
            time.sleep(1)
    raise TimeoutError("bridge did not respond in time")


def start_bridge(command: str, cwd: Path | None) -> subprocess.Popen[bytes]:
    print(f"[pack-images] starting bridge command={command}")
    return subprocess.Popen(command.split(), cwd=cwd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8765")
    parser.add_argument("--bridge-command", default=None, help="optional command used when bridge-url is unavailable（缺省自动探测）")
    parser.add_argument("--bridge-cwd", type=Path, default=None, help="bridge 工作目录（缺省自动探测）")
    parser.add_argument("--output", type=Path, default=Path("."))
    parser.add_argument("--sku-id", default=None, help="optional debug filter; default exports all packs")
    parser.add_argument("--limit", type=int, default=None, help="optional debug limit; default exports all packs")
    parser.add_argument("--chunk-size", type=int, default=1, help="packs requested per bridge call when exporting all packs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # 缺省自动探测 bridge command/cwd，避免手动构造
    if args.bridge_command is None:
        from scripts.resolve_env import resolve_frida_test_dir, resolve_bridge_command, resolve_bridge_cwd
        frida_dir = resolve_frida_test_dir()
        args.bridge_command = resolve_bridge_command(frida_dir)
        if args.bridge_cwd is None:
            args.bridge_cwd = resolve_bridge_cwd(frida_dir)

    process: subprocess.Popen[bytes] | None = None
    try:
        try:
            convert_from_bridge(args.bridge_url, args.output, sku_id=args.sku_id, limit=args.limit, chunk_size=args.chunk_size)
        except Exception:
            if args.bridge_command is None:
                raise
            process = start_bridge(args.bridge_command, args.bridge_cwd)
            wait_for_bridge(args.bridge_url, process)
            convert_from_bridge(args.bridge_url, args.output, sku_id=args.sku_id, limit=args.limit, chunk_size=args.chunk_size)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
