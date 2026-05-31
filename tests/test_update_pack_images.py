import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from scripts.update_pack_images import (
    SUPPORTED_LANGUAGES,
    convert_archive_bytes,
    crop_pack_icon_canvas,
    extract_archive,
    output_paths_for_pack,
)


class UpdatePackImagesTest(unittest.TestCase):
    def test_crop_pack_icon_canvas_matches_pack_contract(self) -> None:
        image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        for x in range(64, 208):
            for y in range(7, 255):
                image.putpixel((x, y), (255, 0, 0, 255))

        cropped = crop_pack_icon_canvas(image)

        self.assertEqual(cropped.size, (160, 256))
        self.assertEqual(cropped.getchannel("A").getbbox(), (16, 7, 160, 255))

    def test_output_paths_for_pack_all_languages(self) -> None:
        root = Path("/tmp/output")

        paths = output_paths_for_pack(root, "A1_1")

        self.assertEqual(
            paths["body"],
            [root / "images" / language / "packs" / "A1_1.webp" for language in SUPPORTED_LANGUAGES],
        )
        self.assertEqual(
            paths["logos"],
            [root / "images" / language / "packs-logos" / "A1_1.webp" for language in SUPPORTED_LANGUAGES],
        )

    def test_extract_archive_rejects_path_traversal(self) -> None:
        archive_bytes = make_tar({"../evil.txt": b"bad"})

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "escapes temp directory"):
                extract_archive(archive_bytes, Path(temp_dir))

    def test_convert_archive_writes_body_to_all_languages_and_localized_logos(self) -> None:
        manifest = {
            "schemaVersion": 1,
            "packs": [
                {
                    "skuId": "A1_1",
                    "body": {"bundlePath": "bundles/body.bundle"},
                    "logos": [
                        {"language": language, "bundlePath": f"bundles/logo-{language}.bundle"}
                        for language in SUPPORTED_LANGUAGES
                    ],
                }
            ],
        }
        archive_bytes = make_tar(
            {
                "manifest.json": json.dumps(manifest).encode(),
                "bundles/body.bundle": b"body",
                **{f"bundles/logo-{language}.bundle": language.encode() for language in SUPPORTED_LANGUAGES},
            }
        )
        body_image = Image.new("RGBA", (160, 256), (255, 0, 0, 255))
        logo_images = {language: Image.new("RGBA", (10 + index, 20), (0, 0, 255, 255)) for index, language in enumerate(SUPPORTED_LANGUAGES)}

        def fake_select_logo(path: Path) -> Image.Image:
            language = path.stem.removeprefix("logo-")
            return logo_images[language]

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "out"
            with (
                patch("scripts.update_pack_images.select_pack_body", return_value=body_image),
                patch("scripts.update_pack_images.select_pack_logo", side_effect=fake_select_logo),
            ):
                convert_archive_bytes(archive_bytes, output)

            for language in SUPPORTED_LANGUAGES:
                self.assertTrue((output / "images" / language / "packs" / "A1_1.webp").exists())
                self.assertTrue((output / "images" / language / "packs-logos" / "A1_1.webp").exists())


def make_tar(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
