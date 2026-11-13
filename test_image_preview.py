"""商品列表主图预览的目录、ZIP 和路径安全回归测试。"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from desktop import image_preview
from desktop.image_preview import PreviewUnavailable, preview_metadata, read_preview
from desktop.jobs import serialize_row


def _image_bytes(color="red", size=(24, 24)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="JPEG")
    return stream.getvalue()


class ImagePreviewTests(unittest.TestCase):
    def test_directory_uses_existing_pack_parser_and_main_image(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            (folder / "主图01.jpg").write_bytes(_image_bytes())
            (folder / "详情01.jpg").write_bytes(_image_bytes("blue"))

            payload = read_preview({"pack_dir": str(folder)})

            self.assertEqual(payload.name, "主图01.jpg")
            self.assertEqual(payload.media_type, "image/jpeg")
            self.assertEqual(payload.data, (folder / "主图01.jpg").read_bytes())

    def test_zip_with_nested_folder_is_previewed_by_same_parser(self):
        with tempfile.TemporaryDirectory() as raw:
            archive_path = Path(raw) / "商品图片.zip"
            image = _image_bytes("green")
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("商品A/主图01.jpg", image)

            payload = read_preview({"pack_dir": str(archive_path)})

            self.assertEqual(payload.name, "主图01.jpg")
            self.assertEqual(payload.data, image)

    def test_zip_path_traversal_does_not_expose_files(self):
        with tempfile.TemporaryDirectory() as raw:
            archive_path = Path(raw) / "恶意.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../主图01.jpg", _image_bytes())

            with self.assertRaises(PreviewUnavailable):
                read_preview({"pack_dir": str(archive_path)})
            self.assertFalse((Path(raw).parent / "主图01.jpg").exists())

    def test_serialized_row_exposes_cache_busted_preview_url(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            (folder / "主图01.jpg").write_bytes(_image_bytes())
            row = serialize_row({
                "row": 7,
                "product_id": "商品-7",
                "product": {"product_id": "商品-7", "title": "测试", "pack_dir": str(folder)},
                "pack_fingerprint": "fingerprint-1",
            })

            self.assertTrue(row["preview_available"])
            self.assertEqual(row["preview_name"], "主图01.jpg")
            self.assertIn("/api/item/preview?", row["preview_url"])
            self.assertIn("row=7", row["preview_url"])
            self.assertIn("product_id=%E5%95%86%E5%93%81-7", row["preview_url"])
            self.assertIn("v=", row["preview_url"])
            self.assertNotIn(str(folder), row["preview_url"])

    def test_main_01_takes_priority_over_other_main_groups(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            for name in ("宝贝主图01.jpg", "主图02.jpg", "主图01.jpg"):
                (folder / name).write_bytes(_image_bytes())
            self.assertEqual(read_preview({"pack_dir": raw}).name, "主图01.jpg")
            self.assertEqual(read_preview({
                "pack_dir": raw,
                "main_images": [str(folder / "主图02.jpg"), str(folder / "主图01.jpg")],
            }).name, "主图01.jpg")

    def test_repeated_metadata_uses_cached_directory_and_zip_selection(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            (folder / "主图01.jpg").write_bytes(_image_bytes())
            archive_path = folder / "图片包.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("主图01.jpg", _image_bytes())
            for pack_path, scanner in ((folder, "_scan_directory"), (archive_path, "_zip_selected_member")):
                with self.subTest(pack=pack_path), patch.object(image_preview, scanner, wraps=getattr(image_preview, scanner)) as scan:
                    product = {"pack_dir": str(pack_path)}
                    for _ in range(5):
                        self.assertTrue(preview_metadata(product)["available"])
                    self.assertEqual(scan.call_count, 1)

    def test_replacing_main_image_changes_version_without_directory_change(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            path = folder / "主图01.jpg"
            path.write_bytes(_image_bytes())
            product = {"pack_dir": raw}
            first = preview_metadata(product)
            stat = path.stat()
            path.write_bytes(_image_bytes("blue"))
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            self.assertNotEqual(first["cache_token"], preview_metadata(product)["cache_token"])

    def test_oversized_main_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "主图01.jpg"
            path.write_bytes(_image_bytes())
            with patch.object(image_preview, "MAX_PREVIEW_BYTES", 32):
                with self.assertRaisesRegex(PreviewUnavailable, "过大"):
                    read_preview({"pack_dir": raw, "main_images": [str(path)]})


if __name__ == "__main__":
    unittest.main()

