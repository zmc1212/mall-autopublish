"""更新事务测试：使用临时的微型程序目录，不构建或替换真实客户端。"""

import json
import io
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlparse

from desktop import paths
from desktop import update_worker as worker
from desktop.updater import UpdateManager, confirm_boot, download_url, extract_package
from tools.build_inapp_update import build


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / "安装目录"
        self.new = self.root / "新版本"
        self.data = self.root / "登录态与设置"
        self.data.mkdir()
        self.env = patch.dict(os.environ, {"QIANNIU_APPDATA": str(self.data)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.install_patch = patch("desktop.paths.install_dir", return_value=self.install)
        self.install_patch.start()
        self.addCleanup(self.install_patch.stop)
        self.runtime = {"architecture": "windows-x64", "node": "22.0.0", "playwright": "1.60.0",
                        "chromium_revision": "1200", "chromium": "130.0.0", "webview2": "130.0.0"}
        self.baseline = self.root / "runtime-baseline.json"
        worker.write_json(self.baseline, self.runtime)
        self.make_app(self.install, "1.3.0.1", "old")
        self.make_app(self.new, "1.3.0.2", "new")
        worker.write_json(self.data / "settings.json", {"chrome_profile": str(self.data / "chrome-profile"),
                          "results_dir": str(self.data / "results"), "concurrency": 3, "update_feed_url": ""})
        (self.data / "chrome-profile").mkdir()
        (self.data / "chrome-profile" / "Cookies").write_bytes(b"login-cookie")
        (self.data / "license.json").write_bytes(b"activation")
        self.original_data = self.contents(self.data)

    def make_app(self, directory, version, marker):
        directory.mkdir()
        for name in (worker.EXE_NAME, "_internal/python3.dll", "web/index.html", "templates/registry.json",
                     "web_fill/scripts/main_images.js", "workspace.py"):
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(marker, encoding="utf-8")
        worker.write_json(directory / "runtime-manifest.json", self.runtime | {"application": version})

    @staticmethod
    def contents(directory):
        return {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob("*") if p.is_file()}

    def package(self):
        return build(self.new, self.root / "output", "修复上传逻辑", baseline_path=self.baseline)[0]

    def delta_packages(self):
        stable = random.Random(42).randbytes(64 * 1024)
        for directory in (self.install, self.new):
            (directory / "_internal" / "stable.bin").write_bytes(stable)
        (self.install / "web" / "obsolete.js").write_text("removed", encoding="utf-8")
        (self.new / "workspace.py").unlink(missing_ok=True)
        build(self.install, self.root / "output", baseline_path=self.baseline)
        package = self.package()
        feed = worker.read_json(package.parent / "latest.json")
        self.assertEqual(len(feed["deltas"]), 1)
        return package, package.parent / feed["deltas"][0]["url"], feed

    def transaction(self):
        package = self.package()
        directory = self.data / "updates" / "transaction"
        directory.mkdir(parents=True)
        stage = directory / "payload"
        manifest = extract_package(package, stage)
        journal = directory / "transaction.json"
        value = {"journal": str(journal), "install": str(self.install), "stage": str(stage),
                 "backup": str(directory / "backup"), "manifest": manifest, "token": "test-token",
                 "protected": [str(self.data)], "phase": "prepared", "parent_pid": os.getpid()}
        worker.write_json(journal, value)
        return journal, value

    def test_builder_excludes_browser_runtimes_and_user_data(self):
        for relative in ("browser/chrome.exe", "node/node.exe", "playwright-core/index.js",
                         "chrome-profile/Cookies", "settings.json"):
            target = self.new / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("private", encoding="utf-8")
        with zipfile.ZipFile(self.package()) as archive:
            names = archive.namelist()
            self.assertTrue(all(info.compress_type == zipfile.ZIP_LZMA for info in archive.infolist()))
            self.assertFalse(any(n.startswith(("browser/", "node/", "playwright-core/", "chrome-profile/")) for n in names))
            self.assertNotIn("settings.json", names)
        feed = worker.read_json(self.root / "output" / "latest.json")
        self.assertEqual(feed["sha256"], worker.digest(self.root / "output" / feed["url"]))

    def test_update_success_removes_stale_assets_and_preserves_login_and_settings(self):
        (self.install / "web" / "old-hash.js").write_text("stale", encoding="utf-8")
        journal, transaction = self.transaction()
        launches = []

        def launch(value, *, updated):
            launches.append(updated)
            worker.write_json(journal.parent / "healthy.json", {"token": value["token"], "version": value["manifest"]["version"]})
            return SimpleNamespace(poll=lambda: None)

        self.assertTrue(worker.perform_update(journal, launcher=launch, health_timeout=1))
        self.assertEqual(self.contents(self.install), self.contents(self.new))
        self.assertFalse((self.install / "web" / "old-hash.js").exists())
        self.assertEqual(launches, [True])
        for name, value in self.original_data.items():
            self.assertEqual((self.data / name).read_bytes(), value)
        self.assertTrue((Path(transaction["backup"]) / worker.EXE_NAME).is_file())

    def test_existing_deflate_complete_packages_remain_importable(self):
        legacy = self.root / "legacy.zip"
        with zipfile.ZipFile(self.package()) as source, zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                target.writestr(info.filename, source.read(info))
        stage = self.root / "legacy-payload"
        extract_package(legacy, stage)
        self.assertEqual(self.contents(stage), self.contents(self.new))

    def test_failed_start_rolls_back_complete_old_app(self):
        before = self.contents(self.install)
        journal, transaction = self.transaction()
        launches = []

        def launch(value, *, updated):
            launches.append(updated)
            return SimpleNamespace(poll=lambda: 1)

        self.assertFalse(worker.perform_update(journal, launcher=launch, health_timeout=1))
        self.assertEqual(self.contents(self.install), before)
        self.assertEqual(launches, [True, False])
        self.assertEqual(worker.read_json(journal.parent / "result.json")["status"], "rolled_back")
        for name, value in self.original_data.items():
            self.assertEqual((self.data / name).read_bytes(), value)

    def test_healthy_ack_does_not_accept_a_process_that_already_exited(self):
        journal, transaction = self.transaction()
        before = self.contents(self.install)

        def launch(value, *, updated):
            worker.write_json(journal.parent / "healthy.json", {"token": value["token"], "version": value["manifest"]["version"]})
            return SimpleNamespace(poll=lambda: 1)

        self.assertFalse(worker.perform_update(journal, launcher=launch, health_timeout=1))
        self.assertEqual(self.contents(self.install), before)

    def test_wait_parent_uses_real_process_exit(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.25)"])
        try:
            worker.wait_parent(process.pid, timeout=5)
            self.assertIsNotNone(process.poll())
        finally:
            process.wait(timeout=5)

    def test_partial_file_replacement_failure_rolls_back(self):
        before = self.contents(self.install)
        journal, transaction = self.transaction()
        real_copy = worker.copy
        failed = False

        def copy(source, target):
            nonlocal failed
            if source.parent == Path(transaction["stage"]) and source.name == "web" and not failed:
                failed = True
                raise PermissionError("模拟文件占用")
            return real_copy(source, target)

        with patch.object(worker, "copy", side_effect=copy):
            self.assertFalse(worker.perform_update(journal, launcher=lambda *a, **k: None))
        self.assertTrue(failed)
        self.assertEqual(self.contents(self.install), before)

    def test_boot_timeout_and_wrong_token_roll_back(self):
        journal, transaction = self.transaction()
        before = self.contents(self.install)

        def launch(value, *, updated):
            worker.write_json(journal.parent / "healthy.json", {"token": "wrong", "version": value["manifest"]["version"]})
            return SimpleNamespace(poll=lambda: None)

        with patch.object(worker, "terminate") as terminate:
            self.assertFalse(worker.perform_update(journal, launcher=launch, health_timeout=0.05))
            terminate.assert_called_once()
        self.assertEqual(self.contents(self.install), before)

    def test_rollback_failure_keeps_backup_and_reports_path(self):
        journal, transaction = self.transaction()
        with patch.object(worker, "rollback", side_effect=PermissionError("磁盘只读")):
            self.assertFalse(worker.perform_update(journal, launcher=lambda *a, **k: SimpleNamespace(poll=lambda: 1)))
        result = worker.read_json(journal.parent / "result.json")
        self.assertEqual(result["status"], "rollback_failed")
        self.assertEqual(result["backup"], transaction["backup"])
        self.assertTrue((Path(result["backup"]) / worker.EXE_NAME).is_file())

    def test_zip_rejects_undeclared_paths_and_tampering(self):
        for extra in ("../settings.json", "web/evil.js", "C:/evil.py", "web/CON", "web/file:ads", "web/INDEX.html"):
            package = self.package()
            with zipfile.ZipFile(package, "a") as archive:
                archive.writestr(extra, "malicious")
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                extract_package(package, self.root / "invalid-payload")
        package = self.package()
        extracted = self.root / "valid-payload"
        manifest = extract_package(package, extracted)
        (extracted / "web" / "index.html").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "校验失败"):
            worker.validate_payload(extracted, manifest)

    def test_worker_rejects_changed_staging_before_touching_install(self):
        journal, transaction = self.transaction()
        before = self.contents(self.install)
        (Path(transaction["stage"]) / worker.EXE_NAME).write_text("bad", encoding="utf-8")
        self.assertFalse(worker.perform_update(journal, launcher=lambda *a, **k: None))
        self.assertEqual(self.contents(self.install), before)

    def test_preserved_directory_overlap_blocks_update(self):
        journal, transaction = self.transaction()
        transaction["protected"].append(str(self.install / "templates" / "user-data"))
        worker.write_json(journal, transaction)
        before = self.contents(self.install)
        self.assertFalse(worker.perform_update(journal, launcher=lambda *a, **k: None))
        self.assertEqual(self.contents(self.install), before)

    def test_settings_feed_persists_without_changing_login_paths(self):
        settings = paths.load_settings()
        settings.update_feed_url = "https://download.example/latest.json"
        paths.save_settings(settings)
        saved = paths.load_settings()
        self.assertEqual(saved.update_feed_url, settings.update_feed_url)
        self.assertEqual(saved.chrome_profile, str(self.data / "chrome-profile"))
        self.assertEqual(saved.concurrency, 3)

    def test_download_address_rejects_insecure_remote_urls(self):
        for value in ("http://example.com/latest.json", "file:///C:/update.zip", "https://user:secret@example.com/a"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                download_url(value)
        self.assertEqual(download_url("http://127.0.0.1:9000/latest.json"), "http://127.0.0.1:9000/latest.json")

    def test_import_and_runtime_mismatch_never_modify_install(self):
        updater = UpdateManager()
        before = self.contents(self.install)
        updater.import_package(str(self.package()))
        updater._operation.join(5)
        self.assertEqual(updater.snapshot()["status"], "ready")
        self.assertEqual(self.contents(self.install), before)
        runtime = worker.read_json(self.new / "runtime-manifest.json")
        runtime["chromium_revision"] = "different"
        worker.write_json(self.new / "runtime-manifest.json", runtime)
        worker.write_json(self.baseline, runtime)
        updater.import_package(str(self.package()))
        updater._operation.join(5)
        self.assertEqual(updater.snapshot()["status"], "error")
        self.assertIn("完整安装包", updater.snapshot()["error"])
        self.assertIn("chromium_revision：当前 1200，更新包要求 different", updater.snapshot()["error"])
        self.assertEqual(self.contents(self.install), before)

    def test_runtime_error_identifies_webview_drift_without_modifying_install(self):
        before = self.contents(self.install)
        runtime = worker.read_json(self.new / "runtime-manifest.json")
        runtime["webview2"] = "154.0.4258.62"
        worker.write_json(self.new / "runtime-manifest.json", runtime)
        worker.write_json(self.baseline, runtime)
        updater = UpdateManager()
        updater.import_package(str(self.package()))
        updater._operation.join(5)
        state = updater.snapshot()
        self.assertEqual(state["status"], "error")
        self.assertIn("webview2：当前 130.0.0，更新包要求 154.0.4258.62", state["error"])
        self.assertNotIn("chromium_revision", state["error"])
        self.assertEqual(self.contents(self.install), before)

    def test_builder_rejects_runtime_drift_before_replacing_published_files(self):
        self.package()
        before = self.contents(self.root / "output")
        runtime = worker.read_json(self.new / "runtime-manifest.json")
        runtime["webview2"] = "154.0.4258.62"
        worker.write_json(self.new / "runtime-manifest.json", runtime)
        with self.assertRaisesRegex(ValueError, "webview2"):
            self.package()
        self.assertEqual(self.contents(self.root / "output"), before)

    def test_waits_for_thread_cleanup_even_after_status_done(self):
        updater = UpdateManager()
        updater.import_package(str(self.package()))
        updater._operation.join(5)
        release = threading.Event()
        task = threading.Thread(target=lambda: release.wait(5), daemon=True)
        task.start()
        self.addCleanup(release.set)
        jobs = SimpleNamespace(lock=threading.RLock(), status="done", thread=task, update_pending=False)
        closed, launched = threading.Event(), threading.Event()
        updater.jobs, updater.close_window = jobs, closed.set
        with patch("desktop.paths.is_frozen", return_value=True), patch.object(updater, "_launch_worker", side_effect=launched.set):
            updater.schedule()
            self.assertTrue(jobs.update_pending)
            time.sleep(1.1)
            self.assertFalse(launched.is_set())
            release.set()
            task.join(1)
            self.assertTrue(closed.wait(3))
            updater._watcher.join(2)
            self.assertTrue(launched.is_set())

    def test_restart_now_does_not_wait_for_running_job(self):
        from desktop.jobs import JobManager

        updater = UpdateManager()
        updater.import_package(str(self.package()))
        updater._operation.join(5)
        jobs = JobManager()
        release = threading.Event()
        jobs.status = "running"
        jobs.thread = threading.Thread(target=lambda: release.wait(5), daemon=True)
        jobs.thread.start()
        self.addCleanup(release.set)
        closed, launched = threading.Event(), threading.Event()
        updater.jobs, updater.close_window = jobs, closed.set
        with patch("desktop.paths.is_frozen", return_value=True), patch.object(updater, "_launch_worker", side_effect=launched.set):
            state = updater.restart_now()
            self.assertEqual(state["status"], "restarting")
            self.assertTrue(jobs.update_pending)
            self.assertEqual(jobs.status, "stopping")
            self.assertTrue(launched.is_set())
            self.assertTrue(closed.wait(2))
        self.assertTrue(jobs.thread.is_alive())  # 未等待任务收尾。
        self.assertIn("立即重启", updater.snapshot()["message"])

    def test_restart_now_launch_failure_keeps_package_ready(self):
        updater = UpdateManager()
        updater.import_package(str(self.package()))
        updater._operation.join(5)
        jobs = SimpleNamespace(lock=threading.RLock(), status="idle", thread=None, update_pending=False)
        updater.jobs, updater.close_window = jobs, lambda: None
        with patch("desktop.paths.is_frozen", return_value=True), patch.object(
                updater, "_launch_worker", side_effect=RuntimeError("磁盘空间不足")):
            state = updater.restart_now()
        self.assertEqual(state["status"], "ready")
        self.assertFalse(jobs.update_pending)
        self.assertIn("磁盘空间不足", state["error"])
        self.assertIn("更新包仍保留", state["message"])

    def test_boot_recovers_restarting_state_without_transaction(self):
        updater = UpdateManager()
        updater.import_package(str(self.package()))
        updater._operation.join(5)
        with updater.lock:
            updater._set(status="restarting", message="正在立即重启更新")
        jobs = SimpleNamespace(lock=threading.RLock(), status="idle", thread=None, update_pending=False)
        updater.configure(jobs, lambda: None)
        self.assertEqual(updater.snapshot()["status"], "ready")
        self.assertFalse(jobs.update_pending)
        self.assertIn("更新包仍保留", updater.snapshot()["message"])

    def test_restart_now_requires_frozen_client(self):
        updater = UpdateManager()
        with patch("desktop.paths.is_frozen", return_value=False), self.assertRaisesRegex(RuntimeError, "源码开发模式"):
            updater.restart_now()

    def test_cancel_allows_new_jobs_without_replacing_files(self):
        from desktop.jobs import JobManager

        updater = UpdateManager()
        updater.import_package(str(self.package()))
        updater._operation.join(5)
        jobs = JobManager()
        jobs.status = "running"
        updater.jobs, updater.close_window = jobs, lambda: None
        with patch("desktop.paths.is_frozen", return_value=True):
            updater.schedule()
            with self.assertRaisesRegex(RuntimeError, "取消自动重启"):
                jobs.start_job()
            updater.cancel()
            self.assertFalse(jobs.update_pending)
            self.assertEqual(updater.snapshot()["status"], "ready")
            updater._watcher.join(2)

    def test_source_mode_never_replaces_source(self):
        updater = UpdateManager()
        with patch("desktop.paths.is_frozen", return_value=False), self.assertRaisesRegex(RuntimeError, "源码开发模式"):
            updater.schedule()

    def test_source_mode_can_validate_without_packaged_runtime_manifest(self):
        (self.install / "runtime-manifest.json").unlink()
        updater = UpdateManager()
        with patch("desktop.paths.is_frozen", return_value=False):
            updater.import_package(str(self.package()))
            updater._operation.join(5)
            self.assertEqual(updater.snapshot()["status"], "ready")
            with self.assertRaisesRegex(RuntimeError, "源码开发模式"):
                updater.schedule()

    def test_startup_keeps_prepared_package_and_rollback_notice(self):
        updater = UpdateManager()
        updater.import_package(str(self.package()))
        updater._operation.join(5)
        settings = paths.load_settings()
        settings.update_feed_url = "https://example.com/latest.json"
        paths.save_settings(settings)
        jobs = SimpleNamespace(lock=threading.RLock(), status="idle", thread=None, update_pending=False)
        with patch.object(updater, "check") as check:
            updater.configure(jobs, lambda: None)
            check.assert_not_called()
            self.assertEqual(updater.snapshot()["status"], "ready")
            with updater.lock:
                updater._set(status="rolled_back", message="更新失败，已恢复旧版本")
            updater.configure(jobs, lambda: None)
            check.assert_not_called()
            self.assertEqual(updater.snapshot()["status"], "rolled_back")

    def test_new_process_uses_independent_pyinstaller_environment(self):
        journal, transaction = self.transaction()
        with patch.object(worker.subprocess, "Popen") as popen:
            worker.launch(transaction, updated=True)
            env = popen.call_args.kwargs["env"]
            self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")
            self.assertEqual(env["QIANNIU_UPDATE_TRANSACTION"], str(journal))
            worker.launch(transaction, updated=False)
            self.assertNotIn("QIANNIU_UPDATE_TRANSACTION", popen.call_args.kwargs["env"])

    def test_react_boot_confirmation_checks_version_and_token(self):
        journal, transaction = self.transaction()
        with patch.dict(os.environ, {"QIANNIU_UPDATE_TRANSACTION": str(journal)}):
            with self.assertRaisesRegex(RuntimeError, "版本不匹配"):
                confirm_boot()
            worker.apply_files(transaction, journal)
            self.assertTrue(confirm_boot()["ok"])
        self.assertEqual(worker.read_json(journal.parent / "healthy.json")["token"], transaction["token"])

    def test_update_api_requires_activation_and_reports_errors(self):
        from fastapi.testclient import TestClient
        from desktop.server import app

        client = TestClient(app)
        with patch("desktop.license.is_activated", return_value=False):
            self.assertEqual(client.get("/api/update").status_code, 403)
            self.assertEqual(client.post("/api/update/boot-ready").status_code, 200)
        with patch("desktop.license.is_activated", return_value=True), patch("desktop.server.UPDATER", UpdateManager()):
            self.assertEqual(client.get("/api/update").json()["current_version"], "1.3.0.1")
            self.assertEqual(client.post("/api/update/check").status_code, 400)
            self.assertEqual(client.put("/api/settings", json={"update_feed_url": "http://example.com/feed"}).status_code, 400)


class DeltaUpdateTests(unittest.TestCase):
    def setUp(self):
        self.f = UpdateTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.package, self.delta, self.feed = self.f.delta_packages()

    def transaction(self):
        directory = self.f.data / "updates" / "delta-transaction"
        directory.mkdir(parents=True)
        manifest = extract_package(self.delta, directory / "payload")
        journal = directory / "transaction.json"
        value = {"journal": str(journal), "install": str(self.f.install), "stage": str(directory / "payload"),
                 "backup": str(directory / "backup"), "manifest": manifest, "token": "delta-token",
                 "phase": "prepared", "protected": [str(self.f.data)]}
        worker.write_json(journal, value)
        return journal, value

    def online(self, *, replacements=None, feed=None):
        responses = {self.package.name: self.package.read_bytes(), self.delta.name: self.delta.read_bytes(),
                     "latest.json": json.dumps(feed or self.feed).encode()}
        responses.update(replacements or {})
        calls = []

        def request(url):
            name = urlparse(url).path.rsplit("/", 1)[-1]
            calls.append(name)
            value = responses[name]
            if isinstance(value, Exception):
                raise value
            stream = io.BytesIO(value)
            stream.geturl = lambda: url
            return stream

        settings = paths.load_settings()
        settings.update_feed_url = "https://updates.example/path/latest.json"
        paths.save_settings(settings)
        updater = UpdateManager()
        with patch("desktop.updater.open_url", side_effect=request):
            updater.check()
            updater._operation.join(10)
            self.assertEqual(updater.snapshot()["status"], "available")
            updater.download()
            updater._operation.join(10)
            self.assertFalse(updater._operation.is_alive())
        return updater, calls

    def test_delta_contains_only_changes_and_reconstructs_complete_payload(self):
        with zipfile.ZipFile(self.delta) as archive:
            manifest = json.loads(archive.read("update.json"))
            self.assertEqual(set(archive.namelist()), set(manifest["changed"]) | {"update.json"})
            self.assertNotIn("_internal/stable.bin", archive.namelist())
            self.assertEqual(set(manifest["deleted"]), {"workspace.py", "web/obsolete.js"})
            self.assertTrue(all(info.compress_type == zipfile.ZIP_LZMA for info in archive.infolist()))
        stage = self.f.root / "stage"
        complete = extract_package(self.delta, stage)
        self.assertEqual(complete["schema"], 1)  # 继续使用现有的完整目录更新事务。
        self.assertEqual(self.f.contents(stage), self.f.contents(self.f.new))

    def test_delta_install_removes_files_and_keeps_user_data(self):
        journal, value = self.transaction()

        def launch(transaction, *, updated):
            worker.write_json(journal.parent / "healthy.json", {"token": transaction["token"], "version": transaction["manifest"]["version"]})
            return SimpleNamespace(poll=lambda: None)

        self.assertTrue(worker.perform_update(journal, launcher=launch, health_timeout=1))
        self.assertEqual(self.f.contents(self.f.install), self.f.contents(self.f.new))
        self.assertTrue((Path(value["backup"]) / "workspace.py").is_file())
        for name, content in self.f.original_data.items():
            self.assertEqual((self.f.data / name).read_bytes(), content)

    def test_delta_start_failure_restores_deleted_and_changed_files(self):
        before = self.f.contents(self.f.install)
        journal, _ = self.transaction()
        launches = []

        def launch(transaction, *, updated):
            launches.append(updated)
            return SimpleNamespace(poll=lambda: 1)

        self.assertFalse(worker.perform_update(journal, launcher=launch))
        self.assertEqual(self.f.contents(self.f.install), before)
        self.assertEqual(launches, [True, False])

    def test_changed_or_missing_baseline_is_rejected_without_modifying_install(self):
        source = self.f.install / "_internal" / "stable.bin"
        original = source.read_bytes()
        for missing in (False, True):
            if missing:
                source.unlink()
            else:
                source.write_bytes(b"corrupt")
            before = self.f.contents(self.f.install)
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "基线不匹配"):
                extract_package(self.delta, self.f.root / "invalid")
            self.assertEqual(self.f.contents(self.f.install), before)
            source.write_bytes(original)

    def test_forged_delta_file_lists_and_payload_are_rejected(self):
        with zipfile.ZipFile(self.delta) as archive:
            manifest = json.loads(archive.read("update.json"))
        for key, value in [("deleted", []), ("changed", []), ("changed", manifest["changed"] * 2)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                worker.validate_manifest(manifest | {key: value})
        with zipfile.ZipFile(self.delta, "a") as archive:
            archive.writestr("web/undeclared.js", "tampered")
        with self.assertRaisesRegex(ValueError, "清单不匹配"):
            extract_package(self.delta, self.f.root / "bad-payload")

    def test_matching_version_downloads_delta_only(self):
        updater, calls = self.online()
        self.assertEqual(calls, ["latest.json", self.delta.name])
        self.assertEqual(updater.snapshot()["status"], "ready")
        self.assertEqual(updater.state["package_kind"], "delta")
        self.assertEqual(self.f.contents(Path(updater.state["prepared"]) / "payload"), self.f.contents(self.f.new))

    def test_missing_or_corrupt_delta_automatically_uses_full_package(self):
        for replacement in (b"truncated", HTTPError("https://updates.example/delta.zip", 404, "Not found", {}, None)):
            with self.subTest(replacement=type(replacement).__name__):
                updater, calls = self.online(replacements={self.delta.name: replacement})
                self.assertEqual(calls, ["latest.json", self.delta.name, self.package.name])
                self.assertEqual(updater.snapshot()["status"], "ready")
                self.assertEqual(updater.state["package_kind"], "full")

    def test_baseline_drift_automatically_uses_full_package(self):
        (self.f.install / "_internal" / "stable.bin").write_bytes(b"locally changed")
        before = self.f.contents(self.f.install)
        updater, calls = self.online()
        self.assertEqual(calls, ["latest.json", self.delta.name, self.package.name])
        self.assertEqual(updater.snapshot()["status"], "ready")
        self.assertEqual(self.f.contents(self.f.install), before)

    def test_other_version_and_malformed_optional_delta_use_full_package(self):
        runtime = worker.read_json(self.f.install / "runtime-manifest.json")
        worker.write_json(self.f.install / "runtime-manifest.json", runtime | {"application": "1.3.0.0"})
        for deltas in (self.feed["deltas"], [None, {"base_version": "1.3.0.0", "url": "file:///C:/bad.zip"}], "bad"):
            updater, calls = self.online(feed=self.feed | {"deltas": deltas})
            self.assertEqual(calls, ["latest.json", self.package.name])
            self.assertEqual(updater.snapshot()["status"], "ready")

    def test_access_denial_does_not_retry_another_package(self):
        for code in (401, 403):
            updater, calls = self.online(replacements={self.delta.name: HTTPError("https://updates.example/delta.zip", code, "Denied", {}, None)})
            self.assertEqual(calls, ["latest.json", self.delta.name])
            self.assertEqual(updater.snapshot()["status"], "error")
            self.assertIn(str(code), updater.snapshot()["error"])

    def test_corrupt_full_fallback_reports_failure_and_preserves_install(self):
        before = self.f.contents(self.f.install)
        updater, calls = self.online(replacements={self.delta.name: b"bad", self.package.name: b"bad"})
        self.assertEqual(calls, ["latest.json", self.delta.name, self.package.name])
        self.assertEqual(updater.snapshot()["status"], "error")
        self.assertEqual(self.f.contents(self.f.install), before)

    def test_explicit_invalid_base_cannot_overwrite_published_files(self):
        before = self.f.contents(self.package.parent)
        with self.assertRaisesRegex(ValueError, "基线"):
            build(self.f.new, self.package.parent, baseline_path=self.f.baseline, base_package=self.package)
        self.assertEqual(self.f.contents(self.package.parent), before)

    def test_no_delta_option_keeps_a_legacy_compatible_complete_package(self):
        _, feed = build(self.f.new, self.f.root / "full-only", baseline_path=self.f.baseline, deltas=False)
        self.assertEqual(worker.read_json(feed)["deltas"], [])
        with zipfile.ZipFile(self.package) as archive:
            self.assertEqual(json.loads(archive.read("update.json"))["schema"], 1)

    def test_delta_without_size_benefit_is_not_advertised(self):
        (self.f.new / "_internal" / "stable.bin").write_bytes(random.Random(43).randbytes(64 * 1024))
        package = self.f.package()
        self.assertEqual(worker.read_json(package.parent / "latest.json")["deltas"], [])
        self.assertFalse(self.delta.exists())


if __name__ == "__main__":
    unittest.main()
