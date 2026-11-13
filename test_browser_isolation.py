import json
import ctypes
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


import 千牛网页执行 as web

_POOL_SPEC = importlib.util.spec_from_file_location(
    "browser_pool_test", Path(__file__).with_name("web_fill") / "browser_pool.py"
)
browser_pool = importlib.util.module_from_spec(_POOL_SPEC)
sys.modules[_POOL_SPEC.name] = browser_pool
_POOL_SPEC.loader.exec_module(browser_pool)
PageLease = browser_pool.PageLease
PageOwnershipRegistry = browser_pool.PageOwnershipRegistry


class _FakeBrowser:
    def __init__(self):
        self.pages = []
        self._next_target = 1

    def add(self, url, checkpoint=None):
        page = {
            "url": url or "about:blank",
            "marker": "",
            "target_id": f"target-{self._next_target}",
            "checkpoint": checkpoint,
        }
        self._next_target += 1
        self.pages.append(page)
        return len(self.pages) - 1


class _FakeCli:
    """A local Playwright CLI-shaped browser for ownership interleaving tests."""

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
            return "\n".join(f"{index} {page['url']}" for index, page in enumerate(self.browser.pages))
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
                page["marker"] = json.loads(value)
                return json.dumps(page["marker"])
            if "window.name" in expression:
                return json.dumps(page["marker"])
            if "location.href" in expression:
                return json.dumps(page["url"])
            if "sessionStorage.getItem" in expression:
                return "### Result\n" + json.dumps(page.get("checkpoint"))
            return "{}"
        if command == "run-code":
            return json.dumps({"targetId": self.browser.pages[self.current]["target_id"]})
        if command == "detach":
            return ""
        raise AssertionError(f"unexpected fake CLI command: {args!r}")


