import unittest
import unittest.mock
from pathlib import Path

import web_fill
from web_fill import pipeline


class FakeSession:
    def __init__(self, href="https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720", tabs=None):
        self._href = href
        self._tabs = list(tabs) if tabs is not None else [href]
        self.calls = []
        self.uploads = []

    def attach(self):
        self.calls.append(("attach",))
        return self._href

    def href(self):
        return self._href

    def body_text(self, limit=4000):
        return "商品发布 如夏盛园文具店"

    def snapshot(self):
        return """
- radio "立刻上架" [ref=a1]
- radio "定时上架" [ref=a2]
- radio "放入仓库" [checked] [ref=a3]
- button "提交宝贝信息" [ref=a4]
"""

    def tab_list(self):
        self.calls.append(("tab-list",))
        return "\n".join(f"{index} {url}" for index, url in enumerate(self._tabs))

    def tab_new(self, url=None):
        self.calls.append(("tab-new", url))
        if url:
            self._tabs.append(url)
            self._href = url
        return "ok"

    def tab_select(self, index):
        self.calls.append(("tab-select", index))
        idx = int(index)
        if 0 <= idx < len(self._tabs):
            self._href = self._tabs[idx]
        return "ok"

    def upload_files(self, *paths, timeout=120):
        self.uploads.extend(paths)
        self.calls.append(("upload",) + paths)
        return "ok"

    def press(self, key):
        self.calls.append(("press", key))
        return "ok"

    def cmd(self, *args, raw=True, timeout=60):
        self.calls.append(args)
        if args and args[0] == "run-code":
            return '### Result\n{"ok": true}\n### Ran Playwright code\n'
        if args and args[0] == "tab-new":
            self._href = args[1]
            if args[1] not in self._tabs:
                self._tabs.append(args[1])
            return "ok"
        if args and args[0] == "tab-list":
            return self.tab_list()
        if args and args[0] == "tab-select":
            self.tab_select(args[1])
            return "ok"
        return "ok"

    def click(self, ref):
        self.calls.append(("click", ref))

    def detach(self):
        self.calls.append(("detach",))


