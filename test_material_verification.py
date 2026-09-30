import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from web_fill import material_import as importer
from web_fill.material_verification import evaluate


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        image = Path(self.tmp.name) / "blue.jpg"
        image.write_bytes(b"local-image-fixture")
        self.item_id, self.sku_id = "1085482487262", "6141513508545"
        self.product = {"title": "中性笔", "category_id": "50012720", "skus": [
            {"name": "蓝杆", "price": 999, "stock": 999, "image": str(image)}]}
        row = {"sku_id": self.sku_id, "name": "蓝杆", "price": "9.90", "stock": "20",
               "attributes": {"颜色分类": "蓝色"}, "search_title": "", "merchant_code": "001",
               "search_image": "", "spec_image": ""}
        def snapshot():
            return {"item_id": self.item_id, "evidence_ref": "capture-1", "rows": [copy.deepcopy(row)]}
        self.evidence = {"item_id": self.item_id, "product": self.product, "before": snapshot(),
                         "preview": snapshot(), "after": snapshot(),
                         "template_rule": {"confirmed": True, "evidence_ref": "rule-capture",
                                           "description": "test fixture only"}}
        self.evidence["after"].update(reloaded_search=True, reopened_editor=True, processing_complete=True)
        sha = hashlib.sha256(image.read_bytes()).hexdigest()
        for phase in ("preview", "after"):
            r = self.evidence[phase]["rows"][0]
            for kind in ("search", "spec"):
                r[kind + "_image"] = "https://img.alicdn.com/blue.jpg"
                r[kind + "_match"] = {"sku_id": self.sku_id, "image": r[kind + "_image"],
                    "source_sha256": sha, "matched": True, "method": "visual", "evidence_ref": "comparison"}

    def test_candidate_uses_server_values_not_stale_local_price(self):
        result = evaluate(self.evidence)
        self.assertEqual(result["conclusion"], "candidate")
        self.assertFalse(result["default_strategy_changed"])

    def test_search_only_is_not_replacement(self):
        self.evidence["after"]["rows"][0]["spec_image"] = ""
        self.assertEqual(evaluate(self.evidence)["conclusion"], "not_replacement")

    def test_image_presence_is_not_content_match(self):
        self.evidence["after"]["rows"][0].pop("spec_match")
        self.assertEqual(evaluate(self.evidence)["conclusion"], "inconclusive")

    def test_no_missing_baseline_cannot_prove_sync(self):
        self.evidence["before"]["rows"][0]["spec_image"] = "already-present"
        self.assertEqual(evaluate(self.evidence)["conclusion"], "inconclusive")

    def test_rule_and_reload_and_completion_required(self):
        for target, key in (("template_rule", "confirmed"), ("after", "reopened_editor"),
                            ("after", "processing_complete"), ("after", "reloaded_search")):
            data = copy.deepcopy(self.evidence)
            data[target][key] = False
            self.assertEqual(evaluate(data)["conclusion"], "inconclusive")

    def test_non_image_changes_are_reported(self):
        for phase in ("preview", "after"):
            for field, value in (("attributes", {}), ("merchant_code", "002"), ("search_title", "AI"),
                                 ("price", "1"), ("stock", "0"), ("name", "错误SKU")):
                data = copy.deepcopy(self.evidence)
                data[phase]["rows"][0][field] = value
                result = evaluate(data)
                self.assertEqual(result["conclusion"], "inconclusive")
                self.assertTrue(result["non_image_differences"])

    def test_id_must_remain_text(self):
        self.evidence["before"]["rows"][0]["sku_id"] = int(self.sku_id)
        self.assertIn("数字文本", evaluate(self.evidence)["reason"])

    def test_duplicates_and_wrong_sku_fail(self):
        data = copy.deepcopy(self.evidence)
        data["before"]["rows"] *= 2
        self.assertEqual(evaluate(data)["conclusion"], "inconclusive")
        self.evidence["after"]["rows"][0]["sku_id"] = "6141513508999"
        self.assertEqual(evaluate(self.evidence)["conclusion"], "inconclusive")

    def test_changed_local_image_invalidates_proof(self):
        Path(self.product["skus"][0]["image"]).write_bytes(b"changed")
        self.assertEqual(evaluate(self.evidence)["conclusion"], "inconclusive")


class ResumeTests(unittest.TestCase):
    def test_recognizing_and_verifying_resume_without_reupload(self):
        for stage in (importer.STAGE_RECOGNIZING, importer.STAGE_VERIFYING):
            observed = []
            with patch.object(importer, "upload_materials") as upload, \
                 patch.object(importer, "await_recognition", return_value=[]) as recognize, \
                 patch.object(importer, "review_materials") as adopt, \
                 patch.object(importer, "verify_materials", return_value=[]) as verify:
                result = importer.run_material_flow(Mock(), Mock(), {"title": "test"}, "1085482487262",
                    {"stage": stage}, on_stage=lambda name, state: observed.append(name))
            self.assertEqual(result["stage"], importer.STAGE_COMPLETE)
            upload.assert_not_called()
            verify.assert_called_once()
            if stage == importer.STAGE_VERIFYING:
                recognize.assert_not_called()
                adopt.assert_not_called()
            else:
                recognize.assert_called_once()
                self.assertIn(importer.STAGE_ADOPT_PENDING, observed)

    def test_captcha_preserves_recognizing_stage(self):
        saved = []
        with patch.object(importer, "await_recognition", side_effect=RuntimeError("PAUSE:安全验证")), \
             patch.object(importer, "upload_materials") as upload:
            with self.assertRaisesRegex(RuntimeError, "安全验证"):
                importer.run_material_flow(Mock(), Mock(), {"title": "test"}, "1085482487262",
                    {"stage": importer.STAGE_RECOGNIZING},
                    on_stage=lambda name, state: saved.append(copy.deepcopy(state)))
        self.assertEqual(saved[-1]["stage"], importer.STAGE_RECOGNIZING)
        self.assertIn("安全验证", saved[-1]["error"])
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
