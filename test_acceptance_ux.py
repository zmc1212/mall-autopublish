"""当前桌面React页面的Playwright交互验收。

复用项目desktop.server、打包前端和browser_exe_path；AppData完全隔离。
业务执行、登录与导入使用本进程替身，设置走真实API，不连接淘宝、不上传。
"""
import copy
import os
import re
import tempfile
import threading
import time
import unittest
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from playwright.sync_api import expect, sync_playwright


class AcceptanceUxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="qianniu-ux-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.patches = ExitStack()
        cls.addClassCleanup(cls.patches.close)
        cls.patches.enter_context(mock.patch.dict(os.environ, {"QIANNIU_APPDATA": str(cls.root / "appdata")}))
        from desktop import license as license_module, paths, server
        from desktop.jobs import MANAGER
        import uvicorn
        cls.paths, cls.manager = paths, MANAGER
        cls.patches.enter_context(mock.patch.object(license_module, "is_activated", return_value=True))
        cls.patches.enter_context(mock.patch.object(license_module, "require_activated", return_value=None))
        cls.patches.enter_context(mock.patch.object(license_module, "state", return_value={"activated": True, "machine_code": "LOCAL-UX-DEMO", "expires_at": 0, "memo": "演示数据", "days_left": None, "issue": ""}))
        cls.patches.enter_context(mock.patch.object(server.code_watch, "stale_code_files", return_value=[]))
        cls.patches.enter_context(mock.patch.object(MANAGER, "begin_login_check", return_value=False))
        cls.patches.enter_context(mock.patch.object(MANAGER, "chrome_status", return_value={
            "chrome_found": True, "chrome_path": "demo", "browser_source": "bundled", "profile": "demo", "cdp_port": 9222,
            "debug_browser": False, "cdp": True, "browser": "Chromium", "logged_in": True, "blocker": "", "checking": False,
            "url": "", "cli_js": "", "cli_js_found": True, "node": "", "node_found": True,
        }))
        cls.patches.enter_context(mock.patch.object(MANAGER, "workspace_info", side_effect=cls._workspace))
        cls.patches.enter_context(mock.patch.object(MANAGER, "start_job", side_effect=cls._start))
        cls.patches.enter_context(mock.patch.object(MANAGER, "import_workbook", side_effect=cls._import))
        cls.patches.enter_context(mock.patch.object(MANAGER, "open_workspace", side_effect=cls._open_workspace))
        cls.patches.enter_context(mock.patch.object(MANAGER, "apply_debug_browser", return_value=False))
        cls.patches.enter_context(mock.patch.object(MANAGER, "rescan_workspace", side_effect=cls._rescan))
        cls.port = server.pick_free_port()
        cls.local_server = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=cls.port, log_level="error"))
        cls.thread = threading.Thread(target=cls.local_server.run, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls._stop_server)
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/api/health", timeout=1):
                    break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("本地页面验收服务启动失败")
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(headless=True, executable_path=str(paths.browser_exe_path()))
        cls.addClassCleanup(cls.browser.close)
        cls.output = Path("output/playwright/ux-upgrade")
        cls.output.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _stop_server(cls):
        cls.local_server.should_exit = True
        cls.thread.join(timeout=5)

    @classmethod
    def _workspace(cls):
        return {"path": cls.manager.workspace_path, "workbook_path": cls.manager.workbook_path,
                "defaults": {"brand": "演示品牌", "attributes_template": "中性笔", "logistics_template": "48小时", "sales_template": "仓库多规格", "price": 9.9, "stock": 20},
                "registry": {"attributes": ["中性笔"], "logistics": ["48小时"], "sales": ["仓库多规格"]},
                "scan": {"categories": [], "errors": [], "folders": []}}

    @classmethod
    def _start(cls, **kwargs):
        cls.starts.append(copy.deepcopy(kwargs))
        return cls.manager.snapshot()

    @classmethod
    def _import(cls, path):
        cls.imports.append(str(path))
        cls.manager.message = f"演示读取 {len(cls.imports)}"
        return cls.manager.snapshot()

    @classmethod
    def _rescan(cls, *args, **kwargs):
        cls.scans += 1
        cls.manager.message = f"演示扫描 {cls.scans}"
        return {**cls.manager.snapshot(), "workspace": cls._workspace(), "sync": {"added": [], "removed": []}}

    @classmethod
    def _open_workspace(cls, path, *args, **kwargs):
        cls.opened.append(path)
        cls.manager.workspace_path = path
        cls.manager.workbook_path = str(Path(path) / "商品清单.xlsx")
        cls.manager.rows = copy.deepcopy(cls.seed_rows)
        return cls._rescan()

    def setUp(self):
        cls = type(self)
        cls.starts, cls.imports, cls.opened, cls.scans = [], [], [], 0
        self.paths.save_settings(self.paths.Settings(limit=5, concurrency=2, results_dir=str(self.root / "results")))
        cls.seed_rows = [{
            "row": i, "product_id": f"P-{i:02d}", "title": f"【演示数据】文具中性笔学生办公多规格商品 {i:02d}",
            "category": "中性笔", "brand": "演示品牌", "validation": "通过", "execution": "已入库" if i == 2 else "失败" if i == 4 else "未执行",
            "notice": "", "errors": [], "last_error": "运费模板未找到，请检查物流模板" if i == 4 else "",
            "flow_stage": "complete" if i == 2 else "filling" if i == 4 else "pending", "sku_image_strategy": "slim_material", "flow_version": "slim-material-v2",
            "main_count": 5, "portrait_count": 2, "detail_count": 8, "sku_count": 6, "pack": str(self.root / f"商品-{i:02d}"),
            "pack_fingerprint": f"assets-{i}", "pack_found": True, "preview_url": "", "taobao_item_id": "100002" if i == 2 else "", "view_url": "", "edit_url": "",
        } for i in range(2, 37)]
        m = self.manager
        with m.lock:
            m._restored = True
            m.rows = copy.deepcopy(cls.seed_rows)
            m.products = [{"meta": copy.deepcopy(row), "product": {"row": row["row"], "product_id": row["product_id"]}} for row in m.rows]
            m.workbook_path = str(self.root / "商品清单.xlsx")
            m.workspace_path = str(self.root / "workspace")  # 不存在目录，校验走本进程导入替身。
            m.status, m.phase, m.blocker, m.message = "idle", "", "", ""
            m.done, m.total, m.started_at, m.finished_at = 0, 0, 0, 0
            m.active_worker_events = {}
            m.batch_settings = None
            m.attention_count = 0
            m.concurrency = 2
            m.result_xlsx, m.result_json = "", ""
            m.logs = [{"time": "10:30", "level": "error", "product_id": "P-04", "message": "运费模板未找到"}, {"time": "10:31", "level": "info", "product_id": "P-06", "message": "另一个商品的日志"}]
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        self.page = self.context.new_page()
        self.page.set_default_timeout(8000)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
        expect(self.page.get_by_role("button", name="连接店铺", exact=True)).to_be_visible()

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def _nav(self, name):
        self.page.get_by_role("button", name=name, exact=True).click()

    def _run(self):
        self._nav("执行入库")
        expect(self.page.get_by_role("table", name="商品执行列表")).to_be_visible()

    def _search(self, value):
        self.page.get_by_role("textbox", name="搜索商品名称或 ID").fill(value)

    def test_selected_execution_and_returning_context(self):
        self._run()
        self._search("P-04")
        self.page.get_by_role("checkbox", name="选择 P-04", exact=True).check()
        self._search("P-06")
        self.page.get_by_role("checkbox", name="选择 P-06", exact=True).check()
        self._nav("设置与工具")
        self._run()
        expect(self.page.get_by_role("textbox", name="搜索商品名称或 ID")).to_have_value("P-06")
        expect(self.page.get_by_role("checkbox", name="选择 P-06", exact=True)).to_be_checked()
        with self.page.expect_response(lambda r: r.url.endswith("/api/job/start") and r.request.method == "POST") as response:
            self.page.get_by_role("button", name="执行所选（2 件）", exact=True).click()
        self.assertEqual(response.value.status, 200)
        self.assertEqual([row["product_id"] for row in self.starts[-1]["selected_rows"]], ["P-04", "P-06"])
        self.assertEqual(self.starts[-1]["selected_rows"][0]["pack_fingerprint"], "assets-4")
        self.assertEqual(self.starts[-1]["workbook_path"], self.manager.workbook_path)
        self.assertEqual(self.starts[-1]["limit"], 5)

    def test_saved_default_all_and_custom_limit_reach_real_api(self):
        self._nav("设置与工具")
        self.page.get_by_label("每次默认条数", exact=True).fill("2")
        with self.page.expect_response(lambda r: r.url.endswith("/api/settings") and r.request.method == "PUT"):
            self.page.get_by_role("button", name="保存设置", exact=True).click()
        self._run()
        expect(self.page.get_by_label("本次执行摘要")).to_contain_text("沿用默认 · 2 件")
        with self.page.expect_response(lambda r: r.url.endswith("/api/job/start")):
            self.page.get_by_role("button", name=re.compile("全部未完成项")).click()
        self.assertEqual(self.starts[-1]["limit"], 2)
        self.page.get_by_role("button", name="执行选项", exact=True).click()
        self.page.get_by_label("本次上限模式", exact=True).select_option("all")
        self.page.get_by_role("heading", name="执行工作台", exact=True).click()
        with self.page.expect_response(lambda r: r.url.endswith("/api/job/start")):
            self.page.get_by_role("button", name=re.compile("全部未完成项")).click()
        self.assertEqual(self.starts[-1]["limit"], 0)
        self.page.get_by_role("button", name="执行选项", exact=True).click()
        self.page.get_by_label("本次上限模式", exact=True).select_option("custom")
        self.page.get_by_label("本次处理上限", exact=True).fill("3")
        self.page.get_by_role("heading", name="执行工作台", exact=True).click()
        with self.page.expect_response(lambda r: r.url.endswith("/api/job/start")):
            self.page.get_by_role("button", name=re.compile("全部未完成项")).click()
        self.assertEqual(self.starts[-1]["limit"], 3)
        self.assertNotIn("selected_rows", self.starts[-1])

    def test_failure_drawer_reason_logs_and_keyboard_restore(self):
        self._run()
        self._search("P-04")
        self.page.get_by_role("button", name="详情 P-04", exact=True).click()
        drawer = self.page.get_by_role("dialog", name="商品详情", exact=True)
        expect(drawer.get_by_label("当前问题", exact=True)).to_contain_text("运费模板未找到")
        expect(drawer).to_contain_text("入库失败")
        self.page.screenshot(path=str(self.output / "failure-drawer.png"))
        drawer.get_by_role("button", name="查看此商品日志", exact=True).click()
        expect(self.page.get_by_role("searchbox", name="搜索日志关键词")).to_have_value("P-04")
        expect(self.page.get_by_text("运费模板未找到", exact=False)).to_be_visible()
        expect(self.page.get_by_text("另一个商品的日志", exact=False)).to_have_count(0)
        self._run()
        expect(drawer).to_be_visible()
        self.page.keyboard.press("Escape")
        expect(drawer).to_be_hidden()
        expect(self.page.get_by_role("textbox", name="搜索商品名称或 ID")).to_have_value("P-04")

    def test_workbook_reload_tabs_and_first_pasted_directory(self):
        self._nav("商品清单")
        with self.page.expect_response(lambda r: r.url.endswith("/api/workbook/validate")):
            self.page.get_by_role("button", name="重新读取并校验", exact=True).click()
        self.assertEqual(len(self.imports), 1)
        self.page.get_by_role("tab", name="Excel 导入", exact=True).click()
        self._run()
        self._nav("商品清单")
        expect(self.page.get_by_role("tab", name="Excel 导入", exact=True)).to_have_attribute("aria-selected", "true")
        self.page.get_by_role("tab", name="Excel 导入", exact=True).press("ArrowLeft")
        expect(self.page.get_by_role("tab", name="目录扫描", exact=True)).to_have_attribute("aria-selected", "true")
        with self.manager.lock:
            self.manager.workbook_path, self.manager.workspace_path = "", ""
            self.manager.rows, self.manager.products = [], []
        self.page.evaluate("localStorage.clear(); sessionStorage.clear()")
        self.page.reload(wait_until="networkidle")
        self._nav("商品清单")
        target = str(self.root / "pasted-workspace")
        self.page.get_by_label("商品工作空间").fill(target)
        button = self.page.get_by_role("button", name="应用并扫描", exact=True)
        expect(button).to_be_enabled()
        with self.page.expect_response(lambda r: r.url.endswith("/api/workspace/open")):
            button.click()
        self.assertEqual(self.opened[-1], target)

    def test_detail_density_last_page_focus_and_settings_arrow_keys(self):
        self._run()
        self.page.get_by_role("button", name="查看执行明细", exact=True).click()
        dialog = self.page.get_by_role("dialog", name="执行明细", exact=True)
        expect(dialog.locator("tbody tr")).to_have_count(15)
        dialog.get_by_label("明细每页条数").select_option("30")
        expect(dialog.locator("tbody tr")).to_have_count(30)
        dialog.get_by_role("button", name="下一页", exact=True).click()
        expect(dialog.locator("tbody tr")).to_have_count(5)
        dialog.locator("button:not([disabled])").last.focus()
        self.page.keyboard.press("Tab")
        self.assertTrue(self.page.evaluate("Boolean(document.activeElement.closest('[role=dialog]'))"))
        self.page.keyboard.press("Escape")
        self._nav("设置与工具")
        tab = self.page.get_by_role("tab", name=re.compile("^常用设置"))
        tab.focus()
        tab.press("ArrowRight")
        expect(self.page.get_by_role("tab", name=re.compile("^图片处理"))).to_have_attribute("aria-selected", "true")

    def test_batch_notification_is_aggregated_and_dismisses_together(self):
        self._run()
        with self.manager.lock:
            for row in self.manager.rows:
                if row["product_id"] in {"P-05", "P-06"}:
                    row.update(taobao_item_id=f"10000{row['row']}", execution="已入库", flow_stage="complete")
        notification = self.page.get_by_label("批次入库通知", exact=True)
        expect(notification).to_contain_text("新建档入库 2 件", timeout=6000)
        expect(notification).to_contain_text("2 件完成图片核验")
        notification.get_by_role("button", name="关闭入库通知", exact=True).click()
        expect(notification).to_be_hidden()

    def test_progress_uses_batch_denominator_and_capture_desktop_layouts(self):
        with self.manager.lock:
            self.manager.status, self.manager.done, self.manager.total = "running", 3, 8
            self.manager.started_at = time.time() - 180
            self.manager.batch_settings = self.paths.Settings(concurrency=2)
        self.page.reload(wait_until="networkidle")
        self._run()
        progress = self.page.get_by_role("progressbar", name="本批处理进度", exact=True)
        expect(progress).to_have_attribute("aria-valuenow", "38")
        self.assertEqual(progress.locator("span").evaluate("el => el.style.width"), "38%")
        for width, height in [(1440, 900), (1366, 768), (1200, 768), (1100, 720)]:
            self.page.set_viewport_size({"width": width, "height": height})
            self.page.screenshot(path=str(self.output / f"run-{width}.png"))
            self.assertEqual(self.page.evaluate("document.documentElement.scrollWidth"), width)
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self._nav("商品清单")
        self.page.screenshot(path=str(self.output / "workbook.png"))
        self._nav("设置与工具")
        self.page.screenshot(path=str(self.output / "settings.png"))


if __name__ == "__main__":
    unittest.main()
