import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


class DetailBrowserTests(unittest.TestCase):
    def test_detail_profile_rejects_source_profile_from_environment_or_settings(self):
        from desktop import detail_browser

        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "source"
            for source_env in (str(profile), ""):
                with self.subTest(source_env=bool(source_env)), \
                     mock.patch.dict(detail_browser.os.environ, {
                         "QIANNIU_DETAIL_PROFILE": str(profile), "QIANNIU_PROFILE": source_env,
                     }), \
                     mock.patch.object(detail_browser.paths, "load_settings",
                                       return_value=SimpleNamespace(chrome_profile=str(profile))):
                    with self.assertRaises(RuntimeError):
                        detail_browser._detail_profile()
            self.assertFalse(profile.exists())

    def test_builtin_runtime_uses_playwright_launch_flags_only_for_bundled_browser(self):
        from desktop import detail_browser

        root = Path(tempfile.gettempdir()) / "qianniu-launch-options"
        bundled = root / "browser" / "chromium" / "chrome.exe"
        staged = root / ".work" / "desktop-runtime" / "browser" / "chromium" / "chrome.exe"
        custom = root / "custom-chrome.exe"
        with mock.patch.object(detail_browser.paths, "bundled_browser_path", return_value=bundled), \
             mock.patch.object(detail_browser.paths, "project_root", return_value=root):
            for browser in (bundled, staged):
                self.assertIn("--no-sandbox", detail_browser._launch_args(browser, root / "profile", 45678))
            self.assertNotIn("--no-sandbox", detail_browser._launch_args(custom, root / "profile", 45678))

    def test_desktop_self_test_does_not_close_running_browsers(self):
        from desktop import app

        with mock.patch.object(app, "configure_environ"), \
             mock.patch.object(app, "_runtime_preflight", return_value=[]), \
             mock.patch.object(app, "_write_self_test"), \
             mock.patch.object(app, "_cleanup_automation_chrome") as cleanup:
            self.assertEqual(app.main(["--self-test"]), 0)
        cleanup.assert_not_called()

    def setUp(self):
        from desktop import detail_browser

        self.detail_browser = detail_browser
        detail_browser.close_detail_browser()

    def tearDown(self):
        # The tests use synthetic PIDs; never invoke a real Windows taskkill
        # against them while cleaning the module state.
        with mock.patch.object(self.detail_browser.os, "name", "posix"):
            self.detail_browser.close_detail_browser()

    def test_item_url_allowlist_rejects_login_and_external_hosts(self):
        checker = self.detail_browser.is_allowed_item_url
        self.assertTrue(checker("https://item.taobao.com/item.htm?id=1"))
        self.assertTrue(checker("https://detail.tmall.com/item.htm?id=1"))
        self.assertFalse(checker("https://login.taobao.com/member/login.jhtml"))
        self.assertFalse(checker("https://example.com/item.htm?id=1"))
        self.assertFalse(checker("javascript:alert(1)"))

    def test_reuses_dedicated_process_and_opens_later_urls_as_new_tabs(self):
        detail_browser = self.detail_browser
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = root / "chrome.exe"
            browser.touch()
            profile = root / "detail-profile"
            process = mock.Mock()
            process.pid = 3210
            process.poll.return_value = None
            popen_calls = []

            def fake_popen(args, **kwargs):
                popen_calls.append((args, kwargs))
                return process

            with mock.patch.object(detail_browser, "_detail_browser", return_value=browser), \
                 mock.patch.object(detail_browser, "_detail_profile", return_value=profile), \
                 mock.patch.object(detail_browser, "_pick_free_port", return_value=43123), \
                 mock.patch.object(detail_browser.subprocess, "Popen", side_effect=fake_popen), \
                 mock.patch.object(detail_browser, "_wait_for_debug_endpoint", return_value=True), \
                 mock.patch.object(detail_browser, "sync_login_session", return_value={
                     "ok": True, "source_available": True, "applied": True,
                     "cookies": 2, "origins": 1, "navigated": True,
                 }), \
                 mock.patch.object(detail_browser, "_open_new_tab", return_value=True) as new_tab:
                first = detail_browser.open_item_url("https://item.taobao.com/item.htm?id=1")
                second = detail_browser.open_item_url("https://item.taobao.com/item.htm?id=2")

            self.assertEqual(first["via"], "builtin-browser")
            self.assertFalse(first["reused"])
            self.assertTrue(second["reused"])
            self.assertEqual(first["process_id"], second["process_id"])
            self.assertEqual(first["profile"], str(profile))
            self.assertEqual(len(popen_calls), 1)
            self.assertIn(f"--user-data-dir={profile}", popen_calls[0][0])
            self.assertIn("--remote-debugging-port=43123", popen_calls[0][0])
            new_tab.assert_called_once_with(43123, "https://item.taobao.com/item.htm?id=2")

    def test_start_failure_is_not_reported_as_success(self):
        detail_browser = self.detail_browser
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = root / "chrome.exe"
            browser.touch()
            process = mock.Mock()
            process.pid = 3211
            process.poll.return_value = None
            with mock.patch.object(detail_browser, "_detail_browser", return_value=browser), \
                 mock.patch.object(detail_browser, "_detail_profile", return_value=root / "profile"), \
                 mock.patch.object(detail_browser, "_pick_free_port", return_value=43125), \
                 mock.patch.object(detail_browser.subprocess, "Popen", return_value=process), \
                 mock.patch.object(detail_browser, "_wait_for_debug_endpoint", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "未就绪"):
                    detail_browser.open_item_url("https://item.taobao.com/item.htm?id=3")
            process.terminate.assert_called_once()
            self.assertFalse(detail_browser.detail_browser_state()["running"])

    def test_failed_fallback_tab_is_not_reported_as_success(self):
        detail_browser = self.detail_browser
        process = mock.Mock()
        process.pid = 3212
        process.poll.return_value = None
        detail_browser._DETAIL_PROCESS = process
        detail_browser._DETAIL_PORT = 43126
        detail_browser._DETAIL_PROFILE = Path("detail-profile")
        detail_browser._DETAIL_BROWSER = Path("chrome.exe")
        with mock.patch.object(detail_browser, "sync_login_session", return_value={
                 "ok": True, "source_available": True, "applied": True,
                 "cookies": 2, "origins": 1, "navigated": False,
             }), \
             mock.patch.object(detail_browser, "_open_new_tab", return_value=False), \
             mock.patch.object(detail_browser, "_spawn_fallback_tab", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "新标签页"):
                detail_browser.open_item_url("https://item.taobao.com/item.htm?id=4")
        self.assertTrue(detail_browser.detail_browser_state()["running"])

    def test_reused_detail_process_stays_open_when_source_is_not_logged_in(self):
        detail_browser = self.detail_browser
        process = mock.Mock()
        process.pid = 3213
        process.poll.return_value = None
        detail_browser._DETAIL_PROCESS = process
        detail_browser._DETAIL_PORT = 43127
        detail_browser._DETAIL_PROFILE = Path("detail-profile")
        detail_browser._DETAIL_BROWSER = Path("chrome.exe")
        with mock.patch.object(detail_browser, "sync_login_session", return_value={
            "ok": False,
            "source_available": True,
            "applied": False,
            "cookies": 0,
            "origins": 0,
            "navigated": False,
            "reason": "not_logged_in",
        }), mock.patch.object(detail_browser, "close_detail_browser") as close_browser:
            with self.assertRaisesRegex(RuntimeError, "尚未登录"):
                detail_browser.open_item_url("https://item.taobao.com/item.htm?id=5")
        close_browser.assert_not_called()
        self.assertTrue(detail_browser.detail_browser_state()["running"])

    def test_close_only_clears_owned_detail_process(self):
        detail_browser = self.detail_browser
        process = mock.Mock()
        process.pid = 9001
        process.poll.return_value = None
        detail_browser._DETAIL_PROCESS = process
        detail_browser._DETAIL_PORT = 43124
        detail_browser._DETAIL_PROFILE = Path("detail-profile")
        detail_browser._DETAIL_BROWSER = Path("chrome.exe")
        with mock.patch.object(detail_browser.os, "name", "posix"):
            self.assertTrue(detail_browser.close_detail_browser())
        process.terminate.assert_called_once()
        self.assertFalse(detail_browser.detail_browser_state()["running"])


if __name__ == "__main__":
    unittest.main()
