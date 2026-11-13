"""Playwright 验收实际本地前端/API。微型更新包和会话均使用临时目录。"""

import functools
import json
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from desktop import paths
from desktop.updater import UpdateManager
import test_updater as updater_fixtures


class QuietFiles(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append(self.path.split("?", 1)[0])
        if self.path.split("?", 1)[0].endswith("/latest.json"):
            time.sleep(getattr(self.server, "feed_delay", 0))
        return super().do_GET()


class AcceptanceUpdateTests(unittest.TestCase):
    def test_real_update_page_online_download_import_queue_and_cancel(self):
        # 复用事务测试的微型目录准备方式，不运行父类的测试。
        fixture = updater_fixtures.UpdateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        package, delta_package, _ = fixture.delta_packages()
        feed_file = package.parent / "latest.json"
        valid_feed = json.loads(feed_file.read_text(encoding="utf-8"))
        feed_file.write_text(json.dumps({"schema": 1, "version": "0.0.0", "url": "", "sha256": "",
                                         "size": 0, "notes": "尚未发布更新"}), encoding="utf-8")
        files = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietFiles, directory=str(package.parent)))
        files.feed_delay = 0.2  # 确保检查 API 先返回 checking，再异步完成。
        files.requests = []
        threading.Thread(target=files.serve_forever, daemon=True).start()
        self.addCleanup(files.server_close)
        self.addCleanup(files.shutdown)
        feed_url = f"http://127.0.0.1:{files.server_port}/latest.json"

        ui = Path(__file__).parent / "desktop" / "ui" / "dist"
        if not (ui / "index.html").is_file():
            self.fail("请先构建前端：cd desktop/ui; npm run build")
        with patch("desktop.paths.web_dir", return_value=ui):
            from desktop import server
        # 其他 API 测试可能已经导入全局 app，静态目录不能继续引用其已删除的临时安装目录。
        from starlette.staticfiles import StaticFiles
        for route in server.app.routes:
            if getattr(route, "name", None) == "web":
                mount = patch.object(route, "app", StaticFiles(directory=str(ui), html=True))
                mount.start()
                self.addCleanup(mount.stop)
        from desktop import license as license_module
        import uvicorn

        updater = UpdateManager()
        jobs = server.MANAGER
        jobs.status, jobs._restored = "idle", True
        jobs.workbook_path, jobs.workspace_path = "", ""
        closed, released = threading.Event(), threading.Event()
        updater.jobs, updater.close_window = jobs, closed.set
        mocks = [
            patch.object(server, "UPDATER", updater),
            patch.object(license_module, "is_activated", return_value=True),
            patch.object(license_module, "require_activated", return_value=None),
            patch.object(license_module, "state", return_value={"activated": True, "machine_code": "acceptance", "expires_at": 0, "memo": "页面验收", "days_left": None}),
            patch.object(jobs, "chrome_status", return_value={"chrome_found": False, "cdp": False, "logged_in": False, "browser_source": "missing"}),
            patch.object(jobs, "begin_login_check", return_value=False),
        ]
        for mock in mocks:
            mock.start()
            self.addCleanup(mock.stop)
        port = server.pick_free_port()
        api_server = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error", log_config=None))
        api_server.install_signal_handlers = lambda: None
        api_thread = threading.Thread(target=api_server.run, daemon=True)
        api_thread.start()

        def stop_api():
            api_server.should_exit = True
            api_thread.join(5)
        self.addCleanup(stop_api)
        deadline = time.monotonic() + 10
        while not api_server.started:
            if time.monotonic() > deadline:
                self.fail("本地 API 启动超时")
            time.sleep(0.1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(paths.browser_exe_path()))
            page = None
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}/")
                page.get_by_role("button", name="设置与工具", exact=True).click()
                page.get_by_role("tab", name="更新与授权").click()
                panel = page.get_by_test_id("app-update")
                expect(panel).to_be_visible()
                panel.get_by_label("更新地址", exact=True).fill(feed_url)
                check = panel.get_by_role("button", name="保存地址并检查")
                check.click()
                expect(panel.get_by_role("status").last).to_have_text("当前已是最新版本", timeout=10000)
                expect(check).to_be_enabled()
                # 主状态指纹未变时 App 不重渲染；固定其快照，复现重复检查的卡转圈问题。
                cached_status = page.request.get(f"http://127.0.0.1:{port}/api/status").json()
                page.route("**/api/status", lambda route: route.fulfill(json=cached_status))
                try:
                    for _ in range(2):
                        check.click()
                        expect(panel.get_by_role("status").last).to_have_text("正在检查更新")
                        updater._operation.join(3)
                        self.assertEqual(updater.snapshot()["status"], "up_to_date")
                        expect(check).to_be_enabled(timeout=3000)
                        expect(panel.get_by_role("status").last).to_have_text("当前已是最新版本")
                        expect(panel.get_by_text("尚未发布更新", exact=True)).to_be_visible()
                except Exception:
                    output = Path(__file__).parent / "output" / "playwright"
                    output.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(output / "update-recheck-failure.png"), full_page=True)
                    raise
                finally:
                    page.unroute("**/api/status")
                feed_file.write_text(json.dumps(valid_feed | {"sha256": "0" * 64, "deltas": []}), encoding="utf-8")
                check.click()
                expect(panel.get_by_role("button", name="下载 1.3.0.2")).to_be_visible(timeout=10000)
                panel.get_by_role("button", name="下载 1.3.0.2").click()
                expect(panel.get_by_role("alert")).to_contain_text("SHA-256", timeout=10000)
                self.assertEqual((fixture.install / "web" / "index.html").read_text(), "old")

                feed_file.write_text(json.dumps(valid_feed), encoding="utf-8")
                panel.get_by_role("button", name="保存地址并检查").click()
                expect(panel.get_by_role("button", name="下载 1.3.0.2")).to_be_visible(timeout=10000)
                panel.get_by_role("button", name="下载 1.3.0.2").click()
                restart = panel.get_by_role("button", name="任务结束后重启更新")
                expect(restart).to_be_visible(timeout=10000)
                expect(restart).to_be_disabled()  # 开发模式不能覆盖真实源码。
                restart_now = panel.get_by_role("button", name="立即重启更新")
                expect(restart_now).to_be_visible(timeout=10000)
                expect(restart_now).to_be_disabled()
                self.assertEqual(updater.state["package_kind"], "delta")
                self.assertIn("/" + delta_package.name, files.requests)
                self.assertEqual(fixture.contents(Path(updater.state["prepared"]) / "payload"), fixture.contents(fixture.new))

                # 差量被截断时，从真实 HTTP 地址回退下载完整包；安装目录仍未修改。
                delta_package.write_bytes(b"truncated")
                panel.get_by_role("button", name="保存地址并检查").click()
                expect(panel.get_by_role("button", name="下载 1.3.0.2")).to_be_visible(timeout=10000)
                request_count = len(files.requests)
                panel.get_by_role("button", name="下载 1.3.0.2").click()
                expect(restart).to_be_visible(timeout=10000)
                self.assertEqual(updater.state["package_kind"], "full")
                self.assertEqual(files.requests[request_count:], ["/" + delta_package.name, "/" + package.name])
                self.assertEqual((fixture.install / "web" / "index.html").read_text(), "old")
                page.get_by_role("button", name="保存设置", exact=True).click()
                expect(page.get_by_text("设置已保存，将在下一次开始或继续入库时生效", exact=True)).to_be_visible()
                self.assertEqual(paths.load_settings().update_feed_url, feed_url)

                page.reload()
                page.get_by_role("button", name="设置与工具", exact=True).click()
                page.get_by_role("tab", name="更新与授权").click()
                expect(panel.get_by_label("更新地址", exact=True)).to_have_value(feed_url)
                panel.get_by_label("本地更新 ZIP", exact=True).fill(str(package))
                panel.get_by_role("button", name="校验并导入").click()
                expect(panel.get_by_role("status").last).to_have_text("更新已校验，重启后生效", timeout=10000)

                task = threading.Thread(target=lambda: released.wait(15), daemon=True)
                jobs.status, jobs.thread = "running", task
                task.start()
                self.addCleanup(released.set)
                with patch("desktop.paths.is_frozen", return_value=True), patch.object(updater, "_launch_worker") as launch:
                    expect(restart).to_be_enabled(timeout=10000)
                    expect(restart_now).to_be_enabled(timeout=10000)
                    restart_now.click()
                    dialog = page.get_by_role("dialog", name="立即重启更新")
                    expect(dialog).to_be_visible()
                    dialog.get_by_role("button", name="取消").click()
                    expect(dialog).not_to_be_visible()
                    self.assertFalse(closed.is_set())
                    restart.click()
                    expect(panel.get_by_role("button", name="取消自动重启")).to_be_visible(timeout=10000)
                    self.assertTrue(jobs.update_pending)
                    self.assertFalse(closed.is_set())
                    self.assertEqual(jobs.status, "running")
                    panel.get_by_role("button", name="取消自动重启").click()
                    expect(restart).to_be_visible(timeout=10000)
                    self.assertFalse(jobs.update_pending)
                    updater._watcher.join(3)
                    launch.assert_not_called()

                    restart.click()
                    expect(panel.get_by_role("button", name="取消自动重启")).to_be_visible(timeout=10000)
                    jobs.status = "done"
                    time.sleep(1.1)
                    self.assertFalse(closed.is_set())  # 结束状态早于线程保存/清理完成。
                    released.set()
                    task.join(2)
                    self.assertTrue(closed.wait(4))
                    updater._watcher.join(2)
                    launch.assert_called_once()
                output = Path(__file__).parent / "output" / "playwright"
                output.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(output / "inapp-update.png"), full_page=True)
                self.assertEqual(errors, [])
                for name, value in fixture.original_data.items():
                    if name != "settings.json":  # 更新地址由用户在页面中主动修改。
                        self.assertEqual((fixture.data / name).read_bytes(), value)
            except Exception:
                if page and not page.is_closed():
                    output = Path(__file__).parent / "output" / "playwright"
                    output.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(output / "inapp-update-last.png"), full_page=True)
                    print("UPDATE_PAGE_BUTTONS", page.get_by_role("button").all_text_contents())
                raise
            finally:
                released.set()
                browser.close()


if __name__ == "__main__":
    unittest.main()
