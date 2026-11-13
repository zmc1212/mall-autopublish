import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from web_fill import material_import


class MaterialImportTests(unittest.TestCase):
    def setUp(self):
        self.product = {
            "title": "测试商品",
            "skus": [{"name": "蓝杆", "price": 6.9, "stock": 10}],
        }
        self.baseline = [{
            "name": "蓝杆", "sku_id": "6141276652863", "price": "6.90",
            "stock": "10", "search_title": "-",
            "attributes_text": "书写粗细: 0.05mm", "merchant_code": "SKU-1",
            "image": "",
        }]

    def test_known_preview_attribute_placeholder_is_recorded(self):
        preview = [{**self.baseline[0], "attributes_text": "-", "image": "https://img.alicdn.com/blue.jpg"}]

        material_import.check_rows(
            preview, self.product, self.baseline, images=True,
            allow_preview_attributes=True,
        )

        self.assertEqual(preview[0]["preview_attribute_diff"], {
            "field": "attributes_text",
            "baseline": "书写粗细: 0.05mm",
            "preview": "-",
            "reason": "preview_placeholder",
        })
        self.assertIn("自动采纳后核对服务器属性", material_import._preview_attribute_notice(preview))

    def test_preview_attribute_allowance_does_not_relax_other_fields_or_server_verify(self):
        unknown = [{**self.baseline[0], "attributes_text": "书写粗细: 0.07mm"}]
        with self.assertRaisesRegex(RuntimeError, "属性或商家编码"):
            material_import.check_rows(
                unknown, self.product, self.baseline,
                allow_preview_attributes=True,
            )

        changed_merchant = [{**self.baseline[0], "attributes_text": "-", "merchant_code": "SKU-2"}]
        with self.assertRaisesRegex(RuntimeError, "属性或商家编码"):
            material_import.check_rows(
                changed_merchant, self.product, self.baseline,
                allow_preview_attributes=True,
            )

        server_changed = [{**self.baseline[0], "attributes_text": "-", "image": "https://img.alicdn.com/blue.jpg"}]
        with self.assertRaisesRegex(RuntimeError, "属性或商家编码"):
            material_import.check_rows(
                server_changed, self.product, self.baseline, images=True,
            )

    def test_uncertain_adoption_advances_to_server_verification_without_second_adopt(self):
        preview = [{
            **self.baseline[0], "attributes_text": "-",
            "image": "https://img.alicdn.com/blue.jpg",
            "preview_attribute_diff": {
                "field": "attributes_text", "baseline": "书写粗细: 0.05mm",
                "preview": "-", "reason": "preview_placeholder",
            },
        }]
        calls = []
        stages = []

        def script(_session, _web, _item_id, _title, phase, **_extra):
            calls.append(phase)
            if phase == "preview":
                return {"ready": True, "rows": [{**self.baseline[0], "attributes_text": "-",
                                                   "image": "https://img.alicdn.com/blue.jpg"}]}
            if phase == "adopt":
                return {"adopted": False, "uncertain": True,
                        "notice": "采纳结果待核实"}
            if phase == "verify":
                return {"rows": [{**self.baseline[0],
                                   "image": "https://img.alicdn.com/blue.jpg"}]}
            raise AssertionError(phase)

        def on_stage(stage, state):
            stages.append((stage, state.get("preview")))

        with mock.patch.object(material_import, "ensure_sku_tab"), \
             mock.patch.object(material_import, "_script", side_effect=script), \
             mock.patch.object(material_import, "_save_material_adopt_receipt"):
            result = material_import.run_material_flow(
                object(), object(), self.product, "1085270103015",
                {"stage": material_import.STAGE_REVIEWED,
                 "baseline": self.baseline, "preview": preview},
                on_stage=on_stage,
            )

        self.assertEqual(result["stage"], material_import.STAGE_COMPLETE)
        self.assertEqual(calls, ["preview", "adopt", "verify"])
        self.assertEqual(
            [stage for stage, _preview in stages],
            [material_import.STAGE_ADOPT_PENDING,
             material_import.STAGE_VERIFYING,
             material_import.STAGE_COMPLETE],
        )

    def test_adopt_receipt_is_separate_from_verify_artifact(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            preview = [dict(self.baseline[0])]

            def script(_session, _web, _item_id, _title, phase, **_extra):
                if phase == "preview":
                    return {"ready": True, "rows": [dict(preview[0])]}
                if phase == "adopt":
                    return {"adopted": False, "uncertain": True,
                            "notice": "采纳结果待核实"}
                raise AssertionError(phase)

            with mock.patch.object(material_import, "ensure_sku_tab"), \
                 mock.patch.object(material_import, "_script", side_effect=script), \
                 mock.patch.object(material_import.pipeline, "get_output", return_value=output):
                result = material_import.review_materials(
                    object(), object(), "1085270103015", self.product["title"],
                    self.baseline, preview,
                )

            receipt_path = output / "web_fill_material_adopt_receipt.json"
            self.assertTrue(receipt_path.is_file())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["item_id"], "1085270103015")
            self.assertEqual(receipt["result"], result)
            self.assertIsInstance(receipt["recorded_at"], float)

            # The generic result written by the later verify phase has a
            # different name and cannot replace this click receipt.
            (output / "web_fill_material_import.json").write_text(
                json.dumps({"phase": "verify"}), encoding="utf-8"
            )
            self.assertEqual(
                json.loads(receipt_path.read_text(encoding="utf-8")), receipt
            )

    def test_server_verify_uses_owned_fresh_tab_and_restores_drawer_page(self):
        class Session:
            def __init__(self):
                # Resume after inspect_material=False starts on the edit page;
                # the verifier must select the owned SKU page first.
                self.tabs = [
                    ["https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1085270103015", True],
                    [material_import.SKU_URL, False],
                ]
                self.actions = []

            def tab_list(self):
                return "\n".join(
                    f"- {index}: {'(current) ' if current else ''}({url})"
                    for index, (url, current) in enumerate(self.tabs)
                )

            def tab_new(self, url):
                self.actions.append(("new", url))
                self.tabs = [[old, False] for old, _current in self.tabs]
                self.tabs.append([url, True])

            def tab_close(self, index):
                self.actions.append(("close", index))
                self.tabs.pop(int(index))

            def tab_select(self, index):
                self.actions.append(("select", index))
                for position, (url, _current) in enumerate(self.tabs):
                    self.tabs[position][1] = position == int(index)

        session = Session()
        calls = []

        def script(_session, _web, _item_id, _title, phase, **extra):
            calls.append((phase, extra))
            if phase == "guard":
                return {"guarded": True}
            if phase == "verify":
                return {"rows": [{**self.baseline[0], "image": "https://img.alicdn.com/blue.jpg"}]}
            raise AssertionError(phase)

        with mock.patch.object(material_import, "_script", side_effect=script):
            rows = material_import.verify_materials(
                session, object(), "1085270103015", self.product["title"],
                self.product, self.baseline, self.baseline,
            )

        self.assertEqual(rows[0]["image"], "https://img.alicdn.com/blue.jpg")
        self.assertEqual([phase for phase, _extra in calls], ["guard", "verify"])
        self.assertTrue(calls[1][1]["fresh"])
        self.assertEqual(
            session.actions,
            [("select", 1), ("new", material_import.SKU_URL),
             ("close", 2), ("select", 1)],
        )
        self.assertEqual(
            session.tabs,
            [["https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1085270103015", False],
             [material_import.SKU_URL, True]],
        )

    def test_server_verify_does_not_open_new_tab_when_old_page_is_blocked(self):
        class Session:
            def __init__(self):
                self.tabs = [[material_import.SKU_URL, True]]
                self.opened = 0

            def tab_list(self):
                return f"- 0: (current) ({material_import.SKU_URL})"

            def tab_select(self, _index):
                pass

            def tab_new(self, _url):
                self.opened += 1

        session = Session()

        def blocked(_session, _web, _item_id, _title, phase, **_extra):
            if phase == "guard":
                raise RuntimeError("PAUSE:安全验证阻断")
            raise AssertionError(phase)

        with mock.patch.object(material_import, "_script", side_effect=blocked), \
             self.assertRaisesRegex(RuntimeError, "安全验证阻断"):
            material_import.verify_materials(
                session, object(), "1085270103015", self.product["title"],
                self.product, self.baseline, self.baseline,
            )

        self.assertEqual(session.opened, 0)


if __name__ == "__main__":
    unittest.main()
