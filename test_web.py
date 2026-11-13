import importlib.util
import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

spec = importlib.util.spec_from_file_location('web', Path(__file__).with_name('千牛网页执行.py'))
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)

WAREHOUSE_ON = '''
- radio "立刻上架" [ref=a1]
- radio "定时上架" [ref=a2]
- radio "放入仓库" [checked] [ref=a3]
- button "提交宝贝信息" [ref=a4]
'''

WAREHOUSE_OFF = '''
- radio "立刻上架" [checked] [ref=b1]
- radio "定时上架" [ref=b2]
- radio "放入仓库" [ref=b3]
- button "提交宝贝信息" [ref=b4]
'''


class FakeSession:
    def __init__(self, snapshot, url='https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720', text='商品发布 如夏盛园文具店'):
        self._snapshot = snapshot
        self._url = url
        self._text = text
        self.clicks = []

    def snapshot(self):
        return self._snapshot

    def href(self):
        return self._url

    def body_text(self, limit=4000):
        return self._text[:limit]

    def click(self, ref):
        self.clicks.append(ref)


class WebSafetyTests(unittest.TestCase):
    def test_automation_command_matches_complete_switch_values(self):
        profile = Path(r"C:\Users\黄宝\AppData\Roaming\千牛自动上架\chrome-profile")
        with unittest.mock.patch.object(web, "PROFILE", profile), \
             unittest.mock.patch.object(web, "CDP_PORT", 9222):
            cases = [
                (f'chrome.exe --user-data-dir="{profile}" --remote-debugging-port=9222', True),
                (f'chrome.exe "--user-data-dir={profile}" --remote-debugging-port=9222', True),
                (f'chrome.exe --user-data-dir "{profile}" --remote-debugging-port 9222', True),
                (f'chrome.exe --user-data-dir="{profile.as_posix()}/" --remote-debugging-port=9222', True),
                (f'chrome.exe --user-data-dir="{profile}-other" --remote-debugging-port=9222', False),
                (f'chrome.exe --user-data-dir="{profile}" --remote-debugging-port=92221', False),
                (f'chrome.exe --user-data-dir="{profile}" https://example.test/--remote-debugging-port=9222', False),
                (f'chrome.exe --user-data-dir="{profile}" --remote-debugging-port=9222 --remote-debugging-port=9333', False),
            ]
            for command, expected in cases:
                with self.subTest(command=command):
                    self.assertEqual(web._is_automation_chrome_command(command), expected)

    def test_adopt_revalidates_cached_pid_and_replaces_exited_process(self):
        command = f'chrome.exe --user-data-dir="{web.PROFILE}" --remote-debugging-port={web.CDP_PORT}'
        exited = unittest.mock.Mock(pid=1111)
        exited.poll.return_value = 0
        with unittest.mock.patch.object(web, "_CHROME_ROOT_PID", 1111), \
             unittest.mock.patch.object(web, "_CHROME_PROC", exited), \
             unittest.mock.patch.object(web, "_CHROME_SESSION_PREFS_KEY", ("old", "ws://old")), \
             unittest.mock.patch.object(web, "listening_pid_on_port", return_value=2222), \
             unittest.mock.patch.object(web, "_process_command_line", return_value=command):
            self.assertEqual(web._adopt_connected_automation_chrome(), 2222)
            self.assertEqual(web._owned_chrome_root(web._CHROME_PROC, web._CHROME_ROOT_PID), 2222)
            self.assertIsNone(web._CHROME_PROC)
            self.assertIsNone(web._CHROME_SESSION_PREFS_KEY)

    def test_adopt_does_not_trust_cached_pid_when_port_is_foreign(self):
        foreign = 'chrome.exe --user-data-dir=C:\\other-profile --remote-debugging-port=9222'
        with unittest.mock.patch.object(web, "_CHROME_ROOT_PID", 1111), \
             unittest.mock.patch.object(web, "_CHROME_PROC", None), \
             unittest.mock.patch.object(web, "listening_pid_on_port", return_value=2222), \
             unittest.mock.patch.object(web, "_process_command_line", return_value=foreign):
            self.assertEqual(web._adopt_connected_automation_chrome(), 0)

    def test_process_command_line_sets_utf8_for_chinese_profile(self):
        command = f'chrome.exe --user-data-dir="{web.PROFILE}" --remote-debugging-port={web.CDP_PORT}'
        with unittest.mock.patch.object(web.os, "name", "nt"), \
             unittest.mock.patch.object(web, "_native_process_command_line", return_value=""), \
             unittest.mock.patch.object(web, "_hidden_subprocess_kwargs", return_value={}), \
             unittest.mock.patch.object(web.subprocess, "check_output", return_value=command) as query:
            actual = web._process_command_line(123)
        self.assertEqual(actual, command)
        self.assertTrue(web._is_automation_chrome_command(actual))
        self.assertIn("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)", query.call_args.args[0][-1])
        self.assertEqual(query.call_args.kwargs["encoding"], "utf-8")

    def test_process_command_line_prefers_native_unicode_query(self):
        command = 'chrome.exe --user-data-dir="C:\\Users\\黄宝\\千牛自动上架"'
        with unittest.mock.patch.object(web.os, "name", "nt"), \
             unittest.mock.patch.object(web, "_native_process_command_line", return_value=command), \
             unittest.mock.patch.object(web.subprocess, "check_output") as query:
            self.assertEqual(web._process_command_line(123), command)
        query.assert_not_called()

    def test_attach_removes_redundant_home_before_connecting(self):
        home = {"id": "home", "type": "page", "url": "https://myseller.taobao.com/home.htm/QnworkbenchHome/"}
        listing = {"id": "list", "type": "page", "url": "https://myseller.taobao.com/home.htm/SellManage/all_skucenter"}
        publish = {"id": "publish", "type": "page", "url": "https://item.upload.taobao.com/sell/v2/publish.htm?catId=1"}
        calls = []
        def runner(args, raw=True):
            calls.append(args)
            self.assertIn("home", closed)
            return listing["url"]
        closed = []
        with unittest.mock.patch.object(web, "start_persistent_chrome"), \
             unittest.mock.patch.object(web, "_adopt_connected_automation_chrome", return_value=123), \
             unittest.mock.patch.object(web, "cdp_tabs", return_value=[home, listing, publish]), \
             unittest.mock.patch.object(web, "_protected_page_urls", return_value=set()), \
             unittest.mock.patch.object(web, "_cdp_close_tab", side_effect=closed.append):
            self.assertEqual(web.CliSession(runner=runner).attach(), listing["url"])
        self.assertEqual(closed, ["home"])
        self.assertEqual(calls, [("eval", "location.href")])

    def test_owned_guard_recovers_drifted_current_page(self):
        """daemon 当前页漂移但租约页签还活着时，守卫先自愈找回页签而不是报错。"""
        from types import SimpleNamespace

        session = web.CliSession(runner=lambda args, raw=True: "### Result\n\"ok\"\n")
        session._isolated = True
        session._active_marker = "m"
        session._current_item = "k"
        session._leases["m"] = SimpleNamespace(marker="m", target_id="T1", key="k", index=0)
        with unittest.mock.patch.object(session, "_current_target_id", return_value="T2"), \
             unittest.mock.patch.object(session, "_recover_lease_target", return_value=True) as recover:
            self.assertIn("ok", session.cmd("eval", "() => 1"))
        recover.assert_called_once()

    def test_owned_guard_raises_with_diagnostics_when_recovery_fails(self):
        from types import SimpleNamespace

        session = web.CliSession(runner=lambda args, raw=True: "### Result\n\"ok\"\n")
        session._isolated = True
        session._active_marker = "m"
        session._current_item = "k"
        session._leases["m"] = SimpleNamespace(marker="m", target_id="T1", key="k", index=0)
        with unittest.mock.patch.object(session, "_current_target_id", return_value="T2"), \
             unittest.mock.patch.object(session, "_recover_lease_target", return_value=False), \
             unittest.mock.patch.object(session, "_raw_cmd", return_value='"https://myseller.taobao.com/home.htm/"'):
            with self.assertRaisesRegex(RuntimeError, "lease.target=T1 current.target=T2"):
                session.cmd("eval", "() => 1")

    def test_connect_cleanup_preserves_only_home_login_and_unowned_browser(self):
        home = {"id": "home", "type": "page", "url": "https://myseller.taobao.com/home.htm/QnworkbenchHome/"}
        listing = {"id": "list", "type": "page", "url": "https://myseller.taobao.com/home.htm/SellManage/all_skucenter"}
        login = {"id": "login", "type": "page", "url": "https://login.taobao.com/member/login.jhtml"}
        for owner, tabs in [(123, [home]), (123, [home, listing, login]), (0, [home, listing])]:
            with self.subTest(owner=owner, tabs=tabs), \
                 unittest.mock.patch.object(web, "_adopt_connected_automation_chrome", return_value=owner), \
                 unittest.mock.patch.object(web, "cdp_tabs", return_value=tabs), \
                 unittest.mock.patch.object(web, "_cdp_close_tab") as close:
                self.assertEqual(web.close_redundant_seller_home_tabs(), [])
                close.assert_not_called()

    def test_rejects_edit_urls(self):
        with self.assertRaises(web.UnsafeUrl):
            web.assert_safe_url('https://upload.taobao.com/auction/publish/edit.htm?itemId=1074400219062')
        with self.assertRaises(web.UnsafeUrl):
            web.assert_safe_url('https://item.upload.taobao.com/sell/subItem/publish.htm?itemId=1')
        web.assert_safe_url('https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720')

    def test_warehouse_not_instant(self):
        self.assertTrue(web.warehouse_selected(WAREHOUSE_ON))
        self.assertFalse(web.warehouse_selected(WAREHOUSE_OFF))
        real = Path(__file__).resolve().parent / 'output' / 'playwright' / 'expanded-form.yml'
        if real.is_file():
            self.assertTrue(web.warehouse_selected(real.read_text(encoding='utf-8')))

    def test_maybe_submit_requires_confirm_and_warehouse(self):
        session = FakeSession(WAREHOUSE_ON)
        self.assertEqual(web.maybe_submit(session, False), '已填写未提交')
        self.assertEqual(session.clicks, [])
        self.assertEqual(web.maybe_submit(session, True), '结果待核实')
        self.assertEqual(session.clicks, ['a4'])

    def test_login_blocker(self):
        self.assertEqual(web.detect_blocker('https://login.taobao.com/', '请登录'), '登录页')
        self.assertEqual(
            web.detect_blocker(
                'https://loginmyseller.taobao.com/?from=taobaoindex&redirect_url=https%3A%2F%2Fmyseller.taobao.com%2F'
            ),
            '登录页',
        )
        with self.assertRaises(web.SessionLost):
            web.assert_logged_in('https://login.taobao.com/', '请登录')
        with self.assertRaises(web.SessionLost):
            web.assert_logged_in('https://loginmyseller.taobao.com/?redirect_url=https://myseller.taobao.com/')

    def test_category_id(self):
        mapping = {
            'category_id': '121466019',
            'category_profiles': {'中性笔': {'category_id': '50012720'}},
        }
        self.assertEqual(web.category_id_for('文具用品/文化用品/商务用品>>笔类/书写工具>>中性笔', mapping), '50012720')
        self.assertEqual(web.leaf_name('a>>b>>中性笔'), '中性笔')

    def test_uses_local_playwright_cli(self):
        self.assertTrue(web.CLI_JS.is_file())
        self.assertIn('cli-client', str(web.CLI_JS))

    def test_node_cli_hides_console_on_windows(self):
        kwargs = web._hidden_subprocess_kwargs()
        if os.name == "nt":
            self.assertTrue(kwargs.get("creationflags", 0) & 0x08000000)
            self.assertTrue(kwargs["startupinfo"].dwFlags & 1)
        self.assertEqual(kwargs["env"]["NO_COLOR"], "1")
        self.assertIs(kwargs["stdin"], __import__("subprocess").DEVNULL)

    def test_picks_seller_tab(self):
        tabs = [
            {"id": "a", "url": "https://www.google.com/"},
            {"id": "b", "url": "https://item.upload.taobao.com/sell/v2/publish.htm"},
            {"id": "c", "url": "https://myseller.taobao.com/home.htm"},
        ]
        self.assertEqual(web.pick_seller_tab(tabs)["id"], "c")
        self.assertEqual(web.pick_seller_tab(tabs[:2])["id"], "b")
        self.assertIsNone(web.pick_seller_tab(tabs[:1]))

    def test_loginmyseller_is_not_logged_in(self):
        login_url = "https://loginmyseller.taobao.com/?from=taobaoindex&f=top&style=&sub=true&redirect_url=https%3A%2F%2Fmyseller.taobao.com%2F"
        tabs = [{"id": "a", "url": login_url}]
        self.assertIsNone(web.pick_seller_tab(tabs))
        status = web.login_status_from_tabs(tabs)
        self.assertFalse(status["logged_in"])
        self.assertEqual(status["blocker"], "登录页")
        self.assertTrue(web.is_login_url(login_url))
        self.assertFalse(web.is_seller_url(login_url))
        home = web.login_status_from_tabs([{"id": "b", "url": "https://myseller.taobao.com/home.htm"}])
        self.assertTrue(home["logged_in"])

    def test_login_page_wins_over_stale_seller_tab(self):
        tabs = [
            {"id": "old", "url": "https://myseller.taobao.com/home.htm"},
            {"id": "login", "url": "https://loginmyseller.taobao.com/?from=taobaoindex"},
        ]
        status = web.login_status_from_tabs(tabs)
        self.assertFalse(status["logged_in"])
        self.assertEqual(status["blocker"], "登录页")
        with unittest.mock.patch.object(web, "_cdp_get") as activate:
            web.activate_seller_tab(tabs)
        activate.assert_called_once_with("/json/activate/login")

    def test_reveal_seller_retries_until_window_exists(self):
        with unittest.mock.patch.object(web, "activate_seller_tab"), \
             unittest.mock.patch.object(web, "reveal_automation_chrome", side_effect=[False, False, True]) as reveal, \
             unittest.mock.patch.object(web.time, "sleep"):
            self.assertTrue(web.reveal_seller_chrome(timeout=1.0))
        self.assertEqual(reveal.call_count, 3)

    def test_item_open_urls_are_limited(self):
        self.assertTrue(web.is_allowed_item_url("https://item.taobao.com/item.htm?id=1086638256748"))
        self.assertTrue(web.is_allowed_item_url("https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1"))
        self.assertFalse(web.is_allowed_item_url("javascript:alert(1)"))
        self.assertFalse(web.is_allowed_item_url("https://example.com/item.htm?id=1"))
        self.assertFalse(web.is_allowed_item_url("https://login.taobao.com/member/login.jhtml"))
        with self.assertRaises(RuntimeError):
            web.open_item_url("https://example.com/")

    def test_open_item_url_uses_default_browser(self):
        opened = []
        with unittest.mock.patch.object(web, "prune_automation_tabs", return_value={"closed": 2, "kept": 1}), \
             unittest.mock.patch.object(web.os, "startfile", side_effect=lambda url: opened.append(url)), \
             unittest.mock.patch.object(web.webbrowser, "open", return_value=True) as browser_open:
            result = web.open_item_url("https://item.taobao.com/item.htm?id=1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["via"], "default-browser")
        self.assertEqual(opened, ["https://item.taobao.com/item.htm?id=1"])
        browser_open.assert_not_called()

    def test_prune_closes_stale_tabs_keeps_seller_home(self):
        closed = []
        tabs = [
            {"id": "1", "type": "page", "url": "https://myseller.taobao.com/home.htm"},
            {"id": "2", "type": "page", "url": "https://item.upload.taobao.com/sell/ai/category.htm"},
            {"id": "3", "type": "page", "url": "about:blank"},
            {"id": "4", "type": "iframe", "url": "https://item.upload.taobao.com/sell/v2/publish.htm"},
            {"id": "5", "type": "page", "url": "https://item.taobao.com/item.htm?id=1"},
        ]
        with unittest.mock.patch.object(web, "cdp_available", return_value=True), \
             unittest.mock.patch.object(web, "cdp_tabs", return_value=tabs), \
             unittest.mock.patch.object(web, "_cdp_close_tab", side_effect=lambda tab_id: closed.append(tab_id)):
            result = web.prune_automation_tabs()
        self.assertEqual(result["kept"], 1)
        self.assertEqual(set(closed), {"2", "3", "5"})

    def test_prune_keep_fill_pages_retains_one_publish(self):
        closed = []
        tabs = [
            {"id": "1", "type": "page", "url": "https://myseller.taobao.com/home.htm"},
            {"id": "2", "type": "page", "url": "https://item.upload.taobao.com/sell/v2/publish.htm?catId=1"},
            {"id": "3", "type": "page", "url": "https://item.upload.taobao.com/sell/v2/publish.htm?catId=2"},
            {"id": "4", "type": "page", "url": "https://item.upload.taobao.com/sell/ai/category.htm"},
        ]
        with unittest.mock.patch.object(web, "cdp_available", return_value=True), \
             unittest.mock.patch.object(web, "cdp_tabs", return_value=tabs), \
             unittest.mock.patch.object(web, "_cdp_close_tab", side_effect=lambda tab_id: closed.append(tab_id)):
            result = web.prune_automation_tabs(keep_fill_pages=True)
        self.assertEqual(result["kept"], 3)
        self.assertEqual(closed, ["3"])

    def test_chrome_launch_args_disable_background_throttling(self):
        args = web.chrome_launch_args()
        for flag in web.CHROME_ANTI_THROTTLE_ARGS:
            self.assertIn(flag, args)

    def test_ensure_chrome_runtime_session_prefs_caches_success_per_browser(self):
        """Runtime preference sync is idempotent per profile/browser websocket."""
        temp_dir = tempfile.TemporaryDirectory(prefix="qianniu-pref-test-")
        profile = Path(temp_dir.name)
        old_profile = web.PROFILE
        old_key = web._CHROME_SESSION_PREFS_KEY
        old_root = web._CHROME_ROOT_PID
        web.PROFILE = profile
        web._CHROME_SESSION_PREFS_KEY = None
        web._CHROME_ROOT_PID = 4242
        result = type("Result", (), {
            "returncode": 0,
            "stdout": json.dumps({"ok": True, "value": 1}),
            "stderr": "",
        })()
        try:
            with unittest.mock.patch.object(
                web, "cdp_version", return_value={"webSocketDebuggerUrl": "ws://browser/one"}
            ), unittest.mock.patch.object(web, "_owned_chrome_root", return_value=4242), \
                    unittest.mock.patch.object(web, "_cdp_listener_owned", return_value=True), \
                    unittest.mock.patch.object(web, "node_executable", return_value="node.exe"), \
                    unittest.mock.patch.object(
                        web, "_playwright_package_path", return_value=profile / "playwright"
                    ), unittest.mock.patch.object(web.subprocess, "run", return_value=result) as run:
                web.ensure_chrome_runtime_session_prefs()
                web.ensure_chrome_runtime_session_prefs()
                self.assertEqual(run.call_count, 1)
                payload = json.loads(run.call_args.kwargs["input"])
                self.assertEqual(payload["endpoint"], "ws://browser/one")
                self.assertIn("playwrightPath", payload)
                self.assertEqual(Path(web._CHROME_SESSION_PREFS_KEY[0]), profile.resolve())
                self.assertEqual(web._CHROME_SESSION_PREFS_KEY[1], "ws://browser/one")
        finally:
            web.PROFILE = old_profile
            web._CHROME_SESSION_PREFS_KEY = old_key
            web._CHROME_ROOT_PID = old_root
            temp_dir.cleanup()

    def test_ensure_chrome_runtime_session_prefs_failure_is_not_cached(self):
        """A failed runtime verification must raise and retry on the next call."""
        temp_dir = tempfile.TemporaryDirectory(prefix="qianniu-pref-failure-")
        profile = Path(temp_dir.name)
        old_profile = web.PROFILE
        old_key = web._CHROME_SESSION_PREFS_KEY
        old_root = web._CHROME_ROOT_PID
        web.PROFILE = profile
        web._CHROME_SESSION_PREFS_KEY = None
        web._CHROME_ROOT_PID = 4243
        result = type("Result", (), {
            "returncode": 0,
            "stdout": json.dumps({"ok": False, "reason": "policy_locked"}),
            "stderr": "",
        })()
        try:
            with unittest.mock.patch.object(
                web, "cdp_version", return_value={"webSocketDebuggerUrl": "ws://browser/fail"}
            ), unittest.mock.patch.object(web, "_owned_chrome_root", return_value=4243), \
                    unittest.mock.patch.object(web, "_cdp_listener_owned", return_value=True), \
                    unittest.mock.patch.object(web, "node_executable", return_value="node.exe"), \
                    unittest.mock.patch.object(
                        web, "_playwright_package_path", return_value=profile / "playwright"
                    ), unittest.mock.patch.object(web.subprocess, "run", return_value=result) as run:
                with self.assertRaises(RuntimeError):
                    web.ensure_chrome_runtime_session_prefs()
                with self.assertRaises(RuntimeError):
                    web.ensure_chrome_runtime_session_prefs()
                self.assertEqual(run.call_count, 2)
                self.assertIsNone(web._CHROME_SESSION_PREFS_KEY)
        finally:
            web.PROFILE = old_profile
            web._CHROME_SESSION_PREFS_KEY = old_key
            web._CHROME_ROOT_PID = old_root
            temp_dir.cleanup()

    def test_ensure_chrome_runtime_session_prefs_refuses_unowned_endpoint(self):
        temp_dir = tempfile.TemporaryDirectory(prefix="qianniu-pref-owner-")
        profile = Path(temp_dir.name)
        old_profile = web.PROFILE
        old_key = web._CHROME_SESSION_PREFS_KEY
        old_root = web._CHROME_ROOT_PID
        web.PROFILE = profile
        web._CHROME_SESSION_PREFS_KEY = None
        web._CHROME_ROOT_PID = 4244
        try:
            for owned_root, listener_owned in ((0, True), (4244, False)):
                with self.subTest(owned_root=owned_root, listener_owned=listener_owned), \
                     unittest.mock.patch.object(
                         web, "cdp_version",
                         return_value={"webSocketDebuggerUrl": "ws://browser/unowned"},
                     ), unittest.mock.patch.object(
                         web, "_owned_chrome_root", return_value=owned_root
                     ), unittest.mock.patch.object(
                         web, "_cdp_listener_owned", return_value=listener_owned
                     ), unittest.mock.patch.object(
                         web, "listening_pid_on_port", return_value=4244
                     ), unittest.mock.patch.object(
                         web, "_process_command_line", return_value=""
                     ), unittest.mock.patch.object(web.subprocess, "run") as run:
                    with self.assertRaises(RuntimeError):
                        web.ensure_chrome_runtime_session_prefs()
                    run.assert_not_called()
                    self.assertIsNone(web._CHROME_SESSION_PREFS_KEY)
        finally:
            web.PROFILE = old_profile
            web._CHROME_SESSION_PREFS_KEY = old_key
            web._CHROME_ROOT_PID = old_root
            temp_dir.cleanup()

    def test_unowned_browser_error_distinguishes_missing_and_unreadable_process(self):
        cases = [(0, "", "未找到监听进程"),
                 (4244, "", "无法读取监听进程启动参数"),
                 (4244, "chrome.exe --user-data-dir=C:\\other", "监听进程与配置的浏览器不匹配")]
        for listener, command, reason in cases:
            with self.subTest(reason=reason), \
                 unittest.mock.patch.object(web, "_CHROME_SESSION_PREFS_KEY", None), \
                 unittest.mock.patch.object(web, "cdp_version", return_value={
                     "webSocketDebuggerUrl": "ws://browser/unowned"
                 }), \
                 unittest.mock.patch.object(web, "_owned_chrome_root", return_value=0), \
                 unittest.mock.patch.object(web, "listening_pid_on_port", return_value=listener), \
                 unittest.mock.patch.object(web, "_process_command_line", return_value=command), \
                 unittest.mock.patch.object(web.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, reason) as raised:
                    web.ensure_chrome_runtime_session_prefs()
                self.assertIn(str(web.CDP_PORT), str(raised.exception))
                run.assert_not_called()

    def test_start_persistent_chrome_syncs_pref_after_spawn_before_status(self):
        events = []

        def mark(name, result=None):
            events.append(name)
            return result

        with unittest.mock.patch.object(web, "reload_paths"), \
             unittest.mock.patch.object(web, "cdp_available", side_effect=[False, True]), \
             unittest.mock.patch.object(web, "_spawn_chrome", side_effect=lambda hidden=False: mark("spawn")), \
             unittest.mock.patch.object(web, "_wait_cdp_ready", side_effect=lambda _timeout: mark("wait", True)), \
             unittest.mock.patch.object(web.time, "sleep", side_effect=lambda _seconds: mark("sleep")), \
             unittest.mock.patch.object(
                 web, "ensure_chrome_runtime_session_prefs", side_effect=lambda: mark("ensure")
             ), \
             unittest.mock.patch.object(
                 web, "login_status_from_tabs",
                 side_effect=lambda: mark("login", {"logged_in": True}),
             ), \
             unittest.mock.patch.object(web, "hide_automation_chrome", return_value=True), \
             unittest.mock.patch.object(web, "reveal_seller_chrome") as reveal:
            self.assertEqual(web.start_persistent_chrome(focus=False, hide_if_logged_in=True), "started")
        self.assertLess(events.index("spawn"), events.index("ensure"))
        self.assertLess(events.index("wait"), events.index("ensure"))
        self.assertLess(events.index("ensure"), events.index("login"))
        reveal.assert_not_called()

    def test_start_persistent_chrome_syncs_pref_after_adopt_before_status(self):
        events = []

        with unittest.mock.patch.object(web, "reload_paths"), \
             unittest.mock.patch.object(web, "cdp_available", return_value=True), \
             unittest.mock.patch.object(
                 web, "_adopt_connected_automation_chrome",
                 side_effect=lambda: events.append("adopt"),
             ), \
             unittest.mock.patch.object(
                 web, "ensure_chrome_runtime_session_prefs",
                 side_effect=lambda: events.append("ensure"),
             ), \
             unittest.mock.patch.object(
                 web, "login_status_from_tabs",
                 side_effect=lambda: events.append("login") or {"logged_in": False},
             ), \
             unittest.mock.patch.object(web, "hide_automation_chrome", return_value=True), \
             unittest.mock.patch.object(web, "reveal_seller_chrome") as reveal:
            self.assertEqual(web.start_persistent_chrome(focus=False, hide_if_logged_in=True), "hidden")
        self.assertLess(events.index("adopt"), events.index("ensure"))
        self.assertLess(events.index("ensure"), events.index("login"))
        reveal.assert_not_called()

    def test_start_persistent_chrome_does_not_report_status_when_pref_sync_fails(self):
        with unittest.mock.patch.object(web, "reload_paths"), \
             unittest.mock.patch.object(web, "cdp_available", return_value=True), \
             unittest.mock.patch.object(web, "_adopt_connected_automation_chrome"), \
             unittest.mock.patch.object(
                 web, "ensure_chrome_runtime_session_prefs",
                 side_effect=RuntimeError("policy_locked"),
             ), unittest.mock.patch.object(web, "login_status_from_tabs") as login:
            with self.assertRaisesRegex(RuntimeError, "policy_locked"):
                web.start_persistent_chrome(focus=False, hide_if_logged_in=True)
            login.assert_not_called()

    def test_parse_listening_pid_matches_exact_port(self):
        sample = (
            "  TCP    127.0.0.1:9222         0.0.0.0:0              LISTENING       4242\n"
            "  TCP    127.0.0.1:19222        0.0.0.0:0              LISTENING       99\n"
            "  TCP    0.0.0.0:443            0.0.0.0:0              LISTENING       7\n"
        )
        self.assertEqual(web.parse_listening_pid(sample, 9222), 4242)
        self.assertEqual(web.parse_listening_pid(sample, 443), 7)
        self.assertNotEqual(web.parse_listening_pid(sample, 9222), 99)

    def test_hide_reveal_only_debug_port_pids(self):
        seen = []
        moved = []

        def fake_hwnds(pids):
            seen.append(set(pids))
            if 90001 in pids or 90002 in pids:
                return [(11, "调试 Chrome", (10, 20, 810, 620))]
            return [(99, "用户 Chrome", (0, 0, 800, 600))]

        def fake_set(hwnd, x, y, w=0, h=0, show=None, activate=False, taskbar_visible=None):
            moved.append((hwnd, x, y, show, activate, taskbar_visible))
            return True

        with unittest.mock.patch.object(web, "_hwnds_for_pids", side_effect=fake_hwnds), \
             unittest.mock.patch.object(web, "_set_window_rect", side_effect=fake_set), \
             unittest.mock.patch.object(web, "process_tree_pids", side_effect=lambda root: {int(root), int(root) + 1}):
            hidden = web.hide_automation_chrome(root_pid=90001)
            shown = web.reveal_automation_chrome(root_pid=90001)
        self.assertTrue(hidden)
        self.assertTrue(shown)
        self.assertTrue(all(90001 in pids or 90002 in pids for pids in seen))
        self.assertFalse(any(99 in pids for pids in seen))
        self.assertEqual(moved[0][0], 11)
        self.assertEqual(moved[0][1], web.OFFSCREEN_POS[0])
        # 隐藏 = SW_SHOWNA 移出屏幕 + 移除任务栏按钮，但窗口保持可见
        # （SW_HIDE 会冻结 Chrome 渲染导致点击超时）。
        self.assertEqual(moved[0][3], 8)
        self.assertIs(moved[0][5], False)
        self.assertTrue(any(item[0] == 11 and item[4] for item in moved))
        reveal_calls = [item for item in moved if item[3] == 9]
        self.assertTrue(reveal_calls)

    def test_process_tree_includes_fake_root_pid(self):
        pids = web.process_tree_pids(424242)
        self.assertIn(424242, pids)

    def test_hide_offscreen_window_reapplies_hide_and_keeps_placement(self):
        original = (10, 20, 1210, 820)
        offscreen = (-32000, -32000, -30800, -31200)
        with unittest.mock.patch.dict(web._CHROME_PLACEMENTS, {11: original}, clear=True), \
             unittest.mock.patch.object(web, "_hwnds_for_pids", return_value=[(11, "Chrome", offscreen)]), \
             unittest.mock.patch.object(web, "_set_window_rect", return_value=True) as move:
            self.assertTrue(web.hide_automation_chrome(pids={90001}))
            self.assertEqual(move.call_args.kwargs["show"], 8)
            self.assertIs(move.call_args.kwargs["taskbar_visible"], False)
            self.assertEqual(web._CHROME_PLACEMENTS[11], original)

    def test_automation_window_hidden_ignores_offscreen_visible_window(self):
        """屏幕外但保持可见的隐藏窗口渲染正常，不算冻结；最小化/SW_HIDE 才算。"""
        from types import SimpleNamespace

        class FakeUser32:
            def __init__(self):
                self.visible = True
                self.iconic = False

            def IsWindowVisible(self, hwnd):
                return self.visible

            def IsIconic(self, hwnd):
                return self.iconic

        fake = FakeUser32()
        offscreen = (-32000, -32000, -30800, -31200)
        with unittest.mock.patch.object(web, "_automation_windows",
                                        return_value=[(11, "Chrome", offscreen)]), \
             unittest.mock.patch("ctypes.windll", SimpleNamespace(user32=fake)):
            self.assertFalse(web.automation_window_hidden())
            fake.visible = False
            self.assertTrue(web.automation_window_hidden())
            fake.visible, fake.iconic = True, True
            self.assertTrue(web.automation_window_hidden())

    def test_background_attach_never_reveals_during_login_settling(self):
        for logged_in in (False, True):
            with self.subTest(logged_in=logged_in), \
                 unittest.mock.patch.object(web, "reload_paths"), \
                 unittest.mock.patch.object(web, "cdp_available", return_value=True), \
                 unittest.mock.patch.object(web, "_adopt_connected_automation_chrome"), \
                 unittest.mock.patch.object(web, "ensure_chrome_runtime_session_prefs"), \
                 unittest.mock.patch.object(web, "login_status_from_tabs", return_value={"logged_in": logged_in}), \
                 unittest.mock.patch.object(web, "hide_automation_chrome", return_value=True) as hide, \
                 unittest.mock.patch.object(web, "reveal_seller_chrome") as reveal:
                self.assertEqual(web.start_persistent_chrome(focus=False, hide_if_logged_in=True), "hidden")
                hide.assert_called_once()
                reveal.assert_not_called()

    def test_background_start_uses_hidden_launch_and_never_reveals(self):
        with unittest.mock.patch.object(web, "reload_paths"), \
             unittest.mock.patch.object(web, "cdp_available", side_effect=[False, True]), \
             unittest.mock.patch.object(web, "_spawn_chrome") as spawn, \
             unittest.mock.patch.object(web, "_wait_cdp_ready", return_value=True), \
             unittest.mock.patch.object(web.time, "sleep"), \
             unittest.mock.patch.object(web, "ensure_chrome_runtime_session_prefs"), \
             unittest.mock.patch.object(web, "login_status_from_tabs", return_value={"logged_in": True}), \
             unittest.mock.patch.object(web, "hide_automation_chrome", return_value=True), \
             unittest.mock.patch.object(web, "reveal_seller_chrome") as reveal:
            self.assertEqual(web.start_persistent_chrome(focus=False, hide_if_logged_in=True), "started")
            spawn.assert_called_once_with(hidden=True)
            reveal.assert_not_called()

    def test_close_automation_chrome_only_closes_owned_process(self):
        class FakeProcess:
            pid = 424242

            def __init__(self):
                self.wait_calls = []

            def poll(self):
                return None

            def wait(self, timeout=None):
                self.wait_calls.append(timeout)
                return 0

            def terminate(self):
                return None

        process = FakeProcess()
        old_process = web._CHROME_PROC
        old_root_pid = web._CHROME_ROOT_PID
        web._CHROME_PROC = process
        web._CHROME_ROOT_PID = 0
        try:
            with unittest.mock.patch.object(web, "_process_command_line", return_value=""), \
                 unittest.mock.patch.object(web, "_request_graceful_chrome_close", return_value=False), \
                 unittest.mock.patch.object(
                     web.subprocess,
                     "run",
                     return_value=type("Result", (), {"returncode": 0})(),
                 ) as run:
                self.assertTrue(web.close_automation_chrome())
            if os.name == "nt":
                run.assert_called_once()
                self.assertEqual(
                    run.call_args.args[0],
                    ["taskkill", "/PID", "424242", "/T", "/F"],
                )
            self.assertIsNone(web._CHROME_PROC)
            self.assertTrue(process.wait_calls)
        finally:
            web._CHROME_PROC = old_process
            web._CHROME_ROOT_PID = old_root_pid

    def test_close_automation_chrome_prefers_graceful_cdp_shutdown(self):
        class FakeProcess:
            pid = 424243

            def __init__(self):
                self.wait_calls = []

            def poll(self):
                return None

            def wait(self, timeout=None):
                self.wait_calls.append(timeout)
                return 0

        process = FakeProcess()
        old_process = web._CHROME_PROC
        old_root_pid = web._CHROME_ROOT_PID
        web._CHROME_PROC = process
        web._CHROME_ROOT_PID = 0
        try:
            with unittest.mock.patch.object(web, "_process_command_line", return_value=""), \
                 unittest.mock.patch.object(web, "_request_graceful_chrome_close", return_value=True) as graceful, \
                 unittest.mock.patch.object(web, "_wait_for_chrome_exit", return_value=True), \
                 unittest.mock.patch.object(web.subprocess, "run") as run:
                self.assertTrue(web.close_automation_chrome())
            graceful.assert_called_once_with(424243, timeout=3.0)
            run.assert_not_called()
            self.assertTrue(process.wait_calls)
        finally:
            web._CHROME_PROC = old_process
            web._CHROME_ROOT_PID = old_root_pid

    def test_close_automation_chrome_waits_after_graceful_helper_reports_failure(self):
        class FakeProcess:
            pid = 424245

            def poll(self):
                return None

        process = FakeProcess()
        old_process = web._CHROME_PROC
        old_root_pid = web._CHROME_ROOT_PID
        web._CHROME_PROC = process
        web._CHROME_ROOT_PID = 0
        try:
            with unittest.mock.patch.object(web, "_process_command_line", return_value=""), \
                 unittest.mock.patch.object(web, "_request_graceful_chrome_close", return_value=False) as graceful, \
                 unittest.mock.patch.object(web, "_wait_for_chrome_exit", return_value=True) as wait, \
                 unittest.mock.patch.object(web.subprocess, "run") as run:
                self.assertTrue(web.close_automation_chrome())
            graceful.assert_called_once_with(424245, timeout=3.0)
            wait.assert_called_once_with(process, 424245, timeout=3.0)
            run.assert_not_called()
        finally:
            web._CHROME_PROC = old_process
            web._CHROME_ROOT_PID = old_root_pid

    def test_close_automation_chrome_does_not_guess_by_debug_port(self):
        old_process = web._CHROME_PROC
        old_root_pid = web._CHROME_ROOT_PID
        web._CHROME_PROC = None
        web._CHROME_ROOT_PID = 0
        try:
            with unittest.mock.patch.object(web, "listening_pid_on_port", return_value=0), \
                unittest.mock.patch.object(web.subprocess, "run") as run:
                self.assertFalse(web.close_automation_chrome())
            run.assert_not_called()
        finally:
            web._CHROME_PROC = old_process
            web._CHROME_ROOT_PID = old_root_pid

    def test_close_automation_chrome_refuses_foreign_profile_process(self):
        class FakeProcess:
            pid = 424244

            def poll(self):
                return None

        process = FakeProcess()
        old_process = web._CHROME_PROC
        old_root_pid = web._CHROME_ROOT_PID
        web._CHROME_PROC = process
        web._CHROME_ROOT_PID = 0
        try:
            foreign = 'chrome.exe --user-data-dir=C:\\other-profile --remote-debugging-port=9222'
            with unittest.mock.patch.object(web, "_process_command_line", return_value=foreign), \
                 unittest.mock.patch.object(web.subprocess, "run") as run:
                self.assertFalse(web.close_automation_chrome())
            run.assert_not_called()
            self.assertIs(web._CHROME_PROC, process)
        finally:
            web._CHROME_PROC = old_process
            web._CHROME_ROOT_PID = old_root_pid


if __name__ == '__main__':
    unittest.main()
