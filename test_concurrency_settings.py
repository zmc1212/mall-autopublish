import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class ConcurrencySettingsPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self._old_appdata = os.environ.get("QIANNIU_APPDATA")
        os.environ["QIANNIU_APPDATA"] = self.temp.name
        from desktop import paths

        self.paths = importlib.reload(paths)
        self.paths.configure_environ()

    def tearDown(self):
        if self._old_appdata is None:
            os.environ.pop("QIANNIU_APPDATA", None)
        else:
            os.environ["QIANNIU_APPDATA"] = self._old_appdata

    def test_missing_concurrency_uses_two(self):
        self.assertEqual(self.paths.Settings().concurrency, 2)
        self.assertEqual(self.paths.load_settings().concurrency, 2)

        self.paths.settings_path().write_text(
            json.dumps({"settings_version": 3, "limit": 10}), encoding="utf-8"
        )
        self.assertEqual(self.paths.load_settings().concurrency, 2)

    def test_concurrency_is_clamped_to_one_through_eight(self):
        self.assertEqual(self.paths.Settings(concurrency=0).normalized().concurrency, 2)
        self.assertEqual(self.paths.Settings(concurrency=-2).normalized().concurrency, 1)
        self.assertEqual(self.paths.Settings(concurrency=1).normalized().concurrency, 1)
        self.assertEqual(self.paths.Settings(concurrency=8).normalized().concurrency, 8)
        self.assertEqual(self.paths.Settings(concurrency=99).normalized().concurrency, 8)

    def test_save_settings_only_persists_and_does_not_reconfigure_runtime(self):
        runtime_env = {
            key: os.environ.get(key)
            for key in ("QIANNIU_PROFILE", "QIANNIU_CDP_PORT", "QIANNIU_OUTPUT_DIR")
        }
        with mock.patch.object(self.paths, "configure_environ") as configure:
            saved = self.paths.save_settings(
                self.paths.Settings(concurrency=5, cdp_port=9333, chrome_profile=str(Path(self.temp.name) / "new-profile"))
            )

        configure.assert_not_called()
        self.assertEqual(
            runtime_env,
            {key: os.environ.get(key) for key in runtime_env},
            "保存设置不应切换当前浏览器会话的 profile/端口上下文",
        )
        self.assertEqual(saved.concurrency, 5)
        raw = json.loads(self.paths.settings_path().read_text(encoding="utf-8"))
        self.assertEqual(raw["concurrency"], 5)
        self.assertEqual(self.paths.load_settings().concurrency, 5)


class ConcurrencySettingsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self._old_appdata = os.environ.get("QIANNIU_APPDATA")
        os.environ["QIANNIU_APPDATA"] = self.temp.name
        from desktop import paths

        self.paths = importlib.reload(paths)
        self.paths.configure_environ()
        self.license_patch = mock.patch("desktop.license.is_activated", return_value=True)
        self.license_patch.start()
        self.addCleanup(self.license_patch.stop)

    def tearDown(self):
        if self._old_appdata is None:
            os.environ.pop("QIANNIU_APPDATA", None)
        else:
            os.environ["QIANNIU_APPDATA"] = self._old_appdata

    def test_api_roundtrip_and_status_include_concurrency(self):
        from fastapi.testclient import TestClient
        from desktop.server import app

        client = TestClient(app)
        self.assertEqual(client.get("/api/settings").json()["concurrency"], 2)
        response = client.put("/api/settings", json={"concurrency": 8})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["concurrency"], 8)
        self.assertEqual(client.get("/api/settings").json()["concurrency"], 8)

    def test_api_rejects_non_strict_or_out_of_range_concurrency(self):
        from fastapi.testclient import TestClient
        from desktop.server import app

        client = TestClient(app)
        with mock.patch("desktop.server.MANAGER.apply_debug_browser", return_value=False):
            for value in (True, 2.0, "2", 0, 9):
                response = client.put("/api/settings", json={"concurrency": value})
                self.assertEqual(response.status_code, 422, (value, response.text))

    def test_job_start_passes_saved_concurrency_to_manager_snapshot(self):
        from fastapi.testclient import TestClient
        from desktop.server import MANAGER, app

        client = TestClient(app)
        with mock.patch.object(MANAGER, "start_job", return_value={"status": "running"}) as start:
            response = client.post("/api/job/start", json={"limit": 0})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(start.call_args.kwargs["concurrency"], 2)


if __name__ == "__main__":
    unittest.main()
