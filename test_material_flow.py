import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from web_fill import material_flow as flow


class MaterialFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = self.root / "source.jpg"
        self.image.write_bytes(b"test-image")
        self.product = {"title": "测试", "skus": [{"name": "蓝杆", "image": str(self.image), "price": 6.9, "stock": 10}]}
        self.row = {"name": "蓝杆", "sku_id": "6141276652863", "price": "6.90", "stock": "10", "image": "https://img.alicdn.com/a.jpg", "search_title": "-"}
        self.state = self.root / "state.json"

    def test_folder_order_and_identity(self):
        self.product["skus"].append({**self.product["skus"][0], "name": "白杆"})
        folder = flow.build_folder(self.product, "1085270103015", self.root)
        self.assertEqual([x.name for x in sorted(folder.iterdir())], ["0001_蓝杆.jpg", "0002_白杆.jpg"])
        self.assertEqual((folder / "0001_蓝杆.jpg").read_bytes(), b"test-image")
        (folder / "extra.xlsx").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "额外"):
            flow.build_folder(self.product, "1085270103015", self.root)

    def test_unsafe_or_duplicate_filenames_fail_before_browser(self):
        for name in ("../blue", "CON", "蓝/杆", "", "blue."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                flow.validate({**self.product, "skus": [{**self.product["skus"][0], "name": name}]})
        with self.assertRaisesRegex(ValueError, "重复"):
            flow.validate({**self.product, "skus": self.product["skus"] * 2})

    def test_ai_missing_extra_changed_rows_are_rejected(self):
        for rows in ([], [self.row, self.row], [{**self.row, "name": "其他"}], [{**self.row, "price": "7"}], [{**self.row, "stock": "9"}], [{**self.row, "sku_id": "6141276652999"}], [{**self.row, "image": ""}], [{**self.row, "search_title": "AI标题"}]):
            with self.subTest(rows=rows), self.assertRaises(RuntimeError):
                flow.check_rows(rows, self.product, [self.row], images=True)

    def test_changed_image_invalidates_checkpoint(self):
        initial = flow.fingerprint(self.product)
        self.image.write_bytes(b"changed")
        self.assertNotEqual(initial, flow.fingerprint(self.product))

    def test_preflight_does_not_connect(self):
        with patch.object(flow.pipeline, "_load_web") as load:
            self.assertEqual(flow.run(self.product, self.state)["stage"], "preflight")
            load.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_id_only_from_submission_result_or_official_success_url(self):
        self.assertEqual(flow.item_id_from_result({"url":"https://item.upload.taobao.com/sell/v2/success.htm?primaryId=1085270103015"}), "1085270103015")
        self.assertEqual(flow.item_id_from_result({"url":"https://evil.test/success.htm?primaryId=1085270103015"}), "")
        self.assertEqual(flow.item_id_from_result({"execution":"提交失败", "taobao_item_id":"1085270103015"}), "")

    def fake_run(self, responses, stage="new", item_id=""):
        if stage != "new":
            flow.save(self.state, {"fingerprint":flow.fingerprint(self.product), "stage":stage,
                                  **({"item_id":item_id} if item_id else {}), "baseline":[self.row], "preview":[self.row]})
        session = Mock()
        session.tab_list.return_value = "0 " + flow.SKU_URL
        web = Mock(unsafe=True)
        session.cancel_event = None
        web.SessionLost = RuntimeError
        return session, web

    def test_new_run_checkpoints_before_submit_and_adopt(self):
        session, web = self.fake_run([])
        observed = []
        def submit(*args):
            observed.append(json.loads(self.state.read_text(encoding="utf-8"))["stage"])
            return {"taobao_item_id":"1085270103015", "execution":"结果待核实"}
        def script(session, name, payload, timeout):
            if payload["phase"] == "adopt":
                observed.append(json.loads(self.state.read_text(encoding="utf-8"))["stage"])
            return {"ready":True, "rows":[self.row]}
        with patch.object(flow.pipeline, "_load_web", return_value=web), \
             patch.object(flow.pipeline, "fill_new_product", return_value={"execution":"已填写未提交"}) as fill, \
             patch.object(flow.pipeline, "_finish_publish", side_effect=submit), \
             patch.object(flow.pipeline, "run_script", side_effect=script):
            result = flow.run(self.product, self.state, execute=True, session=session)
        self.assertEqual(result["stage"], "complete")
        self.assertEqual(observed, ["submit_pending", "material_adopt_pending"])
        self.assertTrue(fill.call_args.kwargs["skip_spec_images"])
        self.assertFalse(fill.call_args.kwargs["confirm_submit"])

    def test_unknown_submit_never_resubmits(self):
        session, web = self.fake_run([], stage="submit_pending")
        with patch.object(flow.pipeline, "_load_web", return_value=web), \
             patch.object(flow.pipeline, "fill_new_product") as fill, \
             patch.object(flow.pipeline, "_finish_publish") as submit:
            with self.assertRaisesRegex(RuntimeError, "禁止自动重复"):
                flow.run(self.product, self.state, execute=True, session=session)
            fill.assert_not_called()
            submit.assert_not_called()

    def test_resume_adoption_only_verifies_never_uploads_or_builds(self):
        session, web = self.fake_run([], stage="adopt_pending", item_id="1085270103015")
        with patch.object(flow.pipeline, "_load_web", return_value=web), \
             patch.object(flow.pipeline, "fill_new_product") as fill, \
             patch.object(flow.pipeline, "run_script", return_value={"rows":[self.row]}) as script:
            result = flow.run(self.product, self.state, execute=True, session=session)
            self.assertEqual(result["stage"], "complete")
            self.assertEqual([x.args[2]["phase"] for x in script.call_args_list], ["verify"])
            fill.assert_not_called()

    def test_completed_run_has_no_browser_side_effects(self):
        self.fake_run([], stage="complete", item_id="1085270103015")
        with patch.object(flow.pipeline, "_load_web") as load:
            self.assertEqual(flow.run(self.product, self.state, execute=True)["stage"], "complete")
            load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