class WebFillTests(unittest.TestCase):
    def setUp(self):
        patcher = unittest.mock.patch.object(pipeline, "_prune_tabs", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
    def test_payload_uses_absolute_paths_and_sku_slots(self):
        pack = Path(__file__).resolve().parent / "testdata"
        image = next(p for p in pack.rglob("颜色01-*.jpg"))
        product = {
            "title": "卡游火影忍者中性笔盲盒忍道版",
            "brand": "卡游",
            "model": "忍道版第1弹",
            "category": "文具用品/文化用品/商务用品>>笔类/书写工具>>中性笔",
            "attributes": {"笔头类型": "子弹头"},
            "skus": [{"slot": "颜色01", "name": "特别款", "image": image, "price": 9.9, "stock": 20}],
            "main_images": [image],
            "thickness": "0.05mm",
        }
        payload = web_fill.product_to_payload(product)
        self.assertEqual(payload["leaf"], "中性笔")
        self.assertEqual(payload["attributes"]["IP联名"], "火影忍者")
        self.assertTrue(payload["skus"][0]["image"].replace("\\", "/").endswith(image.name))
        self.assertEqual(payload["skus"][0]["slot"], "颜色01")
        self.assertEqual(web_fill.product_to_payload({**product, "sku_category": "单品"})["sku_category"], "单品")
        self.assertEqual(payload["skus"][0]["file"], image.name)
        self.assertTrue(Path(payload["main_images"][0]).is_file())

    def test_scripts_are_parameterized_and_avoid_drop(self):
        for name in ("category.js", "attributes.js", "skus.js", "sku_category.js", "spec_images.js", "main_images.js", "details.js", "logistics.js"):
            text = (pipeline.SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn("/*PAYLOAD*/", text)
            self.assertNotIn("page.goto(\"https://item.upload.taobao.com/sell/ai/category.htm\"", text)
            self.assertNotIn(".drop(", text)
            self.assertNotIn("waitForEvent(\"filechooser\"", text)
        helpers = (pipeline.SCRIPTS / "_helpers.inc.js").read_text(encoding="utf-8")
        self.assertIn("scenario-widget", helpers)
        self.assertIn("clickUnblocked", helpers)
        self.assertIn("pictureSpaceFrame", helpers)
        self.assertIn("pickPictureSpaceCards", helpers)
        self.assertIn("retryUntilUploaded", helpers)
        self.assertIn("网络错误", helpers)
        self.assertIn("成功上传", helpers)
        self.assertIn("escape === false", helpers)
        specs = (pipeline.SCRIPTS / "spec_images.js").read_text(encoding="utf-8")
        self.assertIn("targetColumn = \"商品规格\"", specs)
        self.assertIn("sell-color-option-image-empty", specs)
        self.assertIn("filledCount", specs)
        self.assertIn("persistedImageState", specs)
        self.assertIn("saved", specs)
        self.assertIn('verifiedBy = tableSaved ? "sku-table"', specs)
        self.assertIn("clickVisibleDrawerConfirm", specs)
        self.assertIn("button:visible", specs)
        self.assertNotIn('button.click({ force: true, timeout: 8000 })', specs)
        self.assertIn("规格图未保存到SKU表格", specs)
        self.assertIn("escape: false", specs)
        self.assertIn("SKU搜索主图", specs)
        self.assertNotIn("sell-component-sku-images", specs)
        self.assertNotIn("bindFromTable", specs)
        self.assertNotIn("maskOverlay", specs)
        self.assertNotIn('trim() === "批量填写"', specs)
        details = (pipeline.SCRIPTS / "details.js").read_text(encoding="utf-8")
        self.assertIn("openPictureSpace", details)
        self.assertIn("via: \"library\"", details)
        self.assertIn("retryUntilUploaded", details)
        self.assertNotIn('trim() === "上传图片"', details)
        click_upload = (pipeline.SCRIPTS / "click_upload_btn.js").read_text(encoding="utf-8")
        self.assertIn("上传文件", click_upload)
        category = (pipeline.SCRIPTS / "category.js").read_text(encoding="utf-8")
        self.assertIn("clickUnblocked", category)
        self.assertIn("dismissKnow", category)
        self.assertIn("搜索发品", category)
        self.assertIn("开启", category)
        self.assertIn("openSearchPublish", category)
        self.assertNotIn('getByRole("combobox", { name: "请输入" }).first().click()', category)
        attributes = (pipeline.SCRIPTS / "attributes.js").read_text(encoding="utf-8")
        self.assertIn("sell-component-info-wrapper-label", attributes)
        self.assertIn("setDefaultTimeout", attributes)
        self.assertIn("findAttrCombo", helpers)
        self.assertIn("__qnCommitted", helpers)
        self.assertIn("pickComboValue", attributes)
        self.assertIn("hideDraftOverlays", helpers)
        self.assertIn("sell-component-item-prop-item", helpers)
        self.assertIn("pickInsideItem", helpers)
        self.assertIn("__qnItem", helpers)
        self.assertNotIn("following::input[@role='combobox']", helpers)
        self.assertIn("typeOverlaySearch", helpers)
        self.assertIn("属性值反馈", helpers)
        self.assertIn("typeSpecName", (pipeline.SCRIPTS / "skus.js").read_text(encoding="utf-8"))
        skus = (pipeline.SCRIPTS / "skus.js").read_text(encoding="utf-8")
        self.assertIn("box.fill(want)", skus)
        self.assertIn("keyboard.insertText(want)", skus)
        self.assertNotIn("box.type(String(name)", skus)
        self.assertIn("skip-next-ready", category)

    def test_playwright_evaluate_passes_single_argument(self):
        import re
        bad = []
        for path in pipeline.SCRIPTS.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            if re.search(r"\.evaluate\(\([A-Za-z_][\w]*\s*,\s*[A-Za-z_]", text):
                bad.append(path.name)
        self.assertEqual(bad, [])

    def test_cli_error_text_strips_ansi(self):
        raw = "TimeoutError: \x1b[2mwaiting for getByRole\x1b[22m"
        self.assertEqual(pipeline.strip_cli_text(raw), "TimeoutError: waiting for getByRole")

    def test_sku_evaluate_wraps_multiple_args(self):
        text = (pipeline.SCRIPTS / "skus.js").read_text(encoding="utf-8")
        self.assertNotIn("}, kind, value)", text)
        self.assertIn("wantKind: kind", text)
        self.assertIn("{ wantKind, already }", text)

    def test_fill_submits_only_when_confirmed(self):
        session = FakeSession()
        product = {
            "title": "卡游",
            "brand": "卡游",
            "category": "中性笔",
            "skus": [],
            "main_images": [],
            "detail_images": [],
        }
        names = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "submit.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/success.htm?primaryId=1086638256748&catId=50012720"
                return {
                    "hasSuccess": True,
                    "hasFail": False,
                    "text": "商品提交成功 商品ID: 1086638256748, 您可以在商品列表中根据商品 ID搜索找到该商品。",
                    "itemId": "1086638256748",
                    "catId": "50012720",
                    "href": session_obj._href,
                }
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=True)
        self.assertIn("submit.js", names)
        self.assertEqual(result["execution"], "结果待核实")
        self.assertEqual(result["taobao_item_id"], "1086638256748")
        self.assertIn("item.htm?id=1086638256748", result["view_url"])
        self.assertIn("itemId=1086638256748", result["edit_url"])
        names.clear()
        session = FakeSession()
        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertNotIn("submit.js", names)
        self.assertEqual(result["execution"], "已填写未提交")

    def test_fill_opens_new_tab_and_never_submits(self):
        session = FakeSession()
        product = {
            "title": "卡游火影忍者中性笔盲盒忍道版",
            "brand": "卡游",
            "category": "中性笔",
            "attributes": {"笔头类型": "子弹头"},
            "skus": [],
            "main_images": [],
            "detail_images": [],
            "ship_time": "48小时内发货",
            "freight": "文具用品 包邮",
        }

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertEqual(result["execution"], "已填写未提交")
        self.assertFalse(any(call[0] == "tab-new" for call in session.calls))
        self.assertFalse(any(len(call) > 1 and call[0] == "goto" for call in session.calls))
        self.assertFalse(any("drop" in str(call) for call in session.calls))
        self.assertEqual(session.calls.count(("click", "a4")), 0)

    def test_fill_opens_new_tab_from_home(self):
        session = FakeSession(href="https://myseller.taobao.com/home.htm/QnworkbenchHome/")
        product = {
            "title": "卡游",
            "brand": "卡游",
            "category": "中性笔",
            "skus": [],
            "main_images": [],
            "detail_images": [],
        }

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertEqual(result["execution"], "已填写未提交")
        self.assertTrue(any(call[0] == "tab-new" for call in session.calls))

    def test_fill_reuses_open_category_tab(self):
        session = FakeSession(href="https://item.upload.taobao.com/sell/ai/category.htm")
        how = []

        def fake_run(session_obj, name, payload, timeout=120):
            how.append(name)
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            pipeline.fill_new_product(session, {"title": "卡游", "category": "中性笔"}, confirm_submit=False)
        self.assertFalse(any(call[0] == "tab-new" for call in session.calls))
        self.assertIn("category.js", how)

    def test_fill_handles_spec_image_filechooser(self):
        session = FakeSession()
        product = {
            "title": "卡游",
            "brand": "卡游",
            "category": "中性笔",
            "skus": [{"slot": "颜色01", "name": "特别款", "image": "a.jpg", "price": 9.9, "stock": 1}],
            "main_images": [],
            "detail_images": [],
        }

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "spec_images.js" and payload.get("phase") == "open":
                raise pipeline.FileChooserNeeded("### Modal state\n- [File chooser]: can be handled by upload")
            return {"ok": True, "uploaded": True, "script": name, "phase": payload.get("phase")}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertNotEqual(result["execution"], "暂停")
        self.assertTrue(any(call[0] == "upload" for call in session.calls))
        self.assertFalse(result.get("errors"))

    def test_spec_images_unbound_detects_empty_bind(self):
        payload = {"skus": [{"name": "特别款", "image": "a.jpg"}]}
        empty = {
            "bind": {
                "bindLog": [{"name": "特别款", "skuClick": "NO_DIALOG", "picClick": {"ok": False}}],
                "filledCount": 0,
            }
        }
        self.assertTrue(pipeline.spec_images_unbound(empty, payload))
        self.assertFalse(pipeline.spec_images_unbound({"bind": {"ok": True, "phase": "bind"}}, payload))
        self.assertFalse(pipeline.spec_images_unbound({"open": {"uploaded": True}}, payload))

    def test_spec_images_saved_state_is_authoritative(self):
        payload = {"skus": [{"name": "特别款", "image": "a.jpg"}]}
        failed = {"bind": {"saved": False, "filledCount": 1}}
        passed = {"bind": {"saved": True, "filledCount": 0}}
        self.assertTrue(pipeline.spec_images_unbound(failed, payload))
        self.assertFalse(pipeline.spec_images_unbound(passed, payload))
        self.assertEqual(str(pipeline._spec_unbound_error(failed, payload)), "规格图未保存到SKU表格")
        self.assertTrue(pipeline.gate_error_retryable(pipeline._spec_unbound_error(failed, payload)))

    def test_fill_stops_when_spec_images_not_bound(self):
        session = FakeSession()
        product = {
            "title": "卡游",
            "brand": "卡游",
            "category": "中性笔",
            "skus": [{"slot": "颜色01", "name": "特别款", "image": "a.jpg", "price": 9.9, "stock": 1}],
            "main_images": [],
            "detail_images": [],
        }

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "spec_images.js" and payload.get("phase") not in {"open", "after_upload"}:
                return {
                    "bindLog": [{"name": "特别款", "skuClick": "NO_DIALOG", "picClick": {"ok": False}}],
                    "filledCount": 0,
                    "confirm": "NO_DIALOG",
                }
            return {"ok": True, "uploaded": True, "script": name, "phase": payload.get("phase")}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertEqual(result["execution"], "失败")
        self.assertIn("规格图未绑定", result["notice"])

    def test_spec_images_retry_then_succeed(self):
        session = FakeSession()
        product = {
            "title": "卡游",
            "brand": "卡游",
            "category": "中性笔",
            "skus": [{"slot": "颜色01", "name": "特别款", "image": "a.jpg", "price": 9.9, "stock": 1}],
            "main_images": [],
            "detail_images": [],
        }
        attempts = []

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "spec_images.js" and payload.get("phase") not in {"open", "after_upload"}:
                attempts.append(1)
                if len(attempts) < 3:
                    return {"bindLog": [{"name": "特别款", "picClick": {"ok": False}}], "filledCount": 0}
                return {"targetColumn": "商品规格", "bindLog": [{"name": "特别款", "picClick": {"ok": True}}], "filledCount": 1}
            return {"ok": True, "uploaded": True, "script": name, "phase": payload.get("phase")}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertEqual(result["execution"], "已填写未提交")
        self.assertEqual(len(attempts), 3)

    def test_spec_images_retry_exhaustion_does_not_pause(self):
        session = FakeSession()
        product = {
            "title": "卡游",
            "brand": "卡游",
            "category": "中性笔",
            "skus": [{"slot": "颜色01", "name": "特别款", "image": "a.jpg", "price": 9.9, "stock": 1}],
            "main_images": [],
            "detail_images": [],
        }
        attempts = []

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "spec_images.js" and payload.get("phase") not in {"open", "after_upload"}:
                attempts.append(1)
                return {"bindLog": [{"name": "特别款", "picClick": {"ok": False}}], "filledCount": 0}
            return {"ok": True, "uploaded": True, "script": name, "phase": payload.get("phase")}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertEqual(result["execution"], "失败")
        self.assertEqual(len(attempts), 5)

    def test_filechooser_dump_is_not_user_pause(self):
        dump = "### Ran Playwright code\nthrow new Error(\"PAUSE:滑块\");\n### Modal state\n- [File chooser]: can be handled by upload"
        self.assertFalse(pipeline._is_user_pause(dump))
        self.assertTrue(pipeline._is_user_pause("Error: PAUSE:页面出现滑块验证，请手动完成后重试"))

    def test_auth_blocker_still_pauses_batch(self):
        session = FakeSession()
        products = [
            {"product_id": "A", "title": "A", "category": "中性笔", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "B", "category": "中性笔", "skus": [], "main_images": [], "detail_images": []},
        ]

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False):
            return {"execution": "暂停", "notice": "页面出现验证码", "errors": ["页面出现验证码"], "steps": []}

        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            updated = pipeline.run_batch(products, session=session)
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["execution"], "暂停")

    def test_fill_handles_detail_image_filechooser(self):
        session = FakeSession()
        product = {
            "title": "卡游",
            "brand": "卡游",
            "category": "中性笔",
            "skus": [],
            "main_images": [],
            "detail_images": ["d1.jpg", "d2.jpg"],
        }

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "details.js" and payload.get("phase") == "open":
                raise pipeline.FileChooserNeeded("### Modal state\n- [File chooser]: can be handled by upload")
            if name == "details.js" and payload.get("phase") == "select":
                return {"picked": [{"name": "d1.jpg", "ok": True}], "confirm": "OK", "after": {"imgs": 2, "dialog": False}}
            return {"ok": True, "uploaded": True, "script": name, "phase": payload.get("phase")}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertNotEqual(result["execution"], "暂停")
        self.assertTrue(any(call[0] == "upload" for call in session.calls))
        self.assertFalse(result.get("errors"))

    def test_run_web_batch_uses_web_fill(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("seller", Path(__file__).with_name("千牛自动上架.py"))
        seller = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(seller)
        import inspect
        self.assertIn("web_fill", inspect.getsource(seller.run_web_batch))

    def test_decide_skips_filled_sections(self):
        payload = {
            "title": "卡游火影忍者中性笔盲盒忍道版",
            "skus": [{}] * 16,
            "main_images": ["a.jpg"] * 5,
            "portrait_images": [],
            "detail_images": ["d.jpg"],
        }
        filled = {
            "title": "卡游火影忍者中性笔盲盒忍道版",
            "skuRows": 16,
            "specImgs": 16,
            "mainImgs": 5,
            "p34Imgs": 0,
            "detailImgs": 0,
            "popup": False,
            "specDialog": False,
        }
        self.assertEqual(pipeline.decide_skips(filled, payload), {"skus", "spec_images", "main_images"})
        dialog = {**filled, "specImgs": 3, "specDialog": True, "popup": True, "mainImgs": 0}
        self.assertEqual(pipeline.decide_skips(dialog, payload), {"attributes", "skus"})
        other = {**filled, "title": "得力中性笔"}
        self.assertTrue(pipeline.page_conflicts(other, payload))
        self.assertFalse(pipeline.page_conflicts(filled, payload))
        smoke = {**filled, "title": "卡游火影忍者中性笔自动化冒烟"}
        self.assertTrue(pipeline.page_conflicts(smoke, payload))
        sibling = {**filled, "title": "卡游火影忍者中性笔盲盒忍道版02"}
        self.assertTrue(pipeline.page_conflicts(sibling, payload))

    def test_fill_reuses_publish_tab_from_home(self):
        publish = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
        session = FakeSession(
            href="https://myseller.taobao.com/home.htm/QnworkbenchHome/",
            tabs=["https://myseller.taobao.com/home.htm/QnworkbenchHome/", publish],
        )
        names = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "probe_state.js":
                return {"title": "卡游", "skuRows": 16, "specImgs": 0, "mainImgs": 0, "detailImgs": 0, "popup": True, "specDialog": True}
            if name == "spec_images.js":
                return {"ok": True, "phase": payload.get("phase")}
            return {"ok": True, "script": name}

        product = {
            "title": "卡游",
            "brand": "卡游",
            "category": "中性笔",
            "skus": [{"slot": "颜色01", "name": "特别款", "image": "a.jpg", "price": 9.9, "stock": 1}] * 16,
            "main_images": [],
            "detail_images": [],
        }
        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertEqual(result["execution"], "已填写未提交")
        self.assertFalse(any(call[0] == "tab-new" for call in session.calls))
        self.assertTrue(any(call[0] == "tab-select" for call in session.calls))
        self.assertNotIn("category.js", names)
        self.assertNotIn("skus.js", names)
        self.assertNotIn("attributes.js", names)
        self.assertIn("spec_images.js", names)
        self.assertNotIn("close_overlays.js", names)

    def test_fill_skips_completed_steps_on_resume(self):
        session = FakeSession()
        names = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "probe_state.js":
                return {
                    "title": "卡游火影忍者中性笔盲盒忍道版",
                    "skuRows": 1,
                    "specImgs": 1,
                    "mainImgs": 0,
                    "detailImgs": 0,
                    "popup": False,
                    "specDialog": False,
                }
            return {"ok": True, "script": name}

        product = {
            "title": "卡游火影忍者中性笔盲盒忍道版",
            "brand": "卡游",
            "category": "中性笔",
            "skus": [{"slot": "颜色01", "name": "特别款", "image": "a.jpg", "price": 9.9, "stock": 1}],
            "main_images": ["m.jpg"],
            "detail_images": [],
        }
        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertEqual(result["execution"], "已填写未提交")
        self.assertNotIn("skus.js", names)
        self.assertNotIn("spec_images.js", names)
        self.assertIn("attributes.js", names)
        self.assertIn("main_images.js", names)

    def test_fill_force_new_opens_category(self):
        session = FakeSession()
        names = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            pipeline.fill_new_product(session, {"title": "卡游", "category": "中性笔"}, confirm_submit=False, force_new=True)
        self.assertTrue(any(call[0] == "tab-new" for call in session.calls))
        self.assertIn("category.js", names)
        self.assertNotIn("probe_state.js", names)

    def test_fill_conflict_opens_new_category(self):
        session = FakeSession()
        names = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "probe_state.js":
                return {"title": "得力中性笔", "skuRows": 2, "specImgs": 2, "mainImgs": 1, "popup": False, "specDialog": False}
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            pipeline.fill_new_product(session, {"title": "卡游", "category": "中性笔"}, confirm_submit=False)
        self.assertTrue(any(call[0] == "tab-new" for call in session.calls))
        self.assertIn("category.js", names)
        self.assertIn("attributes.js", names)

    def test_run_batch_skips_done_products(self):
        session = FakeSession()
        called = []

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False):
            called.append(product.get("product_id"))
            return {"execution": "已填写未提交", "notice": "ok", "errors": [], "steps": []}

        products = [
            {"product_id": "A", "title": "卡游A", "execution": "已填写未提交", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "卡游B", "execution": "失败", "skus": [], "main_images": [], "detail_images": []},
        ]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            updated = pipeline.run_batch(products, session=session)
        self.assertEqual(called, ["B"])
        self.assertEqual(updated[0]["execution"], "已填写未提交")
        self.assertEqual(updated[0]["notice"], "已填写，跳过")
        self.assertEqual(updated[1]["product_id"], "B")

    def test_run_batch_second_product_force_new(self):
        session = FakeSession()
        flags = []

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False):
            flags.append((product.get("product_id"), bool(force_new)))
            return {"execution": "已填写未提交", "notice": "ok", "errors": [], "steps": [], "url": "https://item.upload.taobao.com/sell/v2/publish.htm?catId=1"}

        products = [
            {"product_id": "A", "title": "卡游A", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "卡游B", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
        ]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            pipeline.run_batch(products, session=session)
        self.assertEqual(flags, [("A", False), ("B", True)])

    def test_run_batch_skipped_done_then_next_force_new(self):
        session = FakeSession()
        flags = []

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False):
            flags.append((product.get("product_id"), bool(force_new)))
            return {"execution": "已填写未提交", "notice": "ok", "errors": [], "steps": []}

        products = [
            {"product_id": "A", "title": "卡游A", "execution": "已填写未提交", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "卡游B", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
        ]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            pipeline.run_batch(products, session=session)
        self.assertEqual(flags, [("B", True)])

    def test_run_batch_failure_then_next_force_new(self):
        session = FakeSession()
        flags = []

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False):
            flags.append((product.get("product_id"), bool(force_new)))
            if product.get("product_id") == "A":
                return {"execution": "失败", "notice": "x", "errors": ["x"], "steps": []}
            return {"execution": "已填写未提交", "notice": "ok", "errors": [], "steps": []}

        products = [
            {"product_id": "A", "title": "卡游A", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "卡游B", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
        ]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            pipeline.run_batch(products, session=session)
        self.assertEqual(flags, [("A", False), ("B", True)])

    def test_submit_script_collects_item_links(self):
        text = (pipeline.SCRIPTS / "submit.js").read_text(encoding="utf-8")
        self.assertIn("viewUrl", text)
        self.assertIn("editUrl", text)
        self.assertIn("查看商品", text)
        self.assertIn("编辑商品", text)

    def test_action_links_from_success_notice(self):
        import job_session
        notice = "商品发布 帮助 反馈 如夏盛园文具店 小海 运营 商品提交成功 商品ID: 1086638256748, 您可以在商品列表中根据商品 ID搜索找到该商品。 继续发布 查看商品 编辑商品"
        links = job_session.product_action_links(notice=notice)
        self.assertEqual(links["taobao_item_id"], "1086638256748")
        self.assertEqual(links["view_url"], "https://item.taobao.com/item.htm?id=1086638256748")
        self.assertIn("itemId=1086638256748", links["edit_url"])
        captured = job_session.product_action_links(
            submitted={"itemId": "1", "viewUrl": "javascript:void(0)", "editUrl": "https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1"}
        )
        self.assertEqual(captured["view_url"], "https://item.taobao.com/item.htm?id=1")
        self.assertIn("itemId=1", captured["edit_url"])

    def test_warehouse_script_does_not_force_click(self):
        warehouse = (pipeline.SCRIPTS / "warehouse.js").read_text(encoding="utf-8")
        helpers = (pipeline.SCRIPTS / "_helpers.inc.js").read_text(encoding="utf-8")
        logistics = (pipeline.SCRIPTS / "logistics.js").read_text(encoding="utf-8")
        self.assertNotIn("force: true", warehouse)
        self.assertIn("selectWarehouseRadio", warehouse)
        self.assertIn("selectWarehouseRadio", helpers)
        self.assertIn("dispatchEvent", helpers)
        self.assertIn("selectWarehouseRadio", logistics)
        self.assertNotIn('getByRole("radio", { name: "放入仓库" }).click({ force: true })', logistics)

    def test_fill_clears_progress_at_start(self):
        written = []

        def fake_write(steps):
            written.append(list(steps) if isinstance(steps, list) else steps)

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            return {"ok": True, "script": name}

        session = FakeSession()
        with unittest.mock.patch.object(pipeline, "_write_progress", side_effect=fake_write), \
             unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            pipeline.fill_new_product(session, {"title": "卡游", "category": "中性笔"}, confirm_submit=False)
        self.assertTrue(written)
        self.assertEqual(written[0], [])

    def test_submit_notice_drops_help_chrome(self):
        notice = pipeline.short_fail_notice(
            "商品发布 帮助 反馈 如夏盛园文具店 错误(2) 2 商品属性必填项未填 上架时间请根据实际需要选择 帮助 反馈"
        )
        self.assertIn("必填项未填", notice)
        self.assertNotIn("请根据实际需要", notice)
        self.assertNotIn("帮助", notice)
        self.assertNotIn("反馈", notice)

    def test_timeout_notice_is_short(self):
        notice = pipeline.short_fail_notice(
            "Command ['D:\\\\nodejs\\\\node.EXE', 'run-code', '--filename=C:\\\\Users\\\\Administrator\\\\AppData\\\\Roaming\\\\千牛自动上架\\\\logs\\\\playwright\\\\web_fill_attributes.js'] timed out after 120 seconds"
        )
        self.assertEqual(notice, "填写属性超时，请重试")
        self.assertNotIn("node.EXE", notice)
        self.assertEqual(
            pipeline.short_fail_notice("Error: PAUSE:类目页没有品牌输入框，请确认已选择 中性笔"),
            "类目页没有品牌输入框，请确认已选择 中性笔",
        )
        self.assertEqual(
            pipeline.short_fail_notice('PAUSE:规格未写入 忍道版1弹【特别款】1支 {"open":true,"names":[],"addDisabled":true,'),
            "规格未写入 忍道版1弹【特别款】1支",
        )
        self.assertEqual(
            pipeline.short_fail_notice("Error: PAUSE:规格图未绑定到SKU 0/16"),
            "规格图未绑定到SKU 0/16",
        )

    def test_attribute_timeout_does_not_dump_command(self):
        session = FakeSession()

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
                return {"ok": True}
            if name == "attributes.js":
                raise RuntimeError(
                    "Command ['D:\\\\nodejs\\\\node.EXE', 'run-code', '--filename=web_fill_attributes.js'] timed out after 120 seconds"
                )
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(
                session,
                {"title": "卡游", "category": "中性笔", "skus": [], "main_images": [], "detail_images": []},
                confirm_submit=True,
            )
        self.assertEqual(result["execution"], "失败")
        self.assertEqual(result["notice"], "填写属性超时，请重试")
        self.assertNotIn("node.EXE", result["notice"])
        src = (pipeline.SCRIPTS / "submit.js").read_text(encoding="utf-8")
        self.assertIn("notice", src)
        self.assertIn("上架时间未选择", src)
        self.assertNotIn("slice(0, 1800)", src)

    def test_submit_blocked_when_required_empty(self):
        session = FakeSession()
        names = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "probe_errors.js":
                return {"banners": ["错误 (2)", "2 商品属性必填项未填"], "empty": ["功能", "IP联名"], "warehouseOn": True}
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(
                session,
                {"title": "卡游", "category": "中性笔", "skus": [], "main_images": [], "detail_images": []},
                confirm_submit=True,
            )
        self.assertEqual(result["execution"], "提交失败")
        self.assertNotIn("submit.js", names)
        self.assertGreaterEqual(names.count("attributes.js"), 2)
        self.assertIn("必填", result["notice"])
        self.assertIn("功能", result["notice"])
        self.assertNotIn("帮助", result["notice"])

    def test_listing_time_helper_does_not_block_submit(self):
        session = FakeSession()
        names = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "probe_errors.js":
                return {"banners": ["上架时间请根据实际需要选择", "上架时间"], "empty": [], "warehouseOn": True}
            if name == "submit.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/success.htm?primaryId=1086638256748&catId=50012720"
                return {
                    "hasSuccess": True,
                    "hasFail": False,
                    "text": "商品提交成功 商品ID: 1086638256748",
                    "itemId": "1086638256748",
                    "catId": "50012720",
                    "href": session_obj._href,
                }
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(
                session,
                {"title": "卡游火影忍者中性笔", "category": "中性笔", "skus": [], "main_images": [], "detail_images": []},
                confirm_submit=True,
            )
        self.assertIn("submit.js", names)
        self.assertEqual(result["execution"], "结果待核实")
        self.assertNotIn("上架时间", result.get("notice") or "")

    def test_payload_adds_ip_for_naruto_title(self):
        payload = pipeline.product_to_payload({"title": "卡游火影忍者中性笔", "attributes": {"功能": "考试专用"}})
        self.assertEqual(payload["attributes"]["IP联名"], "火影忍者")
        self.assertEqual(payload["attributes"]["功能"], "考试专用")

    def test_network_upload_error_is_retryable(self):
        status = {
            "fail": True,
            "retryable": True,
            "networkError": True,
            "failedNames": ["详情01.jpg"],
            "okNames": ["详情02.jpg"],
            "snippet": ["网络错误，请尝试禁止浏览器插件或者换浏览器或者换电脑重试", "有1个上传失败，本次共成功上传 3 个文件，请稍后重试。"],
        }
        self.assertTrue(pipeline.retryable_upload_failure({"status": status}))
        self.assertEqual(pipeline.failed_upload_names({"status": status, "missing": ["详情01.jpg"]}), ["详情01.jpg"])
        self.assertEqual(pipeline._files_named([r"C:\tmp\详情01.jpg", r"C:\tmp\详情02.jpg"], ["详情01.jpg"]), [r"C:\tmp\详情01.jpg"])
        self.assertFalse(pipeline.retryable_upload_failure({
            "fail": True,
            "snippet": ["没有权限", "无图片空间"],
            "failedNames": ["详情01.jpg"],
        }))

    def test_image_step_retries_network_error_file(self):
        session = FakeSession()
        files = [r"C:\tmp\详情01.jpg", r"C:\tmp\详情02.jpg"]
        after_calls = []

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "click_upload_btn.js":
                return {"clicked": "OK"}
            if name == "details.js" and payload.get("phase") == "open":
                return {"uploaded": True, "via": "hidden-input", "missing": []}
            if name == "details.js" and payload.get("phase") == "after_upload":
                after_calls.append(list(payload.get("files") or []))
                if len(after_calls) == 1:
                    return {
                        "status": {
                            "fail": True,
                            "retryable": True,
                            "networkError": True,
                            "failedNames": ["详情01.jpg"],
                            "okNames": ["详情02.jpg"],
                            "snippet": ["网络错误，请尝试禁止浏览器插件或者换浏览器或者换电脑重试"],
                        },
                        "failedNames": ["详情01.jpg"],
                        "missing": ["详情01.jpg"],
                        "uploaded": False,
                    }
                return {
                    "status": {"fail": False, "failedNames": [], "okNames": ["详情01.jpg", "详情02.jpg"]},
                    "failedNames": [],
                    "missing": [],
                    "uploaded": True,
                }
            if name == "details.js" and payload.get("phase") == "select":
                return {"picked": [{"name": "详情01.jpg", "ok": True}], "confirm": "OK"}
            return {"ok": True, "script": name, "phase": payload.get("phase")}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            with unittest.mock.patch.object(pipeline.time, "sleep"):
                result = pipeline._image_step(session, "details.js", {
                    "files": files,
                    "names": ["详情01.jpg", "详情02.jpg"],
                }, files)
        self.assertIn(("upload", r"C:\tmp\详情01.jpg"), session.calls)
        self.assertNotIn(("upload", r"C:\tmp\详情02.jpg"), session.calls)
        self.assertGreaterEqual(len(after_calls), 2)
        self.assertEqual(after_calls[1], [r"C:\tmp\详情01.jpg"])
        self.assertEqual(result["upload"].get("failedNames"), [])
        self.assertTrue(result["upload"].get("cli_retries"))


if __name__ == "__main__":
    unittest.main()
