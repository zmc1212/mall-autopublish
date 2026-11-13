import json
import os
import socket
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


import desktop.session_sync as session_sync


class SessionSyncTests(unittest.TestCase):
    def test_endpoint_aliases_normalize_to_the_same_local_identity(self):
        self.assertEqual(
            session_sync._endpoint_identity("http://LOCALHOST:9222/"),
            session_sync._endpoint_identity("http://127.0.0.1:9222"),
        )
        self.assertEqual(
            session_sync._endpoint_identity("http://[::1]:9222/"),
            session_sync._endpoint_identity("http://localhost:9222"),
        )

    def test_same_cdp_port_is_rejected_before_any_endpoint_probe(self):
        with mock.patch.object(session_sync, "_endpoint_available") as available, mock.patch.object(
            session_sync, "_node_sync_result"
        ) as node:
            result = session_sync.sync_login_session(
                "http://127.0.0.1:9222",
                source_endpoint="http://localhost:9222/",
                web_module=SimpleNamespace(CDP_ENDPOINT="http://localhost:9222"),
            )

        self.assertFalse(result["ok"])
        self.assertFalse(result["applied"])
        self.assertEqual(result["reason"], "same_endpoint")
        available.assert_not_called()
        node.assert_not_called()

    def test_low_level_node_helper_also_rejects_same_cdp_port(self):
        with mock.patch.object(session_sync.subprocess, "run") as run:
            result = session_sync._node_sync_result(
                "http://localhost:9222",
                "http://127.0.0.1:9222/",
                "",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "same_endpoint")
        run.assert_not_called()

    def test_sync_only_passes_endpoints_to_node_and_returns_status_counts(self):
        node_result = {
            "ok": True,
            "source_available": True,
            "applied": True,
            "cookies": 2,
            "origins": 1,
            "navigated": True,
        }
        with mock.patch.object(session_sync, "_endpoint_available", return_value=True), mock.patch.object(
            session_sync, "_node_sync_result", return_value=node_result
        ) as node:
            result = session_sync.sync_login_session(
                "http://127.0.0.1:43210",
                source_endpoint="http://127.0.0.1:9222",
                navigate_url="https://item.taobao.com/item.htm?id=1",
                web_module=SimpleNamespace(CDP_ENDPOINT="http://127.0.0.1:9222"),
            )

        self.assertEqual(result, node_result)
        node.assert_called_once_with(
            "http://127.0.0.1:9222",
            "http://127.0.0.1:43210",
            "https://item.taobao.com/item.htm?id=1",
        )

    def test_node_helper_stdin_contains_no_storage_values(self):
        captured = {}
        output = json.dumps({
            "ok": True,
            "source_available": True,
            "applied": True,
            "cookies": 1,
            "origins": 1,
            "navigated": False,
            "unexpected": "must not escape",
        })

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return SimpleNamespace(returncode=0, stdout=output, stderr="secret-like stderr")

        with mock.patch.object(session_sync.subprocess, "run", side_effect=fake_run):
            result = session_sync._node_sync_result(
                "http://127.0.0.1:9222",
                "http://127.0.0.1:43210",
                "",
            )

        payload = str(captured["kwargs"]["input"])
        self.assertNotIn("synthetic", payload)
        self.assertNotIn("secret-like", payload)
        self.assertEqual(result, {
            "ok": True,
            "source_available": True,
            "applied": True,
            "cookies": 1,
            "origins": 1,
            "navigated": False,
        })
        self.assertIn("-e", captured["command"])
        self.assertNotIn("stderr", result)

    def test_node_helper_filters_source_state_before_apply(self):
        """Exercise the same Node filter used by the packaged runtime.

        The fake Playwright module rejects any unfiltered state in
        ``setStorageState``. This keeps the test independent from a live
        browser while verifying that the production helper does the filtering
        before the state reaches the target context.
        """

        node_path = session_sync.paths.node_exe_path()
        if not node_path or not Path(node_path).is_file():
            self.skipTest("bundled Node is unavailable")
        fake_module = r'''
"use strict";
const sourceState = {
  cookies: [
    { name: "sid", value: "secret-cookie-value", domain: ".taobao.com", path: "/" },
    { name: "external", value: "should-not-copy", domain: ".example.com", path: "/" }
  ],
  origins: [
    { origin: "https://myseller.taobao.com", localStorage: [{ name: "token", value: "secret-storage-value" }] },
    { origin: "https://example.com", localStorage: [{ name: "external", value: "should-not-copy" }] }
  ]
};
const sourceContext = {
  cookies: async () => sourceState.cookies,
  pages: () => [{ frames: () => sourceState.origins.map(item => ({
    url: () => item.origin,
    evaluate: async () => item.localStorage
  })) }]
};
const targetContext = {
  setStorageState: async state => {
    if (state.cookies.length !== 1 || state.cookies[0].domain !== ".taobao.com") throw new Error("cookie filter failed");
    if (state.origins.length !== 1 || state.origins[0].origin !== "https://myseller.taobao.com") throw new Error("origin filter failed");
    if (state.origins[0].localStorage.length !== 1 || state.origins[0].localStorage[0].name !== "token") throw new Error("storage filter failed");
  },
  pages: () => []
};
module.exports = {
  chromium: {
    connectOverCDP: async endpoint => ({
      contexts: () => [endpoint === "source" ? sourceContext : targetContext],
      close: async () => {}
    })
  }
};
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = Path(temp_dir)
            (package_path / "index.js").write_text(fake_module, encoding="utf-8")
            payload = json.dumps({
                "sourceEndpoint": "source",
                "targetEndpoint": "target",
                "navigateUrl": "",
                "playwrightPath": str(package_path),
            }, separators=(",", ":"))
            completed = session_sync.subprocess.run(
                [str(node_path), "-e", session_sync._NODE_SYNC_SCRIPT],
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                creationflags=getattr(session_sync.subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout), {
            "ok": True,
            "source_available": True,
            "applied": True,
            "cookies": 1,
            "origins": 1,
            "navigated": False,
        })

    def test_empty_allowed_cookie_state_is_reported_as_not_logged_in(self):
        with mock.patch.object(session_sync, "_endpoint_available", return_value=True), mock.patch.object(
            session_sync,
            "_node_sync_result",
            return_value={
                "ok": True,
                "source_available": True,
                "applied": True,
                "cookies": 0,
                "origins": 0,
                "navigated": True,
            },
        ):
            result = session_sync.sync_login_session(
                "http://127.0.0.1:43210", web_module=SimpleNamespace(CDP_ENDPOINT="http://127.0.0.1:9222")
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["source_available"])
        self.assertEqual(result["reason"], "not_logged_in")
        self.assertFalse(result["applied"])

    def test_target_unavailable_does_not_start_node_sync(self):
        with mock.patch.object(session_sync, "_endpoint_available", side_effect=[True, False]), mock.patch.object(
            session_sync, "_node_sync_result"
        ) as node:
            result = session_sync.sync_login_session(
                "http://127.0.0.1:43210", web_module=SimpleNamespace(CDP_ENDPOINT="http://127.0.0.1:9222")
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["source_available"])
        node.assert_not_called()

    def test_source_unavailable_is_fail_soft(self):
        with mock.patch.object(session_sync, "_endpoint_available", return_value=False), mock.patch.object(
            session_sync, "_node_sync_result"
        ) as node:
            result = session_sync.sync_login_session(
                "http://127.0.0.1:43210", web_module=SimpleNamespace(CDP_ENDPOINT="http://127.0.0.1:9222")
            )

        self.assertFalse(result["ok"])
        self.assertFalse(result["source_available"])
        node.assert_not_called()


class SessionSyncBrowserTests(unittest.TestCase):
    def test_live_cdp_sync_preserves_source_and_updates_existing_target_storage(self):
        """Catch CDP storageState() omitting origins from already open tabs."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Python Playwright is unavailable")
        browser = session_sync.paths.bundled_browser_path() or session_sync.paths.browser_exe_path()
        if not browser:
            self.skipTest("Chromium is unavailable")

        def free_port():
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                return listener.getsockname()[1]

        with tempfile.TemporaryDirectory(prefix="qianniu-session-test-", ignore_cleanup_errors=True) as temp:
            with sync_playwright() as playwright, ExitStack() as cleanup:
                contexts = []
                ports = []
                for name in ("source", "target"):
                    port = free_port()
                    context = playwright.chromium.launch_persistent_context(
                        str(Path(temp) / name), executable_path=str(browser), headless=True,
                        args=[f"--remote-debugging-port={port}"],
                    )
                    cleanup.callback(context.close)
                    context.route("**/*", lambda route: route.fulfill(
                        status=200, content_type="text/html", body="<body>Local session fixture</body>",
                    ))
                    context.pages[0].goto("https://seller.taobao.com/session-fixture")
                    contexts.append(context)
                    ports.append(port)
                source, target = contexts
                source_page, target_page = source.pages[0], target.pages[0]
                source_page.evaluate('localStorage.setItem("account", "first")')
                source.add_cookies([
                    {"name": "unb", "value": "first", "domain": ".taobao.com", "path": "/"},
                    {"name": "old", "value": "old", "domain": ".taobao.com", "path": "/"},
                    {"name": "external", "value": "outside", "domain": ".example.com", "path": "/"},
                ])
                target_page.evaluate('localStorage.setItem("stale", "old")')
                source_before = (source_page.url, source.cookies())

                def synchronize():
                    result = session_sync.sync_login_session(
                        f"http://127.0.0.1:{ports[1]}", source_endpoint=f"http://127.0.0.1:{ports[0]}",
                        web_module=SimpleNamespace(),
                    )
                    self.assertTrue(result["ok"], result)
                    self.assertEqual(result["origins"], 1)

                synchronize()
                self.assertEqual(target_page.evaluate('localStorage.getItem("account")'), "first")
                self.assertIsNone(target_page.evaluate('localStorage.getItem("stale")'))
                self.assertNotIn("external", {cookie["name"] for cookie in target.cookies()})
                self.assertEqual((source_page.url, source.cookies()), source_before)

                source.clear_cookies(name="old")
                source.add_cookies([{"name": "unb", "value": "second", "domain": ".taobao.com", "path": "/"}])
                source_page.evaluate('localStorage.setItem("account", "second")')
                synchronize()
                self.assertEqual(target_page.evaluate('localStorage.getItem("account")'), "second")
                self.assertNotIn("old", {cookie["name"] for cookie in target.cookies()})
                self.assertFalse(target_page.is_closed())
                target_page.evaluate('localStorage.setItem("account", "website-refresh")')
                target_page.reload()
                self.assertEqual(target_page.evaluate('localStorage.getItem("account")'), "website-refresh")


if __name__ == "__main__":
    unittest.main()
