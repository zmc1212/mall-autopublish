"""Real headed-Chrome regression for closing the last window.

Only temporary profiles, random CDP ports and a local HTTP fixture are used.
No account cookies or application profile are read or modified.
"""
import importlib.util
import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<title>Session persistence fixture</title><body>Local test</body>")

    def log_message(self, *_args):
        pass


@unittest.skipUnless(os.name == "nt", "Windows Chrome protected-preference regression")
class BrowserSessionPersistenceTests(unittest.TestCase):
    def test_last_window_close_retains_session_cookie_and_local_storage(self):
        from playwright.sync_api import sync_playwright

        spec = importlib.util.spec_from_file_location(
            "web_persistence_test", Path(__file__).with_name("千牛网页执行.py")
        )
        web = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(web)
        if not web.CHROME.is_file() or web._playwright_package_path() is None:
            self.skipTest("Chromium/Playwright runtime unavailable")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.assertNotEqual(port, 9222)
        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        fixture_url = f"http://127.0.0.1:{server.server_port}/fixture"

        with tempfile.TemporaryDirectory(prefix="qianniu-manual-close-", ignore_cleanup_errors=True) as temp:
            profile = Path(temp).resolve() / "黄宝" / "千牛自动上架" / "chrome profile"
            env = {"QIANNIU_PROFILE": str(profile), "QIANNIU_CDP_PORT": str(port)}
            with mock.patch.dict(os.environ, env), sync_playwright() as playwright, ExitStack() as cleanup:
                web.reload_paths()
                self.assertEqual(web.PROFILE.resolve(), profile)
                self.assertEqual(web.CDP_PORT, port)

                def launch(reconnect=False):
                    # Never call configure_environ here: it can restore the real
                    # application's profile and 9222, defeating test isolation.
                    args = web.chrome_launch_args()
                    self.assertIn(f"--user-data-dir={profile}", args)
                    self.assertIn(f"--remote-debugging-port={port}", args)
                    args.extend(["--window-position=-32000,-32000", "--disable-background-mode"])
                    proc = subprocess.Popen(
                        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    if not reconnect:
                        web._CHROME_PROC, web._CHROME_ROOT_PID = proc, proc.pid
                    def stop_fixture_process():
                        if proc.poll() is None:
                            proc.kill()
                            proc.wait(timeout=5)
                    cleanup.callback(stop_fixture_process)
                    self.assertTrue(web._wait_cdp_ready(10))
                    if reconnect:
                        self.assertIsNot(web._CHROME_PROC, proc)
                        with mock.patch.object(
                            web.subprocess, "check_output", side_effect=OSError("PowerShell unavailable")
                        ):
                            command = web._process_command_line(proc.pid)
                        self.assertIn(str(profile), command)
                        self.assertTrue(web._is_automation_chrome_command(command))
                        self.assertEqual(web._adopt_connected_automation_chrome(), proc.pid)
                        self.assertIsNone(web._CHROME_PROC)
                        self.assertIsNone(web._CHROME_SESSION_PREFS_KEY)
                    browser = playwright.chromium.connect_over_cdp(web.CDP_ENDPOINT)
                    cleanup.callback(browser.close)
                    return proc, browser, browser.contexts[0]

                def preference(context, value=None):
                    page = context.new_page()
                    try:
                        page.goto("chrome://settings/onStartup")
                        page.wait_for_function("Boolean(globalThis.chrome?.settingsPrivate)")
                        return page.evaluate("""async value => {
                          const api = chrome.settingsPrivate;
                          if (value !== null) await new Promise(resolve =>
                            api.setPref('session.restore_on_startup', value, '', resolve));
                          return new Promise(resolve => api.getPref(
                            'session.restore_on_startup', pref => resolve(pref.value)));
                        }""", value)
                    finally:
                        page.close()

                def close_last_window(proc, browser, context):
                    # Target close matches the user's last-window X path. Do not
                    # use Browser.close CDP, which took a different shutdown path.
                    for page in list(context.pages):
                        page.close()
                    proc.wait(timeout=12)
                    browser.close()

                proc, browser, context = launch()
                self.assertEqual(preference(context, 5), 5)
                close_last_window(proc, browser, context)

                # Recreate the previous implementation's direct disk write on
                # an existing profile with protected startup preference = 5.
                pref_path = profile / "Default" / "Preferences"
                disk_prefs = json.loads(pref_path.read_text(encoding="utf-8"))
                disk_prefs.setdefault("session", {})["restore_on_startup"] = 1
                pref_path.write_text(json.dumps(disk_prefs), encoding="utf-8")

                proc, browser, context = launch()
                before = preference(context)
                web.ensure_chrome_runtime_session_prefs()
                self.assertEqual(preference(context), 1)
                page = context.pages[0]
                page.goto(fixture_url)
                context.add_cookies([{
                    "name": "session_marker", "value": "synthetic", "url": fixture_url,
                }])
                page.evaluate("localStorage.setItem('session_marker', 'synthetic')")
                close_last_window(proc, browser, context)

                proc, browser, context = launch(reconnect=True)
                web.ensure_chrome_runtime_session_prefs()
                self.assertEqual(preference(context), 1)
                cookies = context.cookies([fixture_url])
                self.assertTrue(any(
                    cookie["name"] == "session_marker" and cookie["value"] == "synthetic"
                    and cookie["expires"] == -1 for cookie in cookies
                ), "session cookie disappeared after last-window close")
                page = context.pages[0]
                page.goto(fixture_url)
                self.assertEqual(page.evaluate("localStorage.getItem('session_marker')"), "synthetic")
                web.ensure_chrome_runtime_session_prefs()
                print(f"startup preference: disk=1 / previous runtime={before} / fixed runtime=1; "
                      "last-window close preserved session cookie and localStorage; "
                      "reconnected restarted browser with Chinese profile while PowerShell unavailable")
                close_last_window(proc, browser, context)


if __name__ == "__main__":
    unittest.main()
