"""页签回收回归：条目内即时回收、preserve 瘦身、adopt 容错、全局对账。

背景（2026-10-03）：并发入库的浏览器页签只增不减，registry 中同一商品
挂着 8 个重复 success.htm 受保护页签。根因是规格图分批补传每批提交后
编辑页跳转 success.htm，而历史页签回收只按 publish.htm 匹配；preserve
又把该商品全部页签标记 protected，prune 永远跳过。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import 千牛网页执行 as web
from web_fill import pipeline
from web_fill.browser_pool import PageLease, PageOwnershipRegistry


class ItemTabUrlTests(unittest.TestCase):
    def test_matches_publish_and_success_pages_of_same_item(self):
        item = "1090065736075"
        self.assertTrue(pipeline._is_item_tab_url(
            "https://item.upload.taobao.com/sell/v2/publish.htm?itemId=" + item, item))
        self.assertTrue(pipeline._is_item_tab_url(
            "https://item.upload.taobao.com/sell/v2/success.htm"
            "?primaryId=" + item + "&catId=50012720&isEdit=true&pageStyle=", item))
        # 编辑页会落在 item.manager 域名（2026-10-01 远程日志）。
        self.assertTrue(pipeline._is_item_tab_url(
            "https://item.manager.taobao.com/sell/v2/publish.htm?itemId=" + item, item))

    def test_rejects_other_items_and_pages(self):
        item = "1090065736075"
        self.assertFalse(pipeline._is_item_tab_url(
            "https://item.upload.taobao.com/sell/v2/success.htm?primaryId=1090069152154", item))
        self.assertFalse(pipeline._is_item_tab_url(
            "https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1090069152154", item))
        # 成功页的 ID 参数是 primaryId，publish 用 itemId，不能交叉误认。
        self.assertFalse(pipeline._is_item_tab_url(
            "https://item.upload.taobao.com/sell/v2/publish.htm?primaryId=" + item, item))
        self.assertFalse(pipeline._is_item_tab_url(
            "https://myseller.taobao.com/home.htm/SellManage/all_skucenter", item))
        self.assertFalse(pipeline._is_item_tab_url(
            "https://item.upload.taobao.com/sell/v2/publish.htm?itemId=" + item, ""))
        self.assertFalse(pipeline._is_item_tab_url("", item))


class _FakeSession:
    """tab_list/tab_close 形状的假会话，输出与 isolated CLI 一致。"""

    def __init__(self, tabs):
        # tabs: [{"index": int, "url": str, "current": bool}]
        self.tabs = tabs
        self.closed = []

    def tab_list(self, owned_only=None):
        return "\n".join(
            f"- {tab['index']}: {'(current) ' if tab['current'] else ''}({tab['url']})"
            for tab in self.tabs
        )

    def tab_select(self, target):
        for tab in self.tabs:
            if tab["index"] == int(target):
                for other in self.tabs:
                    other["current"] = other is tab
                return

    def tab_close(self, target=None, *, force=False):
        if target is None:
            victim = next((tab for tab in self.tabs if tab["current"]), None)
        else:
            victim = next((tab for tab in self.tabs
                           if tab["index"] == int(target)), None)
        if victim is None:
            raise RuntimeError("无法定位页签")
        self.closed.append(victim["url"])
        self.tabs = [tab for tab in self.tabs if tab is not victim]


class CloseStaleItemTabsTests(unittest.TestCase):
    def test_server_verification_preserves_the_original_uncertain_edit_tab(self):
        item = "1090921726589"
        url = "https://item.upload.taobao.com/sell/v2/publish.htm?itemId=" + item
        for close_stale in (False, True):
            with self.subTest(close_stale=close_stale):
                session = _FakeSession([{"index": 0, "url": url, "current": True}])

                def tab_new(href):
                    for tab in session.tabs:
                        tab['current'] = False
                    session.tabs.append({"index": 1, "url": href, "current": True})

                session.tab_new = tab_new
                pipeline._open_item_edit_tab(session, item, close_stale=close_stale)
                self.assertEqual(len(session.closed), 1 if close_stale else 0)
                self.assertEqual(len(session.tabs), 1 if close_stale else 2)
                self.assertTrue(session.tabs[-1]['current'])

    def test_closes_stale_success_tab_keeps_current(self):
        item = "1090065736075"
        session = _FakeSession([
            {"index": 0, "url": "https://myseller.taobao.com/home.htm/QnworkbenchHome/",
             "current": False},
            {"index": 1, "url": "https://item.upload.taobao.com/sell/v2/success.htm"
             "?primaryId=" + item + "&isEdit=true", "current": False},
            {"index": 2, "url": "https://item.upload.taobao.com/sell/v2/publish.htm?itemId=" + item,
             "current": True},
        ])
        closed = pipeline._close_stale_item_tabs(session, item, keep_current=True)
        self.assertEqual(closed, 1)
        self.assertEqual(len(session.closed), 1)
        self.assertIn("success.htm", session.closed[0])
        self.assertEqual(len(session.tabs), 2)

    def test_recycle_success_tabs_closes_success_page_of_item(self):
        item = "1090065736075"
        session = _FakeSession([
            {"index": 0, "url": "https://item.upload.taobao.com/sell/v2/success.htm"
             "?primaryId=" + item + "&isEdit=true", "current": True},
            {"index": 1, "url": "https://myseller.taobao.com/home.htm/QnworkbenchHome/",
             "current": False},
        ])
        closed = pipeline._recycle_success_tabs(session, item)
        self.assertGreaterEqual(closed, 1)
        # 当前页是商品成功页：先切到可停靠页签再关，保证 CLI 当前页不失效。
        self.assertTrue(session.tabs[0]["current"])
        self.assertIn("success.htm", " ".join(session.closed))


class _FakeBrowser:
    def __init__(self):
        self.pages = []
        self._next_target = 1

    def add(self, url):
        page = {"url": url or "about:blank", "marker": "",
                "target_id": f"target-{self._next_target}"}
        self._next_target += 1
        self.pages.append(page)
        return len(self.pages) - 1


class _FakeCli:
    def __init__(self, browser):
        self.browser = browser
        self.current = None

    def __call__(self, args, raw=True):
        command = args[0]
        if command == "attach":
            if self.current is None:
                self.current = 0 if self.browser.pages else self.browser.add("about:blank")
            return ""
        if command == "tab-list":
            return "\n".join(
                f"{index} {page['url']}" for index, page in enumerate(self.browser.pages))
        if command == "tab-new":
            url = args[1] if len(args) > 1 else "about:blank"
            self.current = self.browser.add(url)
            return str(self.current)
        if command == "tab-select":
            self.current = int(args[1])
            return ""
        if command == "goto":
            self.browser.pages[self.current]["url"] = str(args[1])
            return ""
        if command == "tab-close":
            if self.current is None:
                return ""
            self.browser.pages.pop(self.current)
            self.current = min(self.current, len(self.browser.pages) - 1)
            return ""
        if command == "eval":
            page = self.browser.pages[self.current]
            expression = str(args[1])
            if "window.name =" in expression:
                value = expression.split("window.name =", 1)[1].split(";", 1)[0].strip()
                page["marker"] = value
                return value
            if "window.name" in expression:
                return page["marker"]
            if "location.href" in expression:
                return page["url"]
            return "{}"
        if command == "run-code":
            return "{\"targetId\": \"%s\"}" % self.browser.pages[self.current]["target_id"]
        if command == "detach":
            return ""
        raise AssertionError(f"unexpected fake CLI command: {args!r}")


class _SessionCase(unittest.TestCase):
    def _session(self, root, browser, name="worker-1"):
        return web.CliSession(
            runner=_FakeCli(browser), session_name=name, worker_id=name,
            output_dir=root / name, registry_path=root / "registry.json",
            isolated=True,
        )


class PreserveSlimTests(_SessionCase):
    def test_preserve_keeps_only_current_scene_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = _FakeBrowser()
            session = self._session(root, browser)
            session.begin_item("product", "https://a.example/home")
            session.tab_new("https://a.example/edit")
            registry = PageOwnershipRegistry(root / "registry.json")
            self.assertEqual(len(registry.list(key="product")), 2)

            session.finish_item(preserve=True)

            leases = registry.list(key="product")
            self.assertEqual(len(leases), 1)
            self.assertTrue(leases[0].protected)
            # 现场页是暂停发生的编辑页；历史 home 页签连同记录一起回收。
            self.assertEqual(leases[0].url, "https://a.example/edit")
            self.assertEqual(
                [page["url"] for page in browser.pages if page["url"] != "about:blank"],
                ["https://a.example/edit"])

    def test_preserve_without_active_page_keeps_newest_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = _FakeBrowser()
            session = self._session(root, browser)
            session.begin_item("product", "https://a.example/home")
            session.tab_new("https://a.example/edit")
            session._active_marker = ""  # 模拟极端场景：active 标记丢失
            session.finish_item(preserve=True)

            registry = PageOwnershipRegistry(root / "registry.json")
            leases = registry.list(key="product")
            self.assertEqual(len(leases), 1)
            self.assertEqual(leases[0].url, "https://a.example/edit")


class AdoptToleranceTests(_SessionCase):
    def test_begin_item_skips_dead_lease_and_selects_alive_scene(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = _FakeBrowser()
            old = self._session(root, browser)
            old.begin_item("product", "https://a.example/home")
            old.tab_new("https://a.example/edit")
            old.detach()
            # 模拟旧现场页签被外部关闭：home 页签消失，registry 记录仍在。
            self._drop_page(browser, "https://a.example/home")
            resumed = self._session(root, browser, name="worker-2")

            lease = resumed.begin_item("product")

            self.assertEqual(lease.url, "https://a.example/edit")
            registry = PageOwnershipRegistry(root / "registry.json")
            records = registry.list(key="product")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].target_id, lease.target_id)

    def test_begin_item_falls_back_to_older_lease_when_newest_dead(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = _FakeBrowser()
            old = self._session(root, browser)
            old.begin_item("product", "https://a.example/home")
            old.tab_new("https://a.example/edit")
            old.detach()
            # 最新编辑页签消失，只剩较旧但存活的 home 页签。
            self._drop_page(browser, "https://a.example/edit")
            resumed = self._session(root, browser, name="worker-2")

            lease = resumed.begin_item("product")

            self.assertEqual(lease.url, "https://a.example/home")
            registry = PageOwnershipRegistry(root / "registry.json")
            self.assertEqual(len(registry.list(key="product")), 1)

    @staticmethod
    def _drop_page(browser, url):
        browser.pages = [page for page in browser.pages if page["url"] != url]

    def test_begin_item_recovers_when_all_adopted_leases_are_dead(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = _FakeBrowser()
            old = self._session(root, browser)
            old.begin_item("product", "https://a.example/home")
            old.finish_item(preserve=True)
            browser.pages.clear()  # 浏览器重启：现场页签全部消失
            resumed = self._session(root, browser, name="worker-2")

            lease = resumed.begin_item("product")

            # 死租约全部清除后按新建路径开卖家首页，不再整条商品报错。
            self.assertEqual(lease.url, web.SELLER_HOME)
            registry = PageOwnershipRegistry(root / "registry.json")
            records = registry.list(key="product")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].target_id, lease.target_id)


class ReconcileBrowserTabsTests(unittest.TestCase):
    def _lease(self, **values):
        return PageLease.new(values.pop("owner"), values.pop("key"),
                             values.pop("session_name"), **values)

    def test_reconcile_releases_dead_leases_and_dedupes_same_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "owned_pages.json"
            registry = PageOwnershipRegistry(registry_path)
            registry.claim(self._lease(
                owner="w1", key="key-a", session_name="s1",
                marker="m-dead", target_id="target-dead", pid=1))
            registry.claim(self._lease(
                owner="w1", key="key-b", session_name="s1",
                marker="m-old", target_id="target-old", pid=1,
                created_at=1000.0, state="parked"))
            registry.claim(self._lease(
                owner="w1", key="key-b", session_name="s1",
                marker="m-new", target_id="target-new", pid=1,
                created_at=2000.0, state="parked"))
            closed_targets = []

            with mock.patch.object(web, "cdp_available", return_value=True), \
                 mock.patch.object(web, "_page_tabs", return_value=[
                     {"id": "target-old", "type": "page", "url": "https://a.example/success"},
                     {"id": "target-new", "type": "page", "url": "https://a.example/edit"},
                 ]), \
                 mock.patch.object(web, "_cdp_close_tab",
                                   side_effect=lambda target: closed_targets.append(target)), \
                 mock.patch.object(web, "prune_automation_tabs",
                                   return_value={"closed": 0, "kept": 2}), \
                 mock.patch.object(web, "_all_registry_paths", return_value={registry_path}):
                result = web.reconcile_browser_tabs()

            self.assertEqual(result["released"], 1)
            self.assertIn("target-old", closed_targets)
            self.assertNotIn("target-new", closed_targets)
            records = {lease.marker: lease for lease in registry.list()}
            self.assertNotIn("m-dead", records)
            self.assertNotIn("m-old", records)
            self.assertIn("m-new", records)

    def test_reconcile_never_touches_active_lease_of_live_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "owned_pages.json"
            registry = PageOwnershipRegistry(registry_path)
            registry.claim(self._lease(
                owner="w1", key="key-a", session_name="s1",
                marker="m-live-old", target_id="target-live-old",
                pid=os.getpid(), created_at=1000.0))
            registry.claim(self._lease(
                owner="w1", key="key-a", session_name="s1",
                marker="m-live-new", target_id="target-live-new",
                pid=os.getpid(), created_at=2000.0))
            closed_targets = []

            with mock.patch.object(web, "cdp_available", return_value=True), \
                 mock.patch.object(web, "_page_tabs", return_value=[
                     {"id": "target-live-old", "type": "page", "url": "https://a.example/one"},
                     {"id": "target-live-new", "type": "page", "url": "https://a.example/two"},
                 ]), \
                 mock.patch.object(web, "_cdp_close_tab",
                                   side_effect=lambda target: closed_targets.append(target)), \
                 mock.patch.object(web, "prune_automation_tabs",
                                   return_value={"closed": 0, "kept": 2}), \
                 mock.patch.object(web, "_all_registry_paths", return_value={registry_path}):
                web.reconcile_browser_tabs()

            # active 且进程存活的租约一律不动（可能是正在运行的任务）。
            self.assertEqual(closed_targets, [])
            self.assertEqual(len(registry.list()), 2)

    def test_reconcile_skips_cleanup_when_cdp_sees_no_tabs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "owned_pages.json"
            registry = PageOwnershipRegistry(registry_path)
            registry.claim(self._lease(
                owner="w1", key="key-a", session_name="s1",
                marker="m-any", target_id="target-any", pid=1))
            closed_targets = []

            with mock.patch.object(web, "cdp_available", return_value=True), \
                 mock.patch.object(web, "_page_tabs", return_value=[]), \
                 mock.patch.object(web, "_cdp_close_tab",
                                   side_effect=lambda target: closed_targets.append(target)):
                result = web.reconcile_browser_tabs()

            # CDP 读不到页签时无法核实死活，必须全部保留。
            self.assertEqual(result, {"released": 0, "closed": 0})
            self.assertEqual(closed_targets, [])
            self.assertEqual(len(registry.list()), 1)


class DuplicateMysellerTabsTests(unittest.TestCase):
    def test_closes_duplicate_seller_tabs_keeping_last(self):
        home = "https://myseller.taobao.com/home.htm/QnworkbenchHome/"
        sku = ("https://myseller.taobao.com/home.htm/SellManage/all_skucenter"
               "?from=qn_entry&current=1&pageSize=10")
        tabs = [
            {"id": "t1", "type": "page", "url": home},
            {"id": "t2", "type": "page", "url": sku},
            {"id": "t3", "type": "page", "url": home + "/"},
            {"id": "t4", "type": "page", "url": sku},
            {"id": "t5", "type": "page", "url": home},
        ]
        closed = []
        with mock.patch.object(web, "_page_tabs", return_value=tabs), \
             mock.patch.object(web, "_cdp_close_tab",
                               side_effect=lambda target: closed.append(target)):
            count = web._close_duplicate_myseller_tabs()
        # 同 URL 只留最后一个；尾部斜杠视为同一页签。
        self.assertEqual(count, 3)
        self.assertEqual(sorted(closed), ["t1", "t2", "t3"])

    def test_target_level_exemption_shields_only_the_protected_tab(self):
        home = "https://myseller.taobao.com/home.htm/QnworkbenchHome/"
        tabs = [
            {"id": "t1", "type": "page", "url": home},
            {"id": "t2", "type": "page", "url": home},
            {"id": "t3", "type": "page", "url": home},
        ]
        closed = []
        with mock.patch.object(web, "_page_tabs", return_value=tabs), \
             mock.patch.object(web, "_cdp_close_tab",
                               side_effect=lambda target: closed.append(target)):
            count = web._close_duplicate_myseller_tabs(skip_targets={"t3"})
        # t3 是受保护现场：豁免它之后只剩 t1/t2 两个副本，保留最后一个 t2。
        self.assertEqual(count, 1)
        self.assertEqual(closed, ["t1"])

    def test_url_level_exemption_for_legacy_lease_without_target(self):
        home = "https://myseller.taobao.com/home.htm/QnworkbenchHome/"
        tabs = [
            {"id": "t1", "type": "page", "url": home},
            {"id": "t2", "type": "page", "url": home},
        ]
        closed = []
        with mock.patch.object(web, "_page_tabs", return_value=tabs), \
             mock.patch.object(web, "_cdp_close_tab",
                               side_effect=lambda target: closed.append(target)):
            count = web._close_duplicate_myseller_tabs(skip_urls={home})
        self.assertEqual(count, 0)
        self.assertEqual(closed, [])

    def test_login_tabs_are_never_recycled(self):
        login = "https://login.taobao.com/member/login.jhtml"
        tabs = [
            {"id": "t1", "type": "page", "url": login},
            {"id": "t2", "type": "page", "url": login},
        ]
        closed = []
        with mock.patch.object(web, "_page_tabs", return_value=tabs), \
             mock.patch.object(web, "_cdp_close_tab",
                               side_effect=lambda target: closed.append(target)):
            count = web._close_duplicate_myseller_tabs()
        self.assertEqual(count, 0)
        self.assertEqual(closed, [])

    def test_reconcile_skips_url_dedupe_when_registry_corrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corrupt = root / "owned_pages.json"
            corrupt.write_text("{ not json", encoding="utf-8")
            home = "https://myseller.taobao.com/home.htm/QnworkbenchHome/"
            closed = []
            with mock.patch.object(web, "cdp_available", return_value=True), \
                 mock.patch.object(web, "_page_tabs", return_value=[
                     {"id": "t1", "type": "page", "url": home},
                     {"id": "t2", "type": "page", "url": home},
                 ]), \
                 mock.patch.object(web, "_cdp_close_tab",
                                   side_effect=lambda target: closed.append(target)), \
                 mock.patch.object(web, "prune_automation_tabs",
                                   return_value={"closed": 0, "kept": 2}), \
                 mock.patch.object(web, "_all_registry_paths", return_value={corrupt}):
                web.reconcile_browser_tabs()
            # registry 损坏是安全边界：对账不关闭任何页签。
            self.assertEqual(closed, [])


if __name__ == "__main__":
    unittest.main()
