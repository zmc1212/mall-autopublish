import subprocess
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

    def test_chaowan_template_clears_examples_and_fills_fixed_columns(self):
        payload = {
            "category_id": "122692006",
            "spec_name": "款式描述",
            "skus": [
                {"name": "单个随机盲盒", "price": 9.9, "stock": 20},
                {"name": "端盒【12个盲盒，款式齐全】", "price": 9.9, "stock": 20, "merchant_code": "B-02"},
            ],
        }
        template = Path(__file__).resolve().parent / "templates" / "sku_import_122692006.xls"
        with tempfile.TemporaryDirectory() as directory:
            generated = sku_import.build_import_file(payload, template, Path(directory))
            with generated.open("rb") as stream:
                workbook = load_workbook(stream)
            sheet = workbook.worksheets[0]
            self.assertEqual(sku_import.CATEGORY_CONFIGS["122692006"]["headers"],
                             tuple(sheet.cell(3, index).value for index in range(1, 11)))
            # 卖家模板自带的 5 行示例数据必须被清除，只保留生成的 2 行。
            self.assertEqual(sheet.max_row, 5)
            self.assertEqual(tuple(sheet.cell(4, index).value for index in range(1, 5)),
                             ("单个随机盲盒", "正版发售", None, 9.9))
            self.assertEqual(sheet.cell(4, 8).value, 1)
            self.assertEqual(tuple(sheet.cell(5, index).value for index in range(1, 7)),
                             ("端盒【12个盲盒，款式齐全】", "正版发售", None, 9.9, 20, "B-02"))

    def test_chaowan_ignores_sku_category_but_batch_import_stays_off(self):
        # 潮玩盲盒走 skus.js 内联规格流程；批量导入模板仅在显式开启
        # sku_template_import 且类目命中时使用（发布页弹窗不收外部模板）。
        payload = {
            "category_id": "122692006",
            "spec_name": "款式描述",
            "skus": [{"name": "单个随机盲盒", "price": 9.9, "stock": 20}],
        }
        self.assertFalse(sku_import.needs_sku_category(payload))
        self.assertTrue(sku_import.supports_product(payload))
        self.assertFalse(sku_import.supports_product({**payload, "spec_name": "商品规格"}))
        self.assertTrue(sku_import.needs_sku_category(
            {**payload, "category_id": "50012720", "spec_name": "商品规格"}))

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
            responses = [{"uploaded": True}, {"verified": False, "error": "无法核实识别结果"}]
            with patch.object(pipeline, "run_script", side_effect=responses) as run:
                with self.assertRaisesRegex(RuntimeError, "PAUSE:SKU 模板已上传"):
                    pipeline.import_skus_from_template(object(), payload, [])
                self.assertEqual([call.args[2]["phase"] for call in run.call_args_list], ["open", "verify"])

    def test_verify_timeout_reveals_window_and_reruns_once(self):
        """verify 烧穿预算（页面冻结）时先还原窗口再安全重跑一次 verify。"""
        payload = {"skus": [{"name": "甲"}]}
        with patch.object(sku_import, "build_import_file", return_value=Path("sku.xls")), \
             patch.object(pipeline, "_write_progress"), \
             patch.object(pipeline, "_ensure_automation_front") as ensure, \
             patch("time.sleep"):
            responses = [
                {"uploaded": True},
                subprocess.TimeoutExpired(cmd="run-code", timeout=120),
                {"verified": True, "count": 1, "matched": 1},
            ]
            with patch.object(pipeline, "run_script", side_effect=responses) as run:
                self.assertTrue(pipeline.import_skus_from_template(object(), payload, []))
            self.assertEqual([call.args[2]["phase"] for call in run.call_args_list],
                             ["open", "verify", "verify"])
            ensure.assert_called_once()

    def test_verify_timeout_twice_pauses_with_original_notice(self):
        payload = {"skus": [{"name": "甲"}]}
        with patch.object(sku_import, "build_import_file", return_value=Path("sku.xls")), \
             patch.object(pipeline, "_write_progress"), \
             patch.object(pipeline, "_ensure_automation_front"), \
             patch("time.sleep"):
            responses = [
                {"uploaded": True},
                subprocess.TimeoutExpired(cmd="run-code", timeout=120),
                subprocess.TimeoutExpired(cmd="run-code", timeout=120),
            ]
            with patch.object(pipeline, "run_script", side_effect=responses):
                with self.assertRaisesRegex(
                        RuntimeError, "PAUSE:SKU 模板已上传但结果未核实.*页面操作超时"):
                    pipeline.import_skus_from_template(object(), payload, [])

    def test_verify_user_pause_not_retried(self):
        """用户暂停不是失败，禁止再跑一次 verify（避免重新驱动已暂停的页面）。"""
        payload = {"skus": [{"name": "甲"}]}
        with patch.object(sku_import, "build_import_file", return_value=Path("sku.xls")), \
             patch.object(pipeline, "_write_progress"), \
             patch.object(pipeline, "_ensure_automation_front"):
            responses = [
                {"uploaded": True},
                RuntimeError("PAUSE:用户已暂停；保留当前发布页，点击继续可接着填写"),
            ]
            with patch.object(pipeline, "run_script", side_effect=responses) as run:
                with self.assertRaisesRegex(RuntimeError, "用户已暂停"):
                    pipeline.import_skus_from_template(object(), payload, [])
            self.assertEqual(len(run.call_args_list), 2)


if __name__ == "__main__":
    unittest.main()
