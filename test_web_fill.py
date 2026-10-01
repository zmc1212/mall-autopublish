import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

import web_fill
from web_fill import pipeline
from web_fill import material_import


def playable_video_file(name="主视频.mp4"):
    """写一个容器头有效的 mp4（仅头部，内容不参与页面交互测试）。"""
    directory = Path(tempfile.mkdtemp(prefix="qianniu-video-"))
    path = directory / name
    path.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 16)
    return path


def fake_video_file(name="主视频.mp4"):
    """写一个伪装成 mp4 的 HTML 文件（线上实测的假视频场景）。"""
    directory = Path(tempfile.mkdtemp(prefix="qianniu-video-"))
    path = directory / name
    path.write_bytes(b"\r\n<!DOCTYPE html><html><head></head><body>download failed</body></html>")
    return path


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

    def test_payload_caps_main_images_to_five(self):
        image = Path(__file__).resolve().parent / "testdata"
        mains = [image.as_posix()] * 8
        product = {
            "title": "卡游火影忍者中性笔盲盒忍道版",
            "category": "文具用品/文化用品/商务用品>>笔类/书写工具>>中性笔",
            "attributes": {},
            "main_images": mains,
        }
        payload = web_fill.product_to_payload(product)
        self.assertEqual(len(payload["main_images"]), 5)
        self.assertEqual(payload["main_images"], mains[:5])

    def test_payload_carries_main_video_absolute_path(self):
        video = playable_video_file()
        payload = web_fill.product_to_payload({"title": "卡游", "main_video": video})
        self.assertTrue(payload["main_video"].endswith("主视频.mp4"))
        self.assertTrue(Path(payload["main_video"]).is_file())
        self.assertEqual(web_fill.product_to_payload({"title": "卡游"})["main_video"], "")

    def test_scripts_are_parameterized_and_avoid_drop(self):
        for name in ("category.js", "attributes.js", "skus.js", "sku_category.js", "spec_images.js", "main_images.js", "details.js", "logistics.js", "main_video.js"):
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
        video = (pipeline.SCRIPTS / "main_video.js").read_text(encoding="utf-8")
        self.assertIn("商品视频", video)
        self.assertIn("上传视频", video)
        self.assertIn("videoSelector", video)
        self.assertIn("setFilesAnywhere", video)
        self.assertIn("already", video)
        self.assertNotIn(".drop(", video)
        self.assertNotIn("waitForEvent(\"filechooser\"", video)
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

    def test_fill_uploads_main_video_and_records_checkpoint(self):
        video = playable_video_file()
        session = FakeSession()
        product = {
            "title": "卡游",
            "category": "中性笔",
            "skus": [],
            "main_images": [],
            "portrait_images": [],
            "detail_images": [],
            "main_video": video,
        }
        checkpoints = []

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "checkpoint.js":
                checkpoints.append(payload["completed"])
            if name == "main_video.js":
                self.assertEqual(payload["phase"], "open")
                self.assertEqual(payload["files"], [video.resolve().as_posix()])
                return {"uploaded": True, "verifiedBy": "slot", "slot": {"videos": 1}}
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertEqual(result["execution"], "已填写未提交")
        self.assertTrue(any("video" in completed for completed in checkpoints))

    def test_fill_skips_video_when_upload_unconfirmed(self):
        video = playable_video_file()
        session = FakeSession()
        product = {
            "title": "卡游",
            "category": "中性笔",
            "skus": [],
            "main_images": [],
            "portrait_images": [],
            "detail_images": [],
            "main_video": video,
        }
        names = []
        checkpoints = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "checkpoint.js":
                checkpoints.append(payload["completed"])
            if name == "main_video.js":
                return {"error": "视频已发布但选择列表未就绪"}
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        # 视频是可选项：上传未成功不暂停，跳过后继续入库流程。
        self.assertEqual(result["execution"], "已填写未提交")
        self.assertEqual(names.count("main_video.js"), 1)
        self.assertIn("logistics.js", names)
        self.assertTrue(any("video" in completed for completed in checkpoints))

    def test_close_video_dialog_runs_after_video_step(self):
        # 视频失败跳过后“选择视频”对话框可能残留；其 videoSelector iframe 与
        # 图片空间同域且 URL 形似，会把详情图的暂存文件劫持进视频上传框
        # （2026-09-30 真实页面复现）。视频步骤结束必须先关对话框再继续。
        video = playable_video_file()
        session = FakeSession()
        product = {
            "title": "卡游",
            "category": "中性笔",
            "skus": [],
            "main_images": [],
            "portrait_images": [],
            "detail_images": [],
            "main_video": video,
        }
        names = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "main_video.js":
                return {"error": "视频已发布但选择列表未就绪"}
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertIn("close_video_dialog.js", names)
        self.assertGreater(names.index("close_video_dialog.js"), names.index("main_video.js"))

    def test_wangpu_frame_ignores_video_selector(self):
        helpers = (pipeline.SCRIPTS / "_helpers.inc.js").read_text(encoding="utf-8")
        # videoSelector.htm 命中 sucai.wangpu 和 select.htm 两个模式，必须显式排除。
        self.assertIn("!/videoSelector/i.test(f.url())", helpers)
        self.assertIn("素材库定位到选择视频对话框", helpers)
        close_script = pipeline.SCRIPTS / "close_video_dialog.js"
        self.assertTrue(close_script.is_file())
        text = close_script.read_text(encoding="utf-8")
        self.assertIn("/*PAYLOAD*/", text)
        self.assertIn(".wdeDialog .next-dialog-close", text)
        self.assertIn("videoSelector", text)

    def test_video_step_security_pause_stops_flow(self):
        video = playable_video_file()
        session = FakeSession()

        def fake_run(session_obj, name, payload, timeout=120):
            raise RuntimeError("PAUSE:淘宝提示操作过于频繁；上传结果尚未确认，已停止自动重试并保留现场")

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            with self.assertRaises(RuntimeError) as ctx:
                pipeline.video_step(session, {"main_video": str(video)})
        self.assertIn("PAUSE:", str(ctx.exception))

    def test_video_step_dispatches_file_into_native_chooser(self):
        video = playable_video_file()
        session = FakeSession()
        calls = []

        def fake_run(session_obj, name, payload, timeout=120):
            calls.append((name, payload.get("phase")))
            if payload.get("phase") == "open":
                raise pipeline.FileChooserNeeded("File chooser opened")
            self.assertEqual(payload.get("phase"), "verify")
            return {"uploaded": True, "verifiedBy": "slot", "slot": {"videos": 1}}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.video_step(session, {"main_video": str(video)})
        self.assertTrue(result["uploaded"])
        self.assertEqual(session.uploads, [str(video)])
        self.assertEqual(calls, [("main_video.js", "open"), ("main_video.js", "verify")])

    def test_video_step_skips_when_chooser_dispatch_fails(self):
        video = playable_video_file()
        session = FakeSession()

        def fake_run(session_obj, name, payload, timeout=120):
            self.assertEqual(payload.get("phase"), "open")
            raise pipeline.FileChooserNeeded("File chooser opened")

        def failing_upload(*paths, timeout=180):
            raise RuntimeError("no pending chooser")

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run), \
                unittest.mock.patch.object(session, "upload_files", side_effect=failing_upload):
            result = pipeline.video_step(session, {"main_video": str(video)})
        self.assertFalse(result["uploaded"])
        self.assertIn("视频文件选择器不可用", result["warning"])

    def test_video_step_skips_unplayable_file(self):
        video = fake_video_file()
        session = FakeSession()
        result = pipeline.video_step(session, {"main_video": str(video)})
        self.assertFalse(result["uploaded"])
        self.assertIn("无法播放", result["warning"])
        # 不可播放的文件不应触碰页面（无任何 run-code/上传调用）。
        self.assertEqual(session.calls, [])

    def test_fill_skips_unplayable_video_and_continues(self):
        video = fake_video_file()
        session = FakeSession()
        product = {
            "title": "卡游",
            "category": "中性笔",
            "skus": [],
            "main_images": [],
            "portrait_images": [],
            "detail_images": [],
            "main_video": video,
        }
        names = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "main_video.js":
                raise AssertionError("无法播放的视频不应调用上传脚本")
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertEqual(result["execution"], "已填写未提交")
        self.assertIn("logistics.js", names)

    def test_fill_without_video_never_calls_video_script(self):
        session = FakeSession()
        product = {
            "title": "卡游",
            "category": "中性笔",
            "skus": [],
            "main_images": [],
            "portrait_images": [],
            "detail_images": [],
        }

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "main_video.js":
                raise AssertionError("无主视频时不应调用视频上传脚本")
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
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
        self.assertEqual(session.uploads, [])
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

    def test_spec_images_bind_large_sku_list_in_batches(self):
        skus = [{"name": f"规格{i}", "image": f"{i}.jpg"} for i in range(12)]
        payload = {"skus": skus}
        ranges = []

        def fake_run(session, name, data, timeout=120):
            if data["phase"] == "open":
                return {"already": True, "uploaded": True}
            start, end = data["bindStart"], data["bindEnd"]
            ranges.append((start, end))
            return {
                "partial": end < len(skus),
                "hadFrame": True,
                "bindLog": [{"name": item["name"], "picClick": {"ok": True}} for item in skus[start:end]],
                "saved": end == len(skus),
                "filledCount": end,
            }

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline._image_step(FakeSession(), "spec_images.js", payload, [item["image"] for item in skus])
        self.assertEqual(ranges, [(0, 5), (5, 10), (10, 12)])
        self.assertEqual(len(result["bind"]["bindLog"]), len(skus))
        self.assertTrue(result["bind"]["saved"])

    def test_spec_images_prefilled_drawer_finishes_without_more_batches(self):
        skus = [{"name": f"规格{i}", "image": f"{i}.jpg"} for i in range(8)]
        ranges = []

        def fake_run(session, name, data, timeout=120):
            if data["phase"] == "open":
                return {"already": True, "uploaded": True}
            ranges.append((data["bindStart"], data["bindEnd"]))
            return {"saved": True, "filledCount": len(skus), "bindLog": []}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline._image_step(FakeSession(), "spec_images.js", {"skus": skus}, [item["image"] for item in skus])
        self.assertEqual(ranges, [(0, 5)])
        self.assertTrue(result["bind"]["saved"])

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

    def test_spec_images_does_not_replay_ambiguous_binding(self):
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
        self.assertEqual(result["execution"], "失败")
        self.assertEqual(len(attempts), 1)

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
        self.assertEqual(len(attempts), 1)

    def test_filechooser_dump_is_not_user_pause(self):
        dump = "### Ran Playwright code\nthrow new Error(\"PAUSE:滑块\");\n### Modal state\n- [File chooser]: can be handled by upload"
        self.assertFalse(pipeline._is_user_pause(dump))
        self.assertTrue(pipeline._is_user_pause("Error: PAUSE:页面出现滑块验证，请手动完成后重试"))

    def test_auth_blocker_marks_items_and_batch_continues(self):
        """安全验证类硬暂停不重试，但只标记当前条并继续下一条，不再中断整批。"""
        session = FakeSession()
        products = [
            {"product_id": "A", "title": "A", "category": "中性笔", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "B", "category": "中性笔", "skus": [], "main_images": [], "detail_images": []},
        ]

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False, **kwargs):
            return {"execution": "暂停", "notice": "页面出现验证码", "errors": ["页面出现验证码"], "steps": []}

        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            updated = pipeline.run_batch(products, session=session)
        self.assertEqual(len(updated), 2)
        self.assertEqual([u["execution"] for u in updated], ["暂停", "暂停"])
        self.assertEqual(updated[0]["run_status"], "paused")

    def test_item_retryable_notice_classification(self):
        # 明确失败可重试；安全验证与结果不明确类不可重试
        self.assertTrue(pipeline.item_retryable_notice("选择类目超时，请重试"))
        self.assertTrue(pipeline.item_retryable_notice("规格未写入"))
        # 数据核对类（服务端商品与输入不一致）允许重试：重试是只读核验，
        # 复用已建商品断点，不会重复建品；重试用尽仍失败才标记跳过。
        self.assertTrue(pipeline.item_retryable_notice("已有商品的 SKU 与输入不符；禁止再次建品"))
        self.assertTrue(pipeline.item_retryable_notice("已有商品 ID 的标题与输入不符"))
        self.assertTrue(pipeline.item_retryable_notice("蓝杆-1支 的价格或库存发生变化"))
        # 新增守卫：提交前规格行审计失败 / SKU 分类不完整 → 可重试（重试重新处理 SKU 步骤）
        self.assertTrue(pipeline.item_retryable_notice("提交前页面规格行与输入不符（页面 17 行 / 输入 37 行）"))
        self.assertTrue(pipeline.item_retryable_notice("SKU 规格分类未写入全部规格行（页面 17 行，未分类 20 行）"))
        # 导入 verify 脚本崩溃（点击超时等）可重试：open 阶段 already 识别避免重复导入
        self.assertTrue(pipeline.item_retryable_notice(
            "SKU 模板已上传但结果未核实，请检查当前页面：TimeoutError: locator.click: Timeout 5000ms exceeded."))
        self.assertFalse(pipeline.item_retryable_notice("页面出现验证码"))
        self.assertFalse(pipeline.item_retryable_notice("淘宝触发\"滑块验证\"，请手动完成"))
        self.assertFalse(pipeline.item_retryable_notice("登录失效或需要人工处理"))
        self.assertFalse(pipeline.item_retryable_notice("上次提交结果不明确；禁止自动重复提交，请核实仓库后继续"))
        self.assertFalse(pipeline.item_retryable_notice("图片上传出现残留文件选择器，上传结果不明确"))
        self.assertFalse(pipeline.item_retryable_notice("PAUSE:captcha:已有商品核验遇到安全验证"))
        self.assertFalse(pipeline.item_retryable_notice("上传触发操作过于频繁限制"))
        self.assertFalse(pipeline.item_retryable_notice(""))

    def test_sku_scripts_guard_against_virtual_scroll(self):
        """虚拟滚动表格（可视约 17 行）必须有滚动采集与 audit 终检。"""
        category_src = (pipeline.SCRIPTS / "sku_category.js").read_text(encoding="utf-8")
        self.assertIn("scrollTop", category_src)
        self.assertIn("round < 150", category_src)
        self.assertIn("audit: true", category_src)
        self.assertIn("missing", category_src)
        import_src = (pipeline.SCRIPTS / "sku_import.js").read_text(encoding="utf-8")
        self.assertIn('PAYLOAD.phase === "audit"', import_src)
        self.assertIn("audit: true", import_src)

    def _spec_audit_product(self):
        return {
            "title": "卡游",
            "brand": "卡游",
            "category": "中性笔",
            "category_id": "50012720",
            "skus": [{"name": f"色{i}", "price": 6.9, "stock": 10} for i in range(37)],
            "main_images": [],
            "detail_images": [],
        }

    def test_fill_blocks_submit_when_spec_rows_mismatch(self):
        """提交前守卫：页面规格行与输入不符时不提交，清除 SKU 断点并判可重试失败。"""
        session = FakeSession()
        product = self._spec_audit_product()
        calls = []

        def fake_run(session_obj, name, payload, timeout=120):
            calls.append((name, payload))
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "sku_import.js" and payload.get("phase") == "audit":
                return {"audit": True, "count": 17, "expected": 37, "missing": ["色17"], "extra": []}
            if name == "probe_state.js":
                return {"checkpoint": {"key": "k1", "completed": ["category", "main_images", "skus", "spec_images"]}}
            if name == "submit.js":
                raise AssertionError("规格行不符时不得提交")
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=True, skip_spec_images=True)
        self.assertNotIn("submit.js", [name for name, _ in calls])
        self.assertEqual(result["execution"], "暂停")
        self.assertIn("页面规格行与输入不符", result["notice"])
        self.assertIn("页面 17 行 / 输入 37 行", result["notice"])
        # 页面断点里 skus/spec_images 被移除，其余步骤保留，重试会重新执行 SKU 步骤
        checkpoints = [payload for name, payload in calls if name == "checkpoint.js"]
        self.assertTrue(checkpoints)
        self.assertNotIn("skus", checkpoints[-1]["completed"])
        self.assertNotIn("spec_images", checkpoints[-1]["completed"])
        self.assertIn("category", checkpoints[-1]["completed"])
        self.assertTrue(pipeline.item_retryable_notice(result["notice"]))

    def test_fill_spec_audit_passes_when_rows_match(self):
        """审计一致时正常提交，守卫不阻断正常流程。"""
        session = FakeSession()
        product = self._spec_audit_product()

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "sku_import.js" and payload.get("phase") == "audit":
                return {"audit": True, "count": 37, "expected": 37, "missing": [], "extra": []}
            if name == "submit.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/success.htm?primaryId=1086638256748&catId=50012720"
                return {"hasSuccess": True, "hasFail": False, "itemId": "1086638256748",
                        "text": "商品提交成功 商品ID: 1086638256748", "href": session_obj._href}
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline.fill_new_product(session, product, confirm_submit=True, skip_spec_images=True)
        self.assertEqual(result["execution"], "结果待核实")
        self.assertEqual(result["taobao_item_id"], "1086638256748")

    def test_recover_existing_item_uses_deep_sku_audit(self):
        """建品后核验必须深扫描全量规格行：可视区只有约 17 行时不得误报不符。"""
        session = FakeSession()
        product = self._spec_audit_product()

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "probe_state.js":
                return {"href": "https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1088558441311",
                        "title": product["title"], "skuRows": 17,
                        "skuNames": [s["name"] for s in product["skus"][:17]],
                        "mainImgs": 0, "detailImgs": 0,
                        "warehouse": [{"t": "放入仓库", "checked": True}],
                        "captchaVisible": False}
            if name == "upload_status.js":
                return {"status": {}, "securityChallenge": False}
            if name == "sku_import.js" and payload.get("phase") == "audit":
                return {"audit": True, "count": 37, "expected": 37, "missing": [], "extra": []}
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run), \
             unittest.mock.patch.object(pipeline, "_open_item_edit_tab", return_value=None), \
             unittest.mock.patch.object(material_import, "inspect_target_skus", return_value=[]), \
             unittest.mock.patch.object(material_import, "check_rows", return_value=None):
            rows = pipeline._recover_existing_item(session, None, product, "1088558441311")
        self.assertEqual(rows, [])

    def test_recover_existing_item_raises_on_real_mismatch(self):
        """深扫描确认真缺失时仍要拦截，并给出缺失明细。"""
        session = FakeSession()
        product = self._spec_audit_product()

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "probe_state.js":
                return {"href": "https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1088558441311",
                        "title": product["title"], "skuRows": 17,
                        "skuNames": [s["name"] for s in product["skus"][:17]],
                        "mainImgs": 0, "detailImgs": 0,
                        "warehouse": [{"t": "放入仓库", "checked": True}],
                        "captchaVisible": False}
            if name == "upload_status.js":
                return {"status": {}, "securityChallenge": False}
            if name == "sku_import.js" and payload.get("phase") == "audit":
                return {"audit": True, "count": 17, "expected": 37, "missing": ["色17"], "extra": []}
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run), \
             unittest.mock.patch.object(pipeline, "_open_item_edit_tab", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                pipeline._recover_existing_item(session, None, product, "1088558441311")
        self.assertIn("页面 17 行 / 输入 37 行", str(ctx.exception))
        self.assertIn("缺失", str(ctx.exception))

    def test_fill_sku_category_incomplete_fails_before_submit(self):
        """SKU 分类终检发现行不全：建品前判失败，断点不标记 skus，可重试。"""
        session = FakeSession()
        product = self._spec_audit_product()
        calls = []
        checkpoints = []
        template = Path(tempfile.mkdtemp(prefix="qianniu-sku-tpl-")) / "SKU导入_test.xls"
        template.write_bytes(b"fake")

        def fake_run(session_obj, name, payload, timeout=120):
            calls.append(name)
            if name == "category.js":
                session_obj._href = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
            if name == "checkpoint.js":
                checkpoints.append(list(payload["completed"]))
            if name == "sku_import.js" and payload.get("phase") == "open":
                return {"uploaded": True, "already": True}
            if name == "sku_import.js" and payload.get("phase") == "verify":
                return {"verified": True, "count": 37, "matched": 37}
            if name == "sku_category.js":
                return {"audit": True, "skuCategory": "单品", "total": 17, "set": 17, "missing": 20, "ok": False}
            if name == "submit.js":
                raise AssertionError("分类不完整时不得提交")
            return {"ok": True, "script": name}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run), \
             unittest.mock.patch.object(pipeline.sku_import, "build_import_file", return_value=template):
            result = pipeline.fill_new_product(
                session, product, confirm_submit=True, skip_spec_images=True, sku_template_import=True)
        self.assertNotIn("submit.js", calls)
        self.assertEqual(result["execution"], "失败")
        self.assertIn("SKU 规格分类未写入", result["notice"])
        self.assertTrue(all("skus" not in completed for completed in checkpoints))
        self.assertTrue(pipeline.item_retryable_notice(result["notice"]))

    def test_run_batch_retries_when_created_item_verification_fails(self):
        """真实场景回归：建品成功后规格图核验失败（SKU 与输入不符），自动从
        已建品断点重试核验，而不是暂停整批。"""
        session = FakeSession()
        fills = []
        repairs = []
        retries = []

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False, **kwargs):
            fills.append(product.get("product_id"))
            return {"execution": "结果待核实", "notice": "商品提交成功 商品ID: 1089583476155",
                    "errors": [], "steps": [], "taobao_item_id": "1089583476155"}

        def fake_repair(session_obj, web, product, item_id, confirm_submit, **kwargs):
            repairs.append(item_id)
            if len(repairs) == 1:
                raise RuntimeError("PAUSE:已有商品的 SKU 与输入不符；禁止再次建品")
            return {"flow_stage": "complete", "execution": "已入库，图片已核验"}

        product = {
            "product_id": "A", "title": "卡游A", "execution": "未执行",
            "sku_image_strategy": "publish_page",
            "skus": [{"name": "蓝杆-1支", "image": "spec.jpg", "price": 6.9, "stock": 10}],
            "main_images": [], "detail_images": [],
        }
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill), \
             unittest.mock.patch.object(pipeline, "_repair_existing_spec_images", side_effect=fake_repair):
            updated = pipeline.run_batch([product], session=session, confirm_submit=True,
                                         item_retry_limit=1,
                                         on_item_retry=lambda p, i, a, l: retries.append((a, l)))
        # 重试不重新建品，复用已建商品断点再次核验
        self.assertEqual(fills, ["A"])
        self.assertEqual(repairs, ["1089583476155", "1089583476155"])
        self.assertEqual(retries, [(1, 1)])
        self.assertEqual(updated[0]["taobao_item_id"], "1089583476155")
        self.assertEqual(updated[0]["execution"], "已入库，图片已核验")

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
                return {"picked": [{"name": "d1.jpg", "ok": True}, {"name": "d2.jpg", "ok": True}],
                        "confirm": "OK", "after": {"imgs": 2, "dialog": False}}
            return {"ok": True, "uploaded": True, "script": name, "phase": payload.get("phase")}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run), \
             unittest.mock.patch.object(pipeline, "_prepare_media_uploads", side_effect=lambda files: files):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertNotEqual(result["execution"], "暂停")
        self.assertEqual(session.uploads, [])
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
        self.assertEqual(pipeline.decide_skips(filled, payload), {"skus", "main_images"})
        dialog = {**filled, "specImgs": 3, "specDialog": True, "popup": True, "mainImgs": 0}
        self.assertEqual(pipeline.decide_skips(dialog, payload), {"attributes", "skus"})
        other = {**filled, "title": "得力中性笔"}
        self.assertTrue(pipeline.page_conflicts(other, payload))
        self.assertFalse(pipeline.page_conflicts(filled, payload))
        smoke = {**filled, "title": "卡游火影忍者中性笔自动化冒烟"}
        self.assertTrue(pipeline.page_conflicts(smoke, payload))
        sibling = {**filled, "title": "卡游火影忍者中性笔盲盒忍道版02"}
        self.assertTrue(pipeline.page_conflicts(sibling, payload))

    def test_decide_skips_video_only_after_own_checkpoint(self):
        payload = {"title": "卡游火影忍者中性笔盲盒忍道版", "main_video": "C:/v/主视频.mp4"}
        state = {
            "title": "卡游火影忍者中性笔盲盒忍道版",
            "videos": 1,
            "checkpoint": {"key": pipeline.resume_key(payload), "completed": ["video"]},
        }
        self.assertEqual(pipeline.decide_skips(state, payload), {"video"})
        state["checkpoint"]["completed"] = []
        self.assertEqual(pipeline.decide_skips(state, payload), set())
        # 页面自带视频但无本商品 checkpoint 时不跳过，交给脚本的 already 探测兜底。
        other = {"title": "卡游火影忍者中性笔盲盒忍道版", "videos": 1}
        self.assertEqual(pipeline.decide_skips(other, payload), set())
        no_video = {"title": "卡游火影忍者中性笔盲盒忍道版", "videos": 1,
                    "checkpoint": {"key": pipeline.resume_key({"title": "卡游火影忍者中性笔盲盒忍道版"}), "completed": ["video"]}}
        self.assertEqual(pipeline.decide_skips(no_video, {"title": "卡游火影忍者中性笔盲盒忍道版"}), set())

    def test_fill_reuses_publish_tab_from_home(self):
        publish = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720"
        session = FakeSession(
            href="https://myseller.taobao.com/home.htm/QnworkbenchHome/",
            tabs=["https://myseller.taobao.com/home.htm/QnworkbenchHome/", publish],
        )
        names = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "upload_files.js":
                return {"uploaded": True}
            if name == "probe_state.js":
                return {"title": "卡游", "skuRows": 16, "specImgs": 0, "mainImgs": 0, "detailImgs": 0, "popup": True, "specDialog": True}
            if name == "spec_row_status.js":
                return {"total": 16, "filled": 16, "missing": [], "sources": [
                    {"index": i + 1, "src": f"url{i}"} for i in range(16)]}
            if name == "spec_row_images.js":
                return {"ready": True} if payload.get("phase") == "open" else {
                    "saved": True, "imageSrc": f"url{payload['index']}"}
            if name == "spec_images.js":
                if payload.get("phase") == "bind":
                    start, end = payload["bindStart"], payload["bindEnd"]
                    return {"ok": True, "partial": end < 16, "bindLog": [{"picClick": {"ok": True}}] * (end - start)}
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
        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run), \
             unittest.mock.patch.object(pipeline.time, "sleep"):
            result = pipeline.fill_new_product(session, product, confirm_submit=False)
        self.assertEqual(result["execution"], "已填写未提交")
        self.assertFalse(any(call[0] == "tab-new" for call in session.calls))
        self.assertTrue(any(call[0] == "tab-select" for call in session.calls))
        self.assertNotIn("category.js", names)
        self.assertNotIn("skus.js", names)
        self.assertNotIn("attributes.js", names)
        self.assertIn("spec_row_images.js", names)
        self.assertNotIn("close_overlays.js", names)

    def test_fill_skips_completed_steps_on_resume(self):
        session = FakeSession()
        names = []

        def fake_run(session_obj, name, payload, timeout=120):
            names.append(name)
            if name == "upload_files.js":
                return {"uploaded": True}
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
            if name == "main_images.js" and payload.get("phase") == "select":
                return {"selected": [{"name": "m.jpg", "pic": {"ok": True}}],
                        "slot": {"imgs": 1}}
            return {"ok": True, "script": name}

        product = {
            "title": "卡游火影忍者中性笔盲盒忍道版",
            "brand": "卡游",
            "category": "中性笔",
            "skus": [{"slot": "颜色01", "name": "特别款", "image": "a.jpg", "price": 9.9, "stock": 1}],
            "main_images": ["m.jpg"],
            "detail_images": [],
        }
        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run), \
             unittest.mock.patch.object(pipeline, "_prepare_media_uploads", side_effect=lambda files: files):
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

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False, **kwargs):
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

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False, **kwargs):
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

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False, **kwargs):
            flags.append((product.get("product_id"), bool(force_new)))
            return {"execution": "已填写未提交", "notice": "ok", "errors": [], "steps": []}

        products = [
            {"product_id": "A", "title": "卡游A", "execution": "已填写未提交", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "卡游B", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
        ]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            pipeline.run_batch(products, session=session)
        self.assertEqual(flags, [("B", True)])

    def test_run_batch_failure_continues_to_next_product(self):
        """条目失败后不再中断整批：标记该条并继续下一条（默认不重试）。"""
        session = FakeSession()
        flags = []

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False, **kwargs):
            flags.append((product.get("product_id"), bool(force_new)))
            if product.get("product_id") == "A":
                return {"execution": "失败", "notice": "x", "errors": ["x"], "steps": []}
            return {"execution": "已填写未提交", "notice": "ok", "errors": [], "steps": []}

        products = [
            {"product_id": "A", "title": "卡游A", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "卡游B", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
        ]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            updated = pipeline.run_batch(products, session=session)
        self.assertEqual(flags, [("A", False), ("B", True)])
        self.assertEqual(updated[0]["execution"], "失败")
        self.assertEqual(updated[0]["run_status"], "error")
        self.assertEqual(updated[1]["execution"], "已填写未提交")

    def test_run_batch_retries_failed_item_then_succeeds(self):
        """失败条目自动重试并从断点续跑；成功后 on_item_done 只结算一次。"""
        session = FakeSession()
        calls = []
        retries = []
        dones = []

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False, **kwargs):
            calls.append(dict(product))
            if len(calls) == 1:
                return {"execution": "失败", "notice": "选择类目超时，请重试",
                        "errors": ["选择类目超时，请重试"], "steps": [], "flow_stage": "filled"}
            return {"execution": "已填写未提交", "notice": "ok", "errors": [], "steps": []}

        products = [
            {"product_id": "A", "title": "卡游A", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "卡游B", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
        ]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            updated = pipeline.run_batch(
                products, session=session, item_retry_limit=1,
                on_item_retry=lambda p, i, a, l: retries.append((p.get("product_id"), a, l)),
                on_item_done=lambda p, i: dones.append(p.get("product_id")),
            )
        self.assertEqual([c.get("product_id") for c in calls], ["A", "A", "B"])
        # 重试时上一轮尝试推进到的断点状态已合并回商品
        self.assertEqual(calls[1].get("flow_stage"), "filled")
        self.assertEqual(retries, [("A", 1, 1)])
        self.assertEqual(dones, ["A", "B"])
        self.assertEqual(updated[0]["execution"], "已填写未提交")
        self.assertEqual(updated[1]["execution"], "已填写未提交")

    def test_run_batch_retry_exhausted_skips_to_next(self):
        """重试次数用尽后标记失败并自动进入下一条，不暂停整批。"""
        session = FakeSession()
        calls = []
        retries = []

        def fake_fill(session_obj, product, **kwargs):
            calls.append(product.get("product_id"))
            return {"execution": "失败", "notice": "页面操作超时，请重试",
                    "errors": ["页面操作超时，请重试"], "steps": []}

        products = [
            {"product_id": "A", "title": "卡游A", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "卡游B", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
        ]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            updated = pipeline.run_batch(
                products, session=session, item_retry_limit=2,
                on_item_retry=lambda p, i, a, l: retries.append((p.get("product_id"), a)),
            )
        # 每条数据各自享有完整的重试预算：A 重试 2 次用尽后跳到 B，B 同样重试 2 次
        self.assertEqual(calls, ["A", "A", "A", "B", "B", "B"])
        self.assertEqual(retries, [("A", 1), ("A", 2), ("B", 1), ("B", 2)])
        self.assertEqual(updated[0]["execution"], "失败")
        self.assertEqual(updated[0]["run_status"], "error")
        self.assertEqual(updated[1]["execution"], "失败")

    def test_run_batch_submit_pending_not_retried(self):
        """提交结果不明确时禁止自动重试（防重复建品），标记后跳下一条。"""
        session = FakeSession()
        calls = []

        def fake_fill(session_obj, product, confirm_submit=False, web=None, force_new=False, **kwargs):
            calls.append(product.get("product_id"))
            return {"execution": "提交待核实", "notice": "提交结果待核实", "errors": [], "steps": []}

        products = [
            {"product_id": "A", "title": "卡游A", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "卡游B", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
        ]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            updated = pipeline.run_batch(products, session=session, item_retry_limit=2, confirm_submit=True)
        self.assertEqual(calls, ["A", "B"])
        self.assertEqual(updated[0]["execution"], "提交待核实")
        self.assertEqual(updated[0]["run_status"], "paused")

    def test_run_batch_session_lost_marks_item_and_continues(self):
        """登录失效不重试，标记暂停后继续下一条。"""
        session = FakeSession()

        class FakeWeb:
            SessionLost = type("SessionLost", (RuntimeError,), {})

            @staticmethod
            def assert_logged_in(href, snapshot):
                return None

        def fake_fill(session_obj, product, **kwargs):
            if product.get("product_id") == "A":
                raise FakeWeb.SessionLost("登录失效或需要人工处理: 请重新登录")
            return {"execution": "已填写未提交", "notice": "ok", "errors": [], "steps": []}

        products = [
            {"product_id": "A", "title": "卡游A", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "卡游B", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
        ]
        with unittest.mock.patch.object(pipeline, "_load_web", return_value=FakeWeb), \
             unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            updated = pipeline.run_batch(products, session=session, item_retry_limit=2)
        self.assertEqual(updated[0]["execution"], "暂停")
        self.assertEqual(updated[0]["run_status"], "paused")
        self.assertEqual(updated[1]["execution"], "已填写未提交")

    def test_run_batch_user_cancel_stops_batch(self):
        """用户主动暂停仍是唯一中断手段：停止后不再处理后续条目。"""
        session = FakeSession()
        cancel = threading.Event()
        calls = []

        def fake_fill(session_obj, product, **kwargs):
            calls.append(product.get("product_id"))
            cancel.set()
            raise pipeline.UserStopped("PAUSE:用户已暂停；保留当前发布页，点击继续可接着填写")

        products = [
            {"product_id": "A", "title": "卡游A", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
            {"product_id": "B", "title": "卡游B", "execution": "未执行", "skus": [], "main_images": [], "detail_images": []},
        ]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill):
            updated = pipeline.run_batch(products, session=session, cancel_event=cancel, item_retry_limit=2)
        self.assertEqual(calls, ["A"])
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["execution"], "暂停")

    def test_run_batch_fill_failure_stops_before_material_stage(self):
        session = FakeSession()

        def fake_fill(session_obj, product, **kwargs):
            return {
                "execution": "失败",
                "notice": "图片上传失败：批量上传未确认成功，已停止后续图片",
                "errors": ["图片上传失败：批量上传未确认成功，已停止后续图片"],
                "steps": [],
            }

        products = [{
            "product_id": "A",
            "title": "晨光大美之诗静音按动中性笔",
            "execution": "未执行",
            "skus": [],
            "main_images": ["main.jpg"],
            "detail_images": [],
        }]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill), \
             unittest.mock.patch.object(material_import, "run_material_flow") as material:
            updated = pipeline.run_batch(products, session=session, confirm_submit=True)
        material.assert_not_called()
        self.assertEqual(updated[0]["execution"], "失败")
        self.assertEqual(
            updated[0]["notice"],
            "图片上传失败：批量上传未确认成功，已停止后续图片",
        )
        self.assertEqual(updated[0]["run_status"], "error")
        self.assertIsNone(updated[0].get("taobao_item_id") or None)

    def test_run_batch_material_error_keeps_fill_failure_notice(self):
        session = FakeSession()

        def fake_fill(session_obj, product, **kwargs):
            return {
                "execution": "失败",
                "notice": "图片上传失败：批量上传未确认成功，已停止后续图片",
                "errors": ["图片上传失败：批量上传未确认成功，已停止后续图片"],
                "steps": [],
            }

        products = [{
            "product_id": "A",
            "title": "晨光大美之诗静音按动中性笔",
            "execution": "未执行",
            "skus": [],
            "main_images": ["main.jpg"],
            "detail_images": [],
        }]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill), \
             unittest.mock.patch.object(material_import, "run_material_flow") as material:
            updated = pipeline.run_batch(products, session=session, confirm_submit=True)
        material.assert_not_called()
        self.assertEqual(updated[0]["errors"], ["图片上传失败：批量上传未确认成功，已停止后续图片"])
        self.assertNotIn("列表未找到目标商品", updated[0]["notice"])

    def test_run_batch_failed_then_resumed_material_pause_keeps_fill_notice(self):
        session = FakeSession()

        def fake_fill(session_obj, product, **kwargs):
            return {
                "execution": "暂停",
                "notice": "图片上传失败：批量上传未确认成功，已停止后续图片",
                "errors": ["图片上传失败：批量上传未确认成功，已停止后续图片"],
                "taobao_item_id": "1087608952245",
                "steps": [],
            }

        products = [{
            "product_id": "A",
            "title": "晨光大美之诗静音按动中性笔",
            "execution": "未执行",
            "skus": [{"name": "蓝杆-1支", "image": "spec.jpg", "price": 6.9, "stock": 10}],
            "main_images": [],
            "detail_images": [],
        }]
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=fake_fill), \
             unittest.mock.patch.object(material_import, "run_material_flow") as material:
            updated = pipeline.run_batch(products, session=session, confirm_submit=True)
        material.assert_not_called()
        self.assertEqual(updated[0]["execution"], "暂停")
        self.assertEqual(
            updated[0]["notice"],
            "图片上传失败：批量上传未确认成功，已停止后续图片",
        )
        self.assertNotIn("列表未找到目标商品", updated[0]["notice"])

    def test_run_batch_resume_created_imports_search_main_without_spec_upload(self):
        session = FakeSession()
        seen = []

        def fake_material(session_obj, web, product, item_id, state, on_stage=None, **kwargs):
            seen.append(item_id)
            if on_stage:
                on_stage("complete", {"baseline": [], "folder": "", "verified": []})
            return {**state, "stage": "complete"}

        products = [{
            "product_id": "A",
            "title": "晨光大美之诗静音按动中性笔",
            "execution": "暂停",
            "notice": "图片上传失败：批量上传未确认成功，已停止后续图片",
            "errors": ["图片上传失败：批量上传未确认成功，已停止后续图片"],
            "taobao_item_id": "1087608952245",
            "flow_stage": "created",
            "flow_version": material_import.FLOW_VERSION,
            "sku_image_strategy": "slim_material",
            "skus": [{"name": "蓝杆-1支", "image": "spec.jpg", "price": 6.9, "stock": 10}],
            "main_images": [],
            "detail_images": [],
        }]
        with unittest.mock.patch.object(pipeline, "fill_new_product") as fill, \
             unittest.mock.patch.object(pipeline, "_repair_existing_spec_images", return_value={
                 "flow_stage": "complete", "execution": "已入库，图片已核验"}) as repair, \
             unittest.mock.patch.object(
                 material_import, "run_material_flow", side_effect=fake_material
             ):
            updated = pipeline.run_batch(products, session=session, confirm_submit=True)
        fill.assert_not_called()
        self.assertEqual(seen, ["1087608952245"])
        repair.assert_not_called()
        self.assertEqual(updated[0]["flow_stage"], "complete")
        self.assertEqual(updated[0]["execution"], "已入库，搜索主图已核验")

    def test_run_batch_existing_id_with_both_strategy_repairs_in_edit_flow(self):
        session = FakeSession()
        repairs = []

        def fake_repair(session_obj, web, product, item_id, confirm_submit, **kwargs):
            repairs.append((item_id, confirm_submit))
            return {"flow_stage": "complete", "execution": "已入库，图片已核验"}

        def fake_material(session_obj, web, product, item_id, state, on_stage=None, **kwargs):
            if on_stage:
                on_stage("complete", {"baseline": [], "folder": "", "verified": []})
            return {**state, "stage": "complete"}

        product = {
            "product_id": "A",
            "title": "已有商品",
            "execution": "结果待核实",
            "taobao_item_id": "1088898192279",
            # 模拟旧记录缺少阶段字段；有 ID 仍必须进入编辑/补图流程。
            "sku_image_strategy": "both",
            "skus": [{"name": "黑色", "image": "spec.jpg", "price": 6.9, "stock": 10}],
            "main_images": [],
            "detail_images": [],
        }
        with unittest.mock.patch.object(pipeline, "fill_new_product") as fill, \
             unittest.mock.patch.object(pipeline, "_repair_existing_spec_images", side_effect=fake_repair), \
             unittest.mock.patch.object(material_import, "run_material_flow", side_effect=fake_material):
            updated = pipeline.run_batch([product], session=session, confirm_submit=True)

        fill.assert_not_called()
        self.assertEqual(repairs, [("1088898192279", True)])
        self.assertEqual(updated[0]["taobao_item_id"], "1088898192279")
        self.assertEqual(updated[0]["execution"], "已入库，图片已核验")

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

    def test_action_links_skip_notice_scrape_for_failed_execution(self):
        import job_session
        notice = ("拒绝使用已有商品编辑页: https://item.upload.taobao.com/sell/v2/publish.htm"
                  "?itemId=1086386107585&fromAiPublish=true")
        for state in ("失败", "暂停", "提交失败", "已停止"):
            links = job_session.product_action_links(notice=notice, execution=state)
            self.assertEqual(links["taobao_item_id"], "", state)
            self.assertEqual(links["view_url"], "", state)
            self.assertEqual(links["edit_url"], "", state)
        # 显式可信 ID（提交成功但验收失败的续跑场景）不受失败态影响。
        kept = job_session.product_action_links(
            notice=notice, item={"taobao_item_id": "1086386107585"}, execution="失败")
        self.assertEqual(kept["taobao_item_id"], "1086386107585")
        # apply_action_links 从记录自身取 execution，失败记录不再派生链接。
        data = job_session.apply_action_links({"execution": "失败", "notice": notice, "url": notice})
        self.assertEqual(data["taobao_item_id"], "")
        # 待核实态保留刮取，供人工核实商品 ID。
        pending = job_session.product_action_links(
            notice="提交成功 商品ID: 1086638256748", execution="结果待核实")
        self.assertEqual(pending["taobao_item_id"], "1086638256748")

    def test_ensure_fill_tab_force_new_ignores_stale_edit_page(self):
        # 回归：上一条入库成功后活动标签停在它的 publish.htm?itemId=… 编辑页，
        # 下一条 force_new 必须直接新开类目页，而不是对旧标签抛 UnsafeUrl。
        session = FakeSession(
            href="https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1086386107585&fromAiPublish=true")
        href, how = pipeline.ensure_fill_tab(session, pipeline._load_web(), force_new=True)
        self.assertEqual(how, "new-category")
        self.assertIn("category.htm", href)
        self.assertTrue(any(call[0] == "tab-new" for call in session.calls))

    def test_ensure_fill_tab_falls_through_stale_edit_page(self):
        # 非 force_new：当前活动标签是编辑页且没有可复用的干净发布页时，
        # 应新开类目页继续，而不是整条失败。
        session = FakeSession(
            href="https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1086386107585&fromAiPublish=true")
        href, how = pipeline.ensure_fill_tab(session, pipeline._load_web(), force_new=False)
        self.assertEqual(how, "new-category")
        self.assertIn("category.htm", href)

    def test_run_batch_drops_scraped_prior_id_from_rejected_notice(self):
        # 回归：历史缺陷把被拒 URL 里的上一条商品 ID 刮进了失败记录；
        # 重跑时必须丢弃这个 ID 按全新建品处理。
        session = FakeSession()
        rejected_id = "1086386107585"
        notice = (f"拒绝使用已有商品编辑页: https://item.upload.taobao.com/sell/v2/publish.htm"
                  f"?itemId={rejected_id}&fromAiPublish=true")
        polluted = {
            "product_id": "A", "title": "东米211胜利刷题按动式中性笔",
            "execution": "失败", "notice": notice, "taobao_item_id": rejected_id,
            "skus": [], "main_images": [], "detail_images": [],
        }
        called = []
        with unittest.mock.patch.object(pipeline, "fill_new_product", side_effect=lambda *a, **k: (
                called.append(a[1].get("product_id")),
                {"execution": "失败", "notice": "页面超时", "errors": ["页面超时"], "steps": []})[1]):
            updated = pipeline.run_batch([polluted], session=session)
        self.assertEqual(called, ["A"])
        self.assertEqual(updated[0]["taobao_item_id"], "")
        # 对照：失败记录的 notice 不含"拒绝使用已有商品编辑页"指纹时，
        # 已有 ID 属于可信 prior_id，按原样保留。
        trusted = {
            "product_id": "B", "title": "东米211A表情包刷题按动中性笔",
            "execution": "失败", "notice": "页面操作超时，请重试",
            "taobao_item_id": rejected_id,
            "skus": [], "main_images": [], "detail_images": [],
        }
        with unittest.mock.patch.object(pipeline, "fill_new_product", return_value={
                "execution": "失败", "notice": "页面超时", "errors": ["页面超时"], "steps": []}):
            updated = pipeline.run_batch([trusted], session=session)
        self.assertEqual(updated[0]["taobao_item_id"], rejected_id)

    def test_warehouse_script_does_not_force_click(self):
        warehouse = (pipeline.SCRIPTS / "warehouse.js").read_text(encoding="utf-8")
        helpers = (pipeline.SCRIPTS / "_helpers.inc.js").read_text(encoding="utf-8")
        logistics = (pipeline.SCRIPTS / "logistics.js").read_text(encoding="utf-8")
        self.assertNotIn("force: true", warehouse)
        self.assertIn("selectWarehouseRadio", warehouse)
        self.assertIn("selectWarehouseRadio", helpers)
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

    def test_main_images_confirmed_upload_is_not_uploaded_again(self):
        files = [r"C:\tmp\宝贝主图01.jpg", r"C:\tmp\宝贝主图02.jpg"]
        phases = []

        def fake_run(_session, script, payload, timeout=120):
            self.assertEqual(script, "main_images.js")
            phases.append(payload.get("phase"))
            if payload.get("phase") == "open":
                return {"uploaded": True, "verifiedBy": "library-search"}
            if payload.get("phase") == "select":
                return {"selected": [{"name": Path(path).name, "pic": {"ok": True}} for path in files],
                        "slot": {"imgs": len(files)}}
            self.fail("Confirmed files should go directly to binding")

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            pipeline._image_step(FakeSession(), "main_images.js", {
                "files": files, "names": [Path(path).name for path in files],
            }, files)
        self.assertEqual(phases, ["open", "select"])

    def test_confirmed_batch_upload_is_carried_into_main_binding(self):
        files = [r"C:\tmp\宝贝主图01.jpg", r"C:\tmp\宝贝主图02.jpg"]
        calls = []

        def fake_run(_session, script, payload, timeout=120):
            calls.append((script, payload.get("phase")))
            if script == "main_images.js" and payload.get("phase") == "open":
                return {"uploaded": False, "need_cli_upload": True}
            if script == "upload_files.js":
                return {"uploaded": True, "verifiedBy": "library-search"}
            if script == "main_images.js" and payload.get("phase") == "select":
                return {"selected": [{"name": Path(path).name, "pic": {"ok": True}} for path in files],
                        "slot": {"imgs": len(files)}}
            self.fail("The confirmed batch must not be checked against a closed upload popup")

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run):
            result = pipeline._image_step(FakeSession(), "main_images.js", {
                "files": files, "names": [Path(path).name for path in files],
            }, files)
        self.assertEqual(result["open"]["verifiedBy"], "library-search")
        self.assertEqual(calls, [("main_images.js", "open"), ("upload_files.js", None),
                                 ("main_images.js", "select")])

    def test_detail_upload_failure_stops_without_resubmitting_files(self):
        session = FakeSession()
        files = [r"C:\tmp\详情01.jpg", r"C:\tmp\详情02.jpg"]
        after_calls = []

        def fake_run(session_obj, name, payload, timeout=120):
            if name == "upload_files.js":
                raise pipeline.FileChooserNeeded("file chooser")
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
                return {"picked": [{"name": "详情01.jpg", "ok": True}, {"name": "详情02.jpg", "ok": True}],
                        "confirm": "OK", "after": {"imgs": 2, "dialog": False}}
            return {"ok": True, "script": name, "phase": payload.get("phase")}

        with unittest.mock.patch.object(pipeline, "run_script", side_effect=fake_run) as run:
            with unittest.mock.patch.object(pipeline.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "已停止绑定"):
                    pipeline._image_step(session, "details.js", {
                        "files": files,
                        "names": ["详情01.jpg", "详情02.jpg"],
                    }, files)
        self.assertEqual(session.uploads, [])
        self.assertEqual(after_calls, [files])
        self.assertEqual([(call.args[1], call.args[2].get("phase")) for call in run.call_args_list],
                         [("details.js", "open"), ("details.js", "after_upload")])

    def test_image_step_rejects_partial_image_binding(self):
        names = [f"详情{i:02}.jpg" for i in range(1, 7)]
        with self.assertRaisesRegex(RuntimeError, "图片包 6 张，页面 4 张"):
            pipeline._verify_image_binding("details.js", {"names": names}, {
                "picked": [{"name": name, "ok": True} for name in names],
                "confirm": "OK",
                "after": {"imgs": 4, "dialog": False},
            })
        with self.assertRaisesRegex(RuntimeError, "图片包 6 张，页面 7 张"):
            pipeline._verify_image_binding("details.js", {"names": names}, {
                "picked": [{"name": name, "ok": True} for name in names],
                "confirm": "OK",
                "after": {"imgs": 7, "dialog": False},
            })


