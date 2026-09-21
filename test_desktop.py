import importlib
import importlib.util
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path


class DesktopPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.appdata = Path(self.temp.name)
        os.environ["QIANNIU_APPDATA"] = str(self.appdata)
        os.environ.pop("QIANNIU_PROFILE", None)
        os.environ.pop("QIANNIU_OUTPUT_DIR", None)
        os.environ.pop("QIANNIU_CHROME", None)

    def test_profile_and_output_use_appdata(self):
        from desktop import paths
        importlib.reload(paths)
        settings = paths.configure_environ()
        self.assertTrue(str(Path(settings.chrome_profile)).startswith(str(self.appdata)))
        self.assertTrue(str(paths.playwright_output_dir()).startswith(str(self.appdata)))
        self.assertTrue(Path(settings.results_dir).is_dir())
        self.assertTrue(paths.cli_js_path().is_file())
        self.assertTrue(paths.templates_dir().is_dir())

    def test_web_module_reload_paths(self):
        from desktop.paths import configure_environ
        configure_environ()
        spec = importlib.util.spec_from_file_location(
            "web_cfg", Path(__file__).with_name("千牛网页执行.py")
        )
        web = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(web)
        web.reload_paths()
        self.assertTrue(str(web.PROFILE).startswith(str(self.appdata)))
        self.assertNotEqual(str(web.PROFILE), r"G:\workspace\taobao-playwright-profile")
        self.assertTrue(web.CHROME.is_file() or "chrome.exe" in str(web.CHROME).lower())
        args = web.chrome_launch_args()
        self.assertTrue(any(item.startswith("--user-data-dir=") for item in args))
        self.assertTrue(any(item.startswith("--remote-debugging-port=") for item in args))
        self.assertNotIn("https://myseller.taobao.com/", args)
        self.assertNotIn("--restore-last-session", args)
        prefs = Path(web.PROFILE) / "Default" / "Preferences"
        self.assertTrue(prefs.is_file())
        data = __import__("json").loads(prefs.read_text(encoding="utf-8"))
        self.assertEqual(data["session"]["restore_on_startup"], 1)

        cookies = Path(web.PROFILE) / "Default" / "Network"
        cookies.mkdir(parents=True, exist_ok=True)
        (cookies / "Cookies").write_bytes(b"cookie")
        restored = web.chrome_launch_args()
        self.assertIn("--restore-last-session", restored)
        self.assertNotIn("https://myseller.taobao.com/", restored)
        self.assertIn("https://myseller.taobao.com/", web.chrome_launch_args(url=web.SELLER_HOME))


class DesktopApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["QIANNIU_APPDATA"] = self.temp.name
        from desktop.paths import configure_environ
        configure_environ()

    def test_import_and_validate_sample_workbook(self):
        from fastapi.testclient import TestClient
        from desktop.server import app
        from desktop.jobs import MANAGER

        MANAGER._restored = True
        MANAGER.restored = False
        MANAGER.rows = []
        MANAGER.products = []
        MANAGER.workbook_path = ""
        excel = Path(__file__).resolve().parent / "testdata" / "中性笔测试入库.xlsx"
        self.assertTrue(excel.is_file(), excel)
        client = TestClient(app)
        response = client.post("/api/workbook/import", json={"path": str(excel)})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertGreaterEqual(data["count"], 1)
        self.assertGreaterEqual(data["valid"], 1)
        self.assertEqual(data["rows"][0]["validation"], "通过")
        health = client.get("/api/health")
        self.assertEqual(health.json()["ok"], True)
        status = client.get("/api/status")
        self.assertIn("chrome", status.json())
        self.assertIn("chrome_found", status.json()["chrome"])

    def test_pending_products_skip_done_unless_force_new(self):
        from desktop.jobs import JobManager
        manager = JobManager()
        manager.workbook_path = "x.xlsx"
        manager.products = [
            {"meta": {"validation": "通过", "execution": "已填写未提交", "row": 2, "errors": []}, "product": {"row": 2, "product_id": "A"}},
            {"meta": {"validation": "通过", "execution": "失败", "row": 3, "errors": []}, "product": {"row": 3, "product_id": "B"}},
            {"meta": {"validation": "失败", "execution": "未执行", "row": 4, "errors": []}, "product": {"row": 4, "product_id": "C"}},
        ]
        manager.rows = [
            {"validation": "通过", "execution": "已填写未提交"},
            {"validation": "通过", "execution": "失败"},
            {"validation": "失败", "execution": "未执行"},
        ]
        self.assertEqual([item["product_id"] for item in manager._pending_products(False)], ["B"])
        self.assertEqual([item["product_id"] for item in manager._pending_products(True)], ["A", "B"])
        self.assertEqual([item["product_id"] for item in manager._pending_products(retry_failed=True)], ["B"])
        snap = manager.snapshot()
        self.assertTrue(snap["can_resume"])
        self.assertEqual(snap["pending"], 1)
        self.assertEqual(snap["retryable"], 1)

    def test_restores_workbook_and_execution_after_restart(self):
        from desktop.jobs import JobManager
        excel = Path(__file__).resolve().parent / "testdata" / "中性笔测试入库.xlsx"
        first = JobManager()
        first._restored = True
        snap = first.import_workbook(str(excel))
        self.assertGreaterEqual(snap["count"], 1)
        first.products[0]["meta"]["execution"] = "失败"
        first.products[0]["meta"]["notice"] = "规格图中断"
        first.rows[0]["execution"] = "失败"
        first.rows[0]["notice"] = "规格图中断"
        first.status = "error"
        first._save_session()

        second = JobManager()
        restored = second.snapshot()
        self.assertTrue(restored["restored"])
        self.assertTrue(restored["workbook_path"].endswith(excel.name))
        self.assertGreaterEqual(restored["count"], 1)
        self.assertEqual(restored["rows"][0]["execution"], "失败")
        self.assertEqual(restored["rows"][0]["notice"], "规格图中断")
        self.assertGreaterEqual(restored["pending"], 1)

    def test_restores_from_latest_result_json(self):
        from desktop.jobs import JobManager
        from desktop import paths
        excel = Path(__file__).resolve().parent / "testdata" / "中性笔测试入库.xlsx"
        results_dir = Path(os.environ["QIANNIU_APPDATA"]) / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        journal = results_dir / "中性笔测试入库.结果-20260101-010101-1.json"
        journal.write_text(
            __import__("json").dumps({
                "source": str(excel.resolve()),
                "results": [{
                    "row": 2,
                    "product_id": "卡游-001",
                    "execution": "失败",
                    "notice": "中断",
                    "validation": "通过",
                    "errors": [],
                }],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        os.environ["QIANNIU_RESULTS_DIR"] = str(results_dir)
        paths.configure_environ()
        manager = JobManager()
        snap = manager.snapshot()
        self.assertTrue(snap["restored"])
        self.assertTrue(snap["workbook_path"].endswith(excel.name))
        self.assertEqual(snap["rows"][0]["execution"], "失败")

    def test_restore_desktop_manager_fills_frozen_manager(self):
        import job_session
        from desktop.jobs import MANAGER
        from desktop import paths
        excel = Path(__file__).resolve().parent / "testdata" / "卡游火影忍者中性笔清单.xlsx"
        self.assertTrue(excel.is_file(), excel)
        results_dir = Path(os.environ["QIANNIU_APPDATA"]) / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        journal = results_dir / "卡游火影忍者中性笔清单.结果-20990101-010101-1.json"
        journal.write_text(
            __import__("json").dumps({
                "source": str(excel.resolve()),
                "results": [{
                    "row": 2,
                    "product_id": "火影-001",
                    "execution": "暂停",
                    "notice": "详情图中断",
                    "validation": "通过",
                    "errors": [],
                }],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        os.environ["QIANNIU_RESULTS_DIR"] = str(results_dir)
        paths.configure_environ()
        MANAGER.workbook_path = ""
        MANAGER.products = []
        MANAGER.rows = []
        MANAGER.status = "idle"
        job_session._RESTORE_TRIED = False
        self.assertTrue(job_session.restore_desktop_manager())
        self.assertTrue(MANAGER.workbook_path.endswith(excel.name))
        self.assertGreaterEqual(len(MANAGER.rows), 1)
        self.assertEqual(MANAGER.rows[0]["execution"], "暂停")
        self.assertTrue(MANAGER.products)

    def test_serialize_row_builds_item_buttons_from_notice(self):
        from desktop.jobs import serialize_row
        row = serialize_row({
            "row": 2,
            "product_id": "火影-001",
            "execution": "结果待核实",
            "notice": "商品提交成功 商品ID: 1086638256748, 您可以在商品列表中根据商品 ID搜索找到该商品。",
            "product": {"title": "火影"},
        })
        self.assertEqual(row["taobao_item_id"], "1086638256748")
        self.assertIn("item.htm?id=1086638256748", row["view_url"])
        self.assertIn("itemId=1086638256748", row["edit_url"])

    def test_open_item_opens_view_url(self):
        from desktop.jobs import JobManager
        manager = JobManager()
        manager._restored = True
        manager.rows = [{
            "row": 2,
            "product_id": "火影-001",
            "notice": "商品提交成功 商品ID: 1086638256748",
        }]
        opened = []

        class FakeWeb:
            def open_item_url(self, url):
                opened.append(url)
                return {"ok": True, "url": url, "via": "default-browser"}

        with unittest.mock.patch("desktop.jobs.load_web", return_value=FakeWeb()):
            result = manager.open_item(2, "火影-001", "view")
        self.assertTrue(result["ok"])
        self.assertEqual(opened, ["https://item.taobao.com/item.htm?id=1086638256748"])
        with self.assertRaises(RuntimeError):
            manager.open_item(2, "火影-001", "share")

    def test_item_open_api(self):
        from fastapi.testclient import TestClient
        from desktop.server import app
        from desktop.jobs import MANAGER

        MANAGER._restored = True
        MANAGER.rows = [{"row": 2, "product_id": "火影-001", "notice": "商品ID: 1086638256748"}]

        class FakeWeb:
            def open_item_url(self, url):
                return {"ok": True, "url": url, "via": "default-browser"}

        with unittest.mock.patch("desktop.jobs.load_web", return_value=FakeWeb()):
            client = TestClient(app)
            response = client.post("/api/item/open", json={"row": 2, "product_id": "火影-001", "action": "edit"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("itemId=1086638256748", response.json()["url"])

    def test_open_workspace_api(self):
        from fastapi.testclient import TestClient
        from desktop.server import app
        from desktop.jobs import MANAGER
        from test_workspace import write_mini_pack

        MANAGER._restored = True
        MANAGER.restored = False
        MANAGER.rows = []
        MANAGER.products = []
        MANAGER.workbook_path = ""
        MANAGER.workspace_path = ""
        root = Path(self.temp.name) / "ws"
        write_mini_pack(root / "火影-001", "规格A")
        write_mini_pack(root / "火影-002", "规格B")
        client = TestClient(app)
        response = client.post("/api/workspace/open", json={"path": str(root)})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertTrue(data["workspace_path"].endswith("ws") or "ws" in data["workspace_path"])
        self.assertGreaterEqual(data["valid"], 0)
        defaults = client.get("/api/workspace/defaults")
        self.assertEqual(defaults.status_code, 200, defaults.text)
        saved = client.put("/api/workspace/defaults", json={"brand": "卡游", "price": 8.8, "stock": 12})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["defaults"]["brand"], "卡游")
        rescan = client.post("/api/workspace/rescan")
        self.assertEqual(rescan.status_code, 200, rescan.text)
        self.assertEqual(rescan.json()["count"], 2)
        start = client.post("/api/job/start", json={"retry_failed": True})
        self.assertEqual(start.status_code, 400)

    def test_open_chrome_hides_when_logged_in(self):
        from desktop.jobs import JobManager
        chrome = Path(self.temp.name) / "chrome.exe"
        chrome.write_bytes(b"mz")
        hidden = []
        revealed = []

        class Settings:
            chrome_path = str(chrome)
            chrome_profile = self.temp.name
            cdp_port = 9222

        class FakeWeb:
            def reload_paths(self):
                pass

            def detect_chrome(self):
                return chrome

            def cdp_available(self):
                return True

            def cdp_version(self):
                return {"Browser": "Chrome/1"}

            def login_status_from_tabs(self):
                return {"logged_in": True, "blocker": "", "url": "https://myseller.taobao.com/home.htm"}

            def start_persistent_chrome(self, focus=False, hide_if_logged_in=True):
                return "hidden"

            def hide_automation_chrome(self, **kwargs):
                hidden.append(True)
                return True

            def prune_automation_tabs(self, **kwargs):
                return {"closed": 0, "kept": 1}

            def reveal_automation_chrome(self, **kwargs):
                revealed.append(True)
                return True

            def reveal_seller_chrome(self):
                revealed.append(True)

        manager = JobManager()
        manager._restored = True
        with unittest.mock.patch("desktop.jobs.paths.configure_environ", return_value=Settings), \
             unittest.mock.patch("desktop.jobs.paths.load_settings", return_value=Settings), \
             unittest.mock.patch("desktop.jobs.load_web", return_value=FakeWeb()):
            status = manager.open_chrome()
        self.assertTrue(hidden)
        self.assertFalse(revealed)
        self.assertIn("已收起", status["notice"])
        self.assertNotIn("前台", status["notice"])

    def test_watch_progress_does_not_leak_end_across_items(self):
        from desktop.jobs import JobManager
        manager = JobManager()
        manager._restored = True
        manager.current_id = "火影-002"
        watch = {"last_id": "火影-001", "last_label": "提交"}
        leftover = [{"step": "end", "execution": "提交失败", "notice": "错误(2) 帮助 反馈"}]
        manager._consume_fill_progress(leftover, watch)
        self.assertFalse(any("本条结束" in (entry.get("message") or "") for entry in manager.logs))
        self.assertEqual(watch["last_id"], "火影-002")
        manager._consume_fill_progress(
            [{"step": "tab", "url": "https://item.upload.taobao.com/sell/v2/publish.htm"}],
            watch,
        )
        messages = [entry.get("message") or "" for entry in manager.logs]
        self.assertTrue(any("定位填写页" in msg for msg in messages))
        self.assertFalse(any("本条结束" in msg for msg in messages))


if __name__ == "__main__":
    unittest.main()