class BrowserIsolationTests(unittest.TestCase):
    def test_new_isolated_item_opens_category_without_tab_scan(self):
        """A fresh worker already owns its seller-home lease after begin_item."""
        from web_fill import pipeline

        class FreshSession:
            isolated = True
            item_had_existing_pages = False

            def __init__(self):
                self.current = "https://myseller.taobao.com/home.htm/qnworkbenchhome"
                self.calls = []

            def attach(self):
                self.calls.append("attach")

            def href(self):
                return self.current

            def tab_new(self, url):
                self.calls.append(("tab_new", url))
                self.current = url

            def body_text(self, _limit):
                return ""

            def tab_list(self):
                self.calls.append("tab_list")
                raise AssertionError("fresh item must not scan all tabs")

        class Web:
            @staticmethod
            def is_publish_page(_href):
                return False

            @staticmethod
            def assert_safe_url(_href):
                return None

            @staticmethod
            def assert_logged_in(_href, _text=""):
                return None

        session = FreshSession()
        with mock.patch.object(pipeline.time, "sleep", return_value=None):
            href, how = pipeline.ensure_fill_tab(session, Web())
        self.assertEqual(how, "new-category")
        self.assertIn("category.htm", href)
        self.assertNotIn("tab_list", session.calls)
        self.assertEqual(
            [call[0] for call in session.calls if isinstance(call, tuple)],
            ["tab_new"],
        )

    def test_resumed_isolated_category_reuses_refresh_cache_once(self):
        """A just-refreshed owned cache avoids a second index-wide scan."""
        from web_fill import pipeline

        class Lease:
            url = "https://item.upload.taobao.com/sell/v2/category.htm?catId=1"

        class ResumedSession:
            isolated = True
            item_had_existing_pages = True

            def __init__(self):
                self.current = "https://myseller.taobao.com/home.htm/qnworkbenchhome"
                self.list_calls = 0

            def attach(self):
                return None

            def href(self):
                return self.current

            def tab_list(self):
                self.list_calls += 1
                return "- 0: (https://myseller.taobao.com/home.htm/qnworkbenchhome)"

            def owned_page_leases(self, *, refresh=True):
                self.assert_not_refresh = refresh
                return [Lease()]

            def tab_select(self, _lease):
                self.current = Lease.url

        class Web:
            @staticmethod
            def is_publish_page(_href):
                return False

            @staticmethod
            def assert_logged_in(_href, _text=""):
                return None

        session = ResumedSession()
        with mock.patch.object(pipeline.time, "sleep", return_value=None):
            href, how = pipeline.ensure_fill_tab(session, Web())
        self.assertEqual(how, "reuse-category")
        self.assertIn("category.htm", href)
        self.assertEqual(session.list_calls, 1)
        self.assertFalse(session.assert_not_refresh)

    def test_windows_process_probe_never_uses_os_kill(self):
        kernel32 = mock.Mock()
        kernel32.OpenProcess.return_value = 0
        with mock.patch.object(browser_pool.os, "name", "nt"), mock.patch.object(
            browser_pool.os, "kill"
        ) as kill, mock.patch.object(
            ctypes, "WinDLL", return_value=kernel32, create=True
        ), mock.patch.object(ctypes, "get_last_error", return_value=87, create=True):
            self.assertFalse(browser_pool._process_alive(987654))
        kill.assert_not_called()

    def test_two_sessions_keep_distinct_item_pages_when_interleaved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "browser_ownership.json"
            browser = _FakeBrowser()
            one = web.CliSession(
                runner=_FakeCli(browser),
                session_name="worker-1",
                worker_id="worker-1",
                output_dir=root / "worker-1",
                registry_path=registry,
                isolated=True,
            )
            two = web.CliSession(
                runner=_FakeCli(browser),
                session_name="worker-2",
                worker_id="worker-2",
                output_dir=root / "worker-2",
                registry_path=registry,
                isolated=True,
            )

            lease_one = one.begin_item("product-one", "http://127.0.0.1/item-one")
            lease_two = two.begin_item("product-two", "http://127.0.0.1/item-two")
            self.assertNotEqual(lease_one.marker, lease_two.marker)
            self.assertEqual(one.href(), "http://127.0.0.1/item-one")
            self.assertEqual(two.href(), "http://127.0.0.1/item-two")

            one.tab_new("http://127.0.0.1/item-one/sku")
            self.assertEqual(len(PageOwnershipRegistry(registry).list(owner="worker-1", key="product-one")), 2)

            two.tab_select(lease_two)
            one.tab_select(lease_one)
            self.assertEqual(one.href(), "http://127.0.0.1/item-one")
            self.assertEqual(two.href(), "http://127.0.0.1/item-two")

            one.finish_item(preserve=True)
            self.assertTrue(PageOwnershipRegistry(registry).get_marker(lease_one.marker).protected)
            with self.assertRaisesRegex(RuntimeError, "其他 worker|当前 worker"):
                two.tab_close(lease_one)

    def test_isolated_attach_does_not_run_global_cleanup(self):
        runner = _FakeCli(_FakeBrowser())
        with mock.patch.object(web, "start_persistent_chrome"), mock.patch.object(
            web, "close_redundant_seller_home_tabs"
        ) as cleanup:
            session = web.CliSession(runner=runner, isolated=True, session_name="worker-1")
            session.attach()
        cleanup.assert_not_called()

    def test_target_id_survives_cross_origin_and_duplicate_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "browser_ownership.json"
            browser = _FakeBrowser()
            session = web.CliSession(
                runner=_FakeCli(browser),
                session_name="worker-1",
                worker_id="worker-1",
                output_dir=root / "worker-1",
                registry_path=registry,
                isolated=True,
            )
            first = session.begin_item("product-one", "https://a.example/item")
            session.tab_new("https://a.example/item")
            second = session.active_lease
            self.assertNotEqual(first.target_id, second.target_id)
            session.goto("https://b.example/publish")
            session.tab_select(first)
            self.assertEqual(session.href(), "https://a.example/item")
            session.tab_select(second)
            self.assertEqual(session.href(), "https://b.example/publish")
            listed = session.tab_list()
            self.assertIn("https://a.example/item", listed)
            self.assertIn("https://b.example/publish", listed)

    def test_stale_index_falls_back_to_refreshed_target_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = _FakeBrowser()
            runner = _FakeCli(browser)
            session = web.CliSession(
                runner=runner, session_name="worker-1", worker_id="worker-1",
                output_dir=root / "worker", registry_path=root / "registry.json",
                isolated=True,
            )
            first = session.begin_item("first", "https://a.example/one")
            session.tab_new("https://a.example/two")
            second = session.active_lease
            session.tab_list()  # materialize mutable indexes in the registry
            browser.pages.pop(0)  # external close shifts second from index 1 to 0
            session.tab_select(second)
            self.assertEqual(session.href(), "https://a.example/two")

    def test_refresh_prefers_registered_indexes_over_unowned_tabs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = _FakeBrowser()

            class CountingCli(_FakeCli):
                def __init__(self, value):
                    super().__init__(value)
                    self.selected = []

                def __call__(self, args, raw=True):
                    if args and args[0] == "tab-select":
                        self.selected.append(int(args[1]))
                    return super().__call__(args, raw=raw)

            runner = CountingCli(browser)
            session = web.CliSession(
                runner=runner, session_name="worker-1", worker_id="worker-1",
                output_dir=root / "worker", registry_path=root / "registry.json",
                isolated=True,
            )
            session.begin_item("product", "https://a.example/one")
            session.tab_new("https://a.example/two")
            # Materialize both mutable indexes before unrelated workers add
            # pages.  The next refresh should verify only those owned indexes.
            session.tab_list()
            owned_indexes = {
                lease.index for lease in PageOwnershipRegistry(root / "registry.json").list()
            }
            runner.selected.clear()
            for index in range(20):
                browser.add(f"https://unowned.example/{index}")

            session.tab_list()
            self.assertTrue(runner.selected)
            self.assertTrue(all(index in owned_indexes for index in runner.selected), runner.selected)
            self.assertEqual(len(PageOwnershipRegistry(root / "registry.json").list()), 2)

    def test_new_claim_captures_explicit_current_index_as_hint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = _FakeBrowser()

            class CurrentCli(_FakeCli):
                def __call__(self, args, raw=True):
                    if args and args[0] == "tab-list":
                        return "\n".join(
                            f"- {index}: {'(current) ' if index == self.current else ''}({page['url']})"
                            for index, page in enumerate(self.browser.pages)
                        )
                    return super().__call__(args, raw=raw)

            session = web.CliSession(
                runner=CurrentCli(browser), session_name="worker-1", worker_id="worker-1",
                output_dir=root / "worker", registry_path=root / "registry.json",
                isolated=True,
            )
            lease = session.begin_item("product", "https://a.example/one")
            registered = PageOwnershipRegistry(root / "registry.json").get_marker(lease.marker)
            self.assertEqual(registered.index, 1)

    def test_refresh_does_not_move_target_bound_lease_by_cloned_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = _FakeBrowser()
            runner = _FakeCli(browser)
            session = web.CliSession(
                runner=runner, session_name="worker-1", worker_id="worker-1",
                output_dir=root / "worker", registry_path=root / "registry.json",
                isolated=True,
            )
            lease = session.begin_item("product", "https://a.example/one")
            session.tab_list()
            # Put an unrelated page at the registered index and clone the
            # marker.  A target-bound lease must remain attached to its real
            # target and be recovered by the remaining-index scan.
            registered = PageOwnershipRegistry(root / "registry.json").get_marker(lease.marker)
            owned_index = registered.index
            clone_index = browser.add("https://unowned.example/clone")
            browser.pages[clone_index]["marker"] = lease.marker
            PageOwnershipRegistry(root / "registry.json").update(registered, index=clone_index)

            session.tab_list()
            current = PageOwnershipRegistry(root / "registry.json").get_marker(lease.marker)
            self.assertEqual(current.target_id, lease.target_id)
            self.assertEqual(current.index, owned_index)

    def test_closing_active_page_selects_a_remaining_owned_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = _FakeBrowser()
            session = web.CliSession(
                runner=_FakeCli(browser), session_name="worker-1", worker_id="worker-1",
                output_dir=root / "worker", registry_path=root / "registry.json",
                isolated=True,
            )
            first = session.begin_item("product", "https://a.example/one")
            session.tab_new("https://a.example/two")
            session.tab_close()
            self.assertEqual(session.href(), "https://a.example/one")
            self.assertEqual(session.active_lease.marker, first.marker)

    def test_preserved_pages_can_be_handed_to_new_run_but_live_pages_cannot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "browser_ownership.json"
            browser = _FakeBrowser()
            old = web.CliSession(
                runner=_FakeCli(browser), session_name="run-old-worker-1",
                worker_id="run-old-worker-1", output_dir=root / "old",
                registry_path=registry, isolated=True,
            )
            old.begin_item("product-one", "https://a.example/item")
            live_new = web.CliSession(
                runner=_FakeCli(browser), session_name="run-new-worker-1",
                worker_id="run-new-worker-1", output_dir=root / "live",
                registry_path=registry, isolated=True,
            )
            with self.assertRaisesRegex(RuntimeError, "active worker"):
                live_new.begin_item("product-one", "https://a.example/other")
            old.finish_item(preserve=True)
            old.detach()
            resumed = web.CliSession(
                runner=_FakeCli(browser), session_name="run-next-worker-1",
                worker_id="run-next-worker-1", output_dir=root / "next",
                registry_path=registry, isolated=True,
            )
            lease = resumed.begin_item("product-one")
            self.assertEqual(lease.owner, "run-next-worker-1")
            self.assertEqual(lease.state, "active")

    def test_explicit_legacy_checkpoint_adoption_requires_unique_key_and_href(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "browser_ownership.json"
            browser = _FakeBrowser()
            legacy_url = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=1"
            browser.add(legacy_url, {"key": "legacy-key", "href": legacy_url})
            session = web.CliSession(
                runner=_FakeCli(browser), session_name="new-worker",
                worker_id="new-worker", output_dir=root / "worker",
                registry_path=registry, isolated=True,
            )
            lease = session.begin_item(
                "legacy-key",
                resume_checkpoint={"key": "legacy-key", "href": legacy_url},
            )
            self.assertEqual(len(browser.pages), 1)
            self.assertEqual(lease.target_id, "target-1")
            self.assertEqual(lease.owner, "new-worker")

    def test_legacy_adoption_uses_target_id_when_an_owned_page_shares_the_url(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "browser_ownership.json"
            browser = _FakeBrowser()
            legacy_url = "https://item.upload.taobao.com/sell/v2/publish.htm?catId=1"
            owned = web.CliSession(
                runner=_FakeCli(browser), session_name="owned", worker_id="owned",
                output_dir=root / "owned", registry_path=registry, isolated=True,
            )
            owned.begin_item("other", legacy_url)
            browser.add(legacy_url, {"key": "legacy-key", "href": legacy_url})
            session = web.CliSession(
                runner=_FakeCli(browser), session_name="new-worker",
                worker_id="new-worker", output_dir=root / "worker",
                registry_path=registry, isolated=True,
            )
            lease = session.begin_item(
                "legacy-key",
                resume_checkpoint={"key": "legacy-key", "href": legacy_url},
            )
            self.assertEqual(lease.target_id, "target-3")

    def test_session_and_output_are_injected_into_cli_command(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "worker-output"
            completed = mock.Mock(returncode=0, stdout="ok", stderr="")
            with mock.patch.object(web, "cli_executable", return_value=["node", "cli.js"]), mock.patch.object(
                web.subprocess, "run", return_value=completed
            ) as run:
                session = web.CliSession(
                    session_name="worker-7",
                    output_dir=output,
                    isolated=False,
                )
                self.assertEqual(session.cmd("tab-list"), "ok")
            command = run.call_args.args[0]
            self.assertIn("-s=worker-7", command)
            self.assertEqual(run.call_args.kwargs["cwd"], str(output.resolve()))

    def test_prune_keeps_protected_url(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "workers" / "worker-1"
            registry = root / "workers" / "browser_ownership.json"
            PageOwnershipRegistry(registry).claim(
                PageLease.new(
                    "worker-1",
                    "product-one",
                    "worker-1",
                    url="https://item.upload.taobao.com/sell/v2/publish.htm?catId=1",
                    protected=True,
                )
            )
            tabs = [
                {"id": "protected", "type": "page", "url": "https://item.upload.taobao.com/sell/v2/publish.htm?catId=1"},
                {"id": "stale", "type": "page", "url": "about:blank"},
            ]
            with mock.patch.object(web, "OUTPUT_DIR", output), mock.patch.object(
                web, "cdp_available", return_value=True
            ), mock.patch.object(web, "cdp_tabs", return_value=tabs), mock.patch.object(
                web, "_cdp_close_tab"
            ) as close:
                result = web.prune_automation_tabs()
            self.assertEqual(result["kept"], 1)
            close.assert_called_once_with("stale")

    def test_corrupt_registry_fails_closed_for_global_prune(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "browser_ownership.json"
            registry.write_text("{broken", encoding="utf-8")
            tabs = [
                {"id": "maybe-owned", "type": "page", "url": "about:blank"},
            ]
            with mock.patch.object(web, "OUTPUT_DIR", root / "workers"), mock.patch.object(
                web, "cdp_available", return_value=True
            ), mock.patch.object(web, "_BROWSER_REGISTRY_PATHS", {str(registry)}), mock.patch.object(
                web, "cdp_tabs", return_value=tabs
            ), mock.patch.object(web, "_cdp_close_tab") as close:
                result = web.prune_automation_tabs()
            self.assertEqual(result["closed"], 0)
            self.assertEqual(result["kept"], 1)
            close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