def sellertab_url():
    return "https://myseller.taobao.com/home.htm/qnworkbenchhome"


def edit_url(item_id, extra=""):
    return "https://item.upload.taobao.com/sell/v2/publish.htm?itemId=" + item_id + extra


class TabListSession:
    """模拟 playwright-cli 的页签命令；tab-list 输出带 "(current)" 标记。"""

    def __init__(self, tabs):
        # tabs: [(url, is_current)]，与 CLI 的页签顺序一致。
        self._tabs = [[url, bool(current)] for url, current in tabs]
        self.closed = []
        self.selected = []
        self.opened = []
        self.fail_close_urls = set()

    def tab_list(self):
        lines = []
        for index, (url, current) in enumerate(self._tabs):
            marker = " (current)" if current else ""
            lines.append(f"- {index}:{marker} [页面标题]({url})")
        return "\n".join(lines)

    def tab_new(self, url=None):
        self.opened.append(url)
        for entry in self._tabs:
            entry[1] = False
        self._tabs.append([url, True])

    def tab_select(self, index):
        index = int(index)
        self.selected.append(index)
        for entry in self._tabs:
            entry[1] = False
        self._tabs[index][1] = True

    def tab_close(self, index):
        index = int(index)
        url = self._tabs[index][0]
        if url in self.fail_close_urls:
            raise RuntimeError("tab-close failed")
        self.closed.append(url)
        del self._tabs[index]

    def href(self):
        for url, current in self._tabs:
            if current:
                return url
        return ""

    def urls(self):
        return [url for url, _current in self._tabs]


