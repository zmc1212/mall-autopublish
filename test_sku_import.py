import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from web_fill import pipeline, sku_import


TEMPLATE = Path(__file__).resolve().parent / "templates" / "sku_import_50012720.xls"


class SkuImportTests(unittest.TestCase):
    def test_generates_from_seller_template_with_exact_columns(self):
        payload = {
            "category_id": "50012720",
            "spec_name": "商品规格",
            "thickness": "0.05mm",
            "skus": [
                {"name": "甲", "price": 9.9, "stock": 20},
                {"name": "乙", "price": 12, "stock": 0, "merchant_code": "B-02"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            generated = sku_import.build_import_file(payload, TEMPLATE, Path(directory))
            self.assertEqual(generated.suffix, ".xls")
            self.assertEqual(generated.read_bytes()[:2], b"PK")
            with generated.open("rb") as stream:
                workbook = load_workbook(stream)
            self.assertEqual(len(workbook.worksheets), 2)
            self.assertEqual(workbook.worksheets[1].sheet_state, "hidden")
            rows = list(workbook.worksheets[0].values)
            self.assertEqual(rows[0], sku_import.HEADERS)
            self.assertEqual(rows[1][:6], (None, None, None, "甲", 9.9, 20))
            self.assertEqual(rows[2][3:7], ("乙", 12, 0, "B-02"))

    def test_only_matching_category_uses_template(self):
        base = {"skus": [{"name": "甲"}], "spec_name": "商品规格"}
        self.assertTrue(sku_import.supports_product({**base, "category_id": "50012720"}))
        self.assertFalse(sku_import.supports_product({**base, "category_id": "other"}))
        self.assertFalse(sku_import.supports_product({**base, "category_id": "50012720", "spec_name": "颜色分类"}))

    def test_missing_entry_seeds_one_sku_and_retries(self):
        payload = {"skus": [{"name": "甲"}]}
        with patch.object(sku_import, "build_import_file", return_value=Path("sku.xls")), \
             patch.object(pipeline, "_write_progress"):
            responses = [{"unavailable": True}, {"ok": True}, {"uploaded": True}, {"verified": True}]
            with patch.object(pipeline, "run_script", side_effect=responses) as run:
                self.assertTrue(pipeline.import_skus_from_template(object(), payload, []))
                self.assertEqual([call.args[1] for call in run.call_args_list],
                                 ["sku_import.js", "skus.js", "sku_import.js", "sku_import.js"])

    def test_missing_entry_after_seed_pauses_instead_of_filling_all(self):
        payload = {"skus": [{"name": "甲"}, {"name": "乙"}]}
        with patch.object(sku_import, "build_import_file", return_value=Path("sku.xls")), \
             patch.object(pipeline, "_write_progress"):
            responses = [{"unavailable": True}, {"ok": True}, {"unavailable": True}]
            with patch.object(pipeline, "run_script", side_effect=responses) as run:
                with self.assertRaisesRegex(RuntimeError, "PAUSE:未找到 SKU 批量导入入口"):
                    pipeline.import_skus_from_template(object(), payload, [])
                self.assertEqual(run.call_args_list[1].args[2]["skus"], payload["skus"][:1])

    def test_ambiguous_upload_pauses(self):
        payload = {"skus": [{"name": "甲"}]}
        with patch.object(sku_import, "build_import_file", return_value=Path("sku.xls")), \
             patch.object(pipeline, "_write_progress"):
            with patch.object(pipeline, "run_script", side_effect=[{"uploaded": True}, {"verified": False}]):
                with self.assertRaisesRegex(RuntimeError, "PAUSE:SKU 模板已上传"):
                    pipeline.import_skus_from_template(object(), payload, [])


if __name__ == "__main__":
    unittest.main()
