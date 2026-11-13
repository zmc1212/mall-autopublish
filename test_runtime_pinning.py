"""运行环境固定与打包前置校验；不生成真实安装包。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import pin_desktop_runtime as pin


class RuntimePinningTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "完整程序"
        self.cache = self.root / "固定缓存"
        self.baseline = pin.load_baseline()
        self.values = {
            "node": {"node": self.baseline["node"]},
            "playwright-core": {k: self.baseline[k] for k in ("playwright", "chromium_revision")},
            "browser": {"chromium": self.baseline["chromium"]},
            "webview2": {"webview2": self.baseline["webview2"]},
        }
        for name, value in self.values.items():
            directory = self.source / name
            directory.mkdir(parents=True)
            (directory / "version.json").write_text(json.dumps(value), encoding="utf-8")
        mock = patch.object(pin, "inspect_component", side_effect=lambda name, directory: pin.read_json(directory / "version.json"))
        mock.start()
        self.addCleanup(mock.stop)

    def prepare(self):
        return pin.prepare(self.cache, self.baseline, [self.source], [])

    def test_system_upgrade_does_not_modify_or_reselect_pinned_runtime(self):
        self.prepare()
        before = pin.inventory(self.cache)
        (self.source / "webview2" / "version.json").write_text('{"webview2":"999.0.0.0"}')
        shutil.rmtree(self.source / "node")
        self.prepare()
        self.assertEqual(pin.inventory(self.cache), before)
        self.assertEqual(pin.read_json(self.cache / "baseline.json")["runtime"], self.baseline)

    def test_wrong_runtime_fails_without_creating_cache(self):
        (self.source / "webview2" / "version.json").write_text('{"webview2":"154.0.4258.62"}')
        with self.assertRaisesRegex(ValueError, "缺少固定运行环境 webview2"):
            self.prepare()
        self.assertFalse(self.cache.exists())

    def test_exact_webview_source_can_seed_older_client_baseline(self):
        exact = self.root / self.baseline["webview2"]
        shutil.copytree(self.source / "webview2", exact)
        (self.source / "webview2" / "version.json").write_text('{"webview2":"154.0.4258.62"}')
        pin.prepare(self.cache, self.baseline, [self.source], [exact])
        pin.verify_cache(self.cache, self.baseline)

    def test_corrupt_cache_is_not_silently_replaced(self):
        self.prepare()
        extra = self.cache / "playwright-core" / "changed.js"
        extra.write_text("unexpected")
        with self.assertRaisesRegex(ValueError, "缓存校验失败"):
            self.prepare()
        self.assertEqual(extra.read_text(), "unexpected")

    def test_changed_baseline_cannot_reuse_old_cache(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "webview2"):
            pin.prepare(self.cache, self.baseline | {"webview2": "999.0.0.0"}, [self.source], [])

    def test_failed_copy_never_leaves_partial_cache(self):
        with patch.object(pin.shutil, "copytree", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.prepare()
        self.assertFalse(self.cache.exists())
        self.assertFalse(list(self.root.glob("runtime-pin-*")))

    def test_incomplete_baseline_is_rejected(self):
        path = self.root / "invalid.json"
        path.write_text('{"webview2":"154.0.4258.37"}')
        with self.assertRaisesRegex(ValueError, "缺少版本字段"):
            pin.load_baseline(path)

    @unittest.skipUnless(os.name == "nt", "PowerShell packaging entry point")
    def test_clean_update_preflight_preserves_cache_and_previous_outputs(self):
        # 真正执行 PowerShell 入口，但故意让前置校验失败，绝不调用构建器。
        for filename in ("desktop/pack.ps1", "desktop/runtime-baseline.json", "tools/pin_desktop_runtime.py"):
            target = self.root / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pin.ROOT / filename, target)
        cache = self.root / ".work" / "desktop-runtime-pinned"
        cache.mkdir(parents=True)
        (cache / "baseline.json").write_text(json.dumps({"runtime": self.baseline | {"webview2": "wrong"}}))
        output = self.root / "dist" / "updates" / "latest.json"
        output.parent.mkdir(parents=True)
        output.write_text("previous release")
        env = os.environ | {"QIANNIU_PYTHON": sys.executable, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(self.root / "desktop" / "pack.ps1"), "-UpdateOnly", "-Clean"],
                                env=env, capture_output=True, timeout=30)
        combined = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Pinned runtime unavailable", combined)
        self.assertNotIn("==> build frontend", combined)
        self.assertTrue((cache / "baseline.json").is_file())
        self.assertEqual(output.read_text(), "previous release")


if __name__ == "__main__":
    unittest.main()