class TabRecycleTests(unittest.TestCase):
    def setUp(self):
        sleep_patcher = unittest.mock.patch.object(pipeline.time, "sleep", lambda *_args: None)
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)
        prune_patcher = unittest.mock.patch.object(pipeline, "_prune_tabs", return_value=None)
        self.prune_mock = prune_patcher.start()
        self.addCleanup(prune_patcher.stop)

    def test_parse_tabs_with_current_reads_cli_format(self):
        text = "\n".join([
            "- 0: [我的商品](https://myseller.taobao.com/home.htm)",
            "- 1: (current) [淘宝网 - 商品发布](https://item.upload.taobao.com/sell/v2/publish.htm?itemId=123)",
        ])
        self.assertEqual(pipeline._parse_tabs_with_current(text), [
            (0, "https://myseller.taobao.com/home.htm", False),
            (1, "https://item.upload.taobao.com/sell/v2/publish.htm?itemId=123", True),
        ])

    def test_parse_tabs_with_current_accepts_plain_format(self):
        text = "0 https://myseller.taobao.com/home.htm\n1 https://item.upload.taobao.com/sell/v2/publish.htm?itemId=9"
        rows = pipeline._parse_tabs_with_current(text)
        self.assertEqual([row[0] for row in rows], [0, 1])
        self.assertFalse(any(row[2] for row in rows))

    def test_is_item_publish_url_scopes_to_item(self):
        self.assertTrue(pipeline._is_item_publish_url(edit_url("123"), "123"))
        self.assertTrue(pipeline._is_item_publish_url(edit_url("123", "&fr=tuwen"), "123"))
        self.assertFalse(pipeline._is_item_publish_url(edit_url("124"), "123"))
        self.assertFalse(pipeline._is_item_publish_url(
            "https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720", "123"))
        self.assertFalse(pipeline._is_item_publish_url(
            "https://item.upload.taobao.com/sell/v2/success.htm?itemId=123", "123"))
        self.assertFalse(pipeline._is_item_publish_url(
            "https://myseller.taobao.com/home.htm", "123"))

    def test_open_item_edit_tab_closes_stale_same_item_tabs(self):
        session = TabListSession([
            (edit_url("123"), False),
            (edit_url("123", "&fr=tuwen"), False),
            (sellertab_url(), False),
            (edit_url("124"), True),
        ])
        pipeline._open_item_edit_tab(session, "123")
        self.assertEqual(session.opened, [edit_url("123")])
        self.assertEqual(sorted(session.closed), [edit_url("123"), edit_url("123", "&fr=tuwen")])
        self.assertEqual(session.urls().count(edit_url("123")), 1)
        self.assertIn(edit_url("124"), session.urls())
        self.assertIn(sellertab_url(), session.urls())

    def test_close_stale_item_tabs_never_closes_without_current_marker(self):
        session = TabListSession([(edit_url("123"), False), (edit_url("123", "&fr=t"), False)])
        session._tabs = [[url, False] for url, _current in session._tabs]
        # 无 "(current)" 标记：宁可不动，避免关掉 CLI 正在使用的页签。
        session.tab_list = lambda: "\n".join(
            f"- {i}: [页面标题]({url})" for i, (url, _c) in enumerate(session._tabs))
        self.assertEqual(pipeline._close_stale_item_tabs(session, "123"), 0)
        self.assertEqual(session.closed, [])
        self.assertEqual(len(session._tabs), 2)

    def test_recycle_success_tabs_parks_on_seller_tab_then_closes_all(self):
        session = TabListSession([
            (sellertab_url(), False),
            (edit_url("123"), True),
            (edit_url("123", "&fr=tuwen"), False),
        ])
        closed = pipeline._recycle_success_tabs(session, "123")
        self.assertEqual(closed, 2)
        self.assertEqual(session.selected, [0])
        self.assertEqual(session.urls(), [sellertab_url()])

    def test_recycle_success_tabs_keeps_current_when_no_park_tab(self):
        session = TabListSession([
            (edit_url("123"), True),
            (edit_url("123", "&fr=tuwen"), False),
        ])
        closed = pipeline._recycle_success_tabs(session, "123")
        self.assertEqual(closed, 1)
        self.assertEqual(session.selected, [])
        self.assertEqual(session.urls(), [edit_url("123")])

    def test_recycle_success_tabs_skips_when_item_tab_absent(self):
        session = TabListSession([(sellertab_url(), True)])
        self.assertEqual(pipeline._recycle_success_tabs(session, "123"), 0)
        self.assertEqual(session.selected, [])
        self.assertEqual(session.closed, [])

    def test_finish_product_tabs_recycles_only_completed_items(self):
        session = TabListSession([(edit_url("123"), True), (sellertab_url(), False)])
        with unittest.mock.patch.object(pipeline, "_recycle_success_tabs", return_value=1) as recycle:
            pipeline._finish_product_tabs(session, None, {
                "run_status": "completed", "taobao_item_id": "123"})
            recycle.assert_called_once_with(session, "123")
        session = TabListSession([(edit_url("123"), True), (sellertab_url(), False)])
        with unittest.mock.patch.object(pipeline, "_recycle_success_tabs", return_value=0) as recycle:
            pipeline._finish_product_tabs(session, None, {
                "run_status": "paused", "taobao_item_id": "123"})
            recycle.assert_not_called()
        session = TabListSession([(edit_url("123"), True), (sellertab_url(), False)])
        with unittest.mock.patch.object(pipeline, "_recycle_success_tabs", return_value=0) as recycle:
            pipeline._finish_product_tabs(session, None, {"run_status": "completed"})
            recycle.assert_not_called()

    def test_finish_product_tabs_prunes_with_scene_url(self):
        session = TabListSession([(edit_url("123"), True)])
        pipeline._finish_product_tabs(session, None, {"run_status": "paused"})
        self.prune_mock.assert_called_with(None, keep_url=edit_url("123"))


if __name__ == "__main__":
    unittest.main()
