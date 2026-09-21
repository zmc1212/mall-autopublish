import importlib.util
import os
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

        def fake_set(hwnd, x, y, w=0, h=0, show=None, activate=False):
            moved.append((hwnd, x, y, activate))
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
        self.assertTrue(any(item[0] == 11 and item[3] for item in moved))

    def test_process_tree_includes_fake_root_pid(self):
        pids = web.process_tree_pids(424242)
        self.assertIn(424242, pids)

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
            with unittest.mock.patch.object(
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


if __name__ == '__main__':
    unittest.main()
