"""并发入库调度器和执行会话事务的回归测试。"""

import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import job_session


class JobSessionConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                "QIANNIU_APPDATA": str(self.root / "appdata"),
                "QIANNIU_RESULTS_DIR": str(self.root / "results"),
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

        rows = [
            {
                "row": index,
                "product_id": f"P-{index}",
                "validation": "通过",
                "product": {"title": f"商品 {index}"},
            }
            for index in range(1, 5)
        ]
        job_session.remember_workbook(str(self.root / "清单.xlsx"), rows)

    def test_row_checkpoints_are_not_lost_when_workers_commit_together(self):
        barrier = threading.Barrier(4)

        def worker(row):
            barrier.wait(timeout=3)
            job_session.patch_flow_state(
                row,
                f"P-{row}",
                {"flow_stage": "created", "material_folder": f"folder-{row}"},
            )
            job_session.patch_execution(
                row,
                f"P-{row}",
                "已入库",
                notice=f"worker-{row}",
                extra={"run_status": "completed"},
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(worker, range(1, 5)))

        saved = job_session.load_session()
        by_row = {item["row"]: item for item in saved["rows"]}
        self.assertEqual(
            {row: by_row[row]["notice"] for row in by_row},
            {row: f"worker-{row}" for row in range(1, 5)},
        )
        self.assertEqual(
            {row: by_row[row]["material_folder"] for row in by_row},
            {row: f"folder-{row}" for row in range(1, 5)},
        )

    def test_checkpoint_write_error_is_visible_to_caller(self):
        with patch.object(job_session, "_save_session_unlocked", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                job_session.patch_flow_state(1, "P-1", {"flow_stage": "created"})

    def test_manager_save_does_not_replace_newer_flow_checkpoint(self):
        source = self.root / "清单.xlsx"
        source.write_bytes(b"placeholder")
        manager_rows = [{
            "row": 1,
            "product_id": "P-1",
            "validation": "通过",
            "execution": "未执行",
            "flow_stage": "pending",
        }]
        job_session.remember_workbook(str(source), manager_rows)
        job_session.patch_flow_state(
            1, "P-1", {"flow_stage": "created", "material_folder": "checkpoint"}
        )

        from desktop.jobs import JobManager

        manager = JobManager()
        manager._restored = True
        manager.workbook_path = str(source)
        manager.rows = list(manager_rows)
        manager.products = [{"meta": dict(manager_rows[0]), "product": {"row": 1, "product_id": "P-1"}}]
        manager._save_session()

        saved = job_session.load_session()
        self.assertEqual(saved["rows"][0]["flow_stage"], "created")
        self.assertEqual(saved["rows"][0]["material_folder"], "checkpoint")
        self.assertEqual(saved["products"][0]["meta"]["flow_stage"], "created")

    def test_manager_save_and_checkpoint_can_cross_without_lock_inversion(self):
        source = self.root / "清单.xlsx"
        source.write_bytes(b"placeholder")
        rows = [{"row": 1, "product_id": "P-1", "validation": "通过"}]
        job_session.remember_workbook(str(source), rows)

        from desktop.jobs import JobManager

        manager = JobManager()
        manager._restored = True
        manager.workbook_path = str(source)
        manager.rows = list(rows)
        manager.products = [{"meta": dict(rows[0]), "product": {"row": 1, "product_id": "P-1"}}]

        def save():
            manager._save_session()

        def checkpoint():
            job_session.patch_flow_state(1, "P-1", {"flow_stage": "created"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(save), pool.submit(checkpoint)]
            for future in futures:
                future.result(timeout=3)
        self.assertEqual(job_session.load_session()["rows"][0]["flow_stage"], "created")


class JobManagerConcurrencyTests(unittest.TestCase):
    def test_worker_events_extend_snapshot_and_global_blocker_marks_batch(self):
        from desktop.jobs import JobManager

        manager = JobManager()
        manager._restored = True
        manager.status = "running"
        manager.concurrency = 2
        manager._on_worker_event(
            {
                "event": "start",
                "worker_id": 1,
                "row": 2,
                "product_id": "P-2",
                "status": "running",
                "phase": "填写属性",
                "output_dir": "worker-1",
            }
        )
        snapshot = manager.snapshot()
        self.assertEqual(len(snapshot["active_workers"]), 1)
        self.assertEqual(snapshot["active_workers"][0]["worker_id"], "1")
        self.assertEqual(snapshot["current_row"], 2)
        self.assertEqual(snapshot["concurrency"], 2)

        manager._on_worker_event(
            {
                "event": "global_blocker",
                "worker_id": 1,
                "row": 2,
                "product_id": "P-2",
                "status": "paused",
                "phase": "登录失效",
                "blocker": "账号级登录失效",
                "output_dir": "worker-1",
            }
        )
        snapshot = manager.snapshot()
        self.assertEqual(snapshot["global_blocker"], "账号级登录失效")
        self.assertFalse(manager.cancel.is_set())
        self.assertEqual(snapshot["status"], "stopping")

    def test_done_event_after_global_blocker_keeps_blocker_and_pause_phase(self):
        from desktop.jobs import JobManager

        manager = JobManager()
        manager._restored = True
        manager.status = "running"
        manager._on_worker_event({
            "event": "global_blocker", "worker_id": 1, "row": 1,
            "product_id": "P-1", "status": "paused", "phase": "需处理全局故障",
            "message": "账号级登录失效", "output_dir": "worker-1",
        })
        manager._on_worker_event({
            "event": "done", "worker_id": 1, "row": 1,
            "product_id": "P-1", "status": "paused", "phase": "已处理",
            "item": {"execution": "暂停", "notice": "单条页面验证"},
            "output_dir": "worker-1",
        })
        self.assertEqual(manager.global_blocker, "账号级登录失效")
        self.assertEqual(manager.blocker, "账号级登录失效")
        self.assertEqual(manager.phase, "需人工处理")
        self.assertEqual(manager.status, "stopping")
        self.assertFalse(manager.cancel.is_set())

    def test_progress_prefers_steps_and_cannot_clear_global_phase(self):
        from desktop.jobs import JobManager

        manager = JobManager()
        manager._restored = True
        manager.status = "running"
        manager._on_worker_event({
            "event": "start", "worker_id": 1, "row": 1,
            "product_id": "P-1", "phase": "开始填写", "status": "running",
            "output_dir": "worker-1",
        })
        manager._on_worker_event({
            "event": "progress", "worker_id": 1, "row": 1,
            "product_id": "P-1", "phase": "main_images", "status": "running",
            "steps": [{"step": "probe_state"}], "output_dir": "worker-1",
        })
        active = manager.snapshot()["active_workers"][0]
        self.assertEqual(active["phase"], "检查已填内容")
        self.assertEqual(manager.phase, "检查已填内容")

        manager._on_worker_event({
            "event": "global_blocker", "worker_id": 1, "row": 1,
            "product_id": "P-1", "status": "paused", "phase": "需处理全局故障",
            "message": "账号级登录失效", "output_dir": "worker-1",
        })
        manager._on_worker_event({
            "event": "progress", "worker_id": 1, "row": 1,
            "product_id": "P-1", "phase": "main_images", "status": "running",
            "steps": [{"step": "main_images"}], "output_dir": "worker-1",
        })
        snapshot = manager.snapshot()
        self.assertEqual(snapshot["phase"], "需人工处理")
        self.assertEqual(snapshot["blocker"], "账号级登录失效")
        self.assertEqual(snapshot["active_workers"][0]["phase"], "主图")

    def test_attention_count_includes_uncertain_and_user_stopped_items(self):
        from desktop.jobs import JobManager

        manager = JobManager()
        manager._restored = True
        manager.status = "running"
        for row, execution in ((1, "结果待核实"), (2, "已停止")):
            manager._on_worker_event({
                "event": "done", "worker_id": row, "row": row,
                "product_id": f"P-{row}", "status": "paused", "phase": "已处理",
                "item": {"execution": execution}, "output_dir": f"worker-{row}",
            })
        self.assertEqual(manager.snapshot()["attention_count"], 2)

    def test_worker_log_has_runtime_context_in_entry_and_file_prefix(self):
        from web_fill.runtime import worker_runtime
        from desktop.jobs import JobManager

        manager = JobManager()
        runtime = SimpleNamespace(worker_id=2, row=7, product_id="P-7")
        with tempfile.TemporaryDirectory() as temp:
            log_dir = Path(temp)
            with patch("desktop.jobs.paths.logs_dir", return_value=log_dir):
                with worker_runtime(runtime):
                    manager.log("填写属性")
            entry = manager.logs[-1]
            self.assertEqual(entry["worker_id"], "2")
            self.assertEqual(entry["row"], 7)
            self.assertEqual(entry["product_id"], "P-7")
            line = (log_dir / "desktop.log").read_text(encoding="utf-8")
            self.assertIn("[worker_id=2 row=7 product_id=P-7] 填写属性", line)

    def test_start_captures_settings_for_next_batch_only(self):
        from desktop.jobs import JobManager

        manager = JobManager()
        manager._restored = True
        manager.workbook_path = str(Path("清单.xlsx"))
        manager._pending_products = lambda **kwargs: [
            {"row": 1, "product_id": "P-1", "validation": "通过"}
        ]
        manager._hide_chrome_for_fill = MagicMock()
        manager._run_job = MagicMock()
        settings = SimpleNamespace(concurrency=5)

        with patch("desktop.jobs.paths.load_settings", return_value=settings):
            manager.start_job()
            manager.thread.join(timeout=3)

        self.assertEqual(manager.concurrency, 5)
        settings.concurrency = 1
        self.assertEqual(manager.batch_settings.concurrency, 5)
        self.assertEqual(manager.snapshot()["concurrency"], 5)

    def test_running_batch_uses_image_strategy_snapshot_for_pending_count(self):
        from desktop.jobs import JobManager

        manager = JobManager()
        manager._restored = True
        manager.status = "running"
        manager.batch_settings = SimpleNamespace(sku_image_strategy="slim_material")
        manager.rows = [{
            "row": 1,
            "product_id": "P-1",
            "validation": "通过",
            "execution": "已入库",
            "flow_stage": "complete",
            "sku_image_strategy": "slim_material",
        }]

        # A setting saved while this batch is running applies to the next
        # start/continue action, not to this batch's progress projection.
        with patch("desktop.jobs.paths.load_settings", return_value=SimpleNamespace(sku_image_strategy="publish_page")):
            self.assertEqual(manager.snapshot()["pending"], 0)

        # Once paused, the next continue action is allowed to use the saved
        # strategy and therefore sees this row as needing the publish-page
        # image target.
        manager.status = "paused"
        with patch("desktop.jobs.paths.load_settings", return_value=SimpleNamespace(sku_image_strategy="publish_page")):
            self.assertEqual(manager.snapshot()["pending"], 1)

    def test_watchdog_tracks_worker_progress_and_marks_only_stale_slot(self):
        from desktop.jobs import JobManager

        manager = JobManager()
        manager._restored = True
        manager.status = "running"
        manager.concurrency = 2
        manager._on_worker_event(
            {
                "event": "start", "worker_id": 1, "row": 1,
                "product_id": "P-1", "status": "running",
                "phase": "开始填写", "output_dir": "worker-1",
            }
        )
        manager._on_worker_event(
            {
                "event": "start", "worker_id": 2, "row": 2,
                "product_id": "P-2", "status": "running",
                "phase": "开始填写", "output_dir": "worker-2",
            }
        )
        manager._on_worker_event(
            {
                "event": "progress", "worker_id": 2, "row": 2,
                "product_id": "P-2", "status": "running",
                "steps": [{"step": "attributes"}], "output_dir": "worker-2",
            }
        )
        manager.active_worker_events[1]["activity_at"] = time.time() - 61
        manager._reveal_chrome_for_attention = MagicMock()
        with patch("desktop.jobs.stall_seconds", return_value=60), \
             patch("desktop.jobs.paths.load_settings", return_value=SimpleNamespace(debug_browser=False)):
            manager._check_stalled()

        active = {item["worker_id"]: item for item in manager.snapshot()["active_workers"]}
        self.assertTrue(active["1"]["stalled"])
        self.assertFalse(active["2"]["stalled"])
        self.assertEqual(active["2"]["phase"], "填写属性")

    def test_chrome_status_and_debug_toggle_keep_batch_runtime_frozen(self):
        from desktop.jobs import JobManager

        manager = JobManager()
        manager._restored = True
        manager.status = "running"
        manager.batch_settings = SimpleNamespace(
            chrome_path="batch-chrome", chrome_profile="batch-profile",
            cdp_port=9333, debug_browser=False,
        )
        new_settings = SimpleNamespace(
            chrome_path="new-chrome", chrome_profile="new-profile",
            cdp_port=9444, debug_browser=True,
        )
        web = MagicMock()
        web.cdp_available.return_value = False
        with patch("desktop.jobs.paths.load_settings", return_value=new_settings), \
             patch("desktop.jobs.paths.browser_exe_path", return_value=None), \
             patch("desktop.jobs.paths.browser_source", return_value="batch"), \
             patch("desktop.jobs.load_web", return_value=web):
            status = manager.chrome_status()
            self.assertFalse(manager.apply_debug_browser(True))

            web.reload_paths.assert_not_called()
            self.assertEqual(status["profile"], "batch-profile")
            self.assertEqual(status["cdp_port"], 9333)
            self.assertTrue(status["debug_browser"], "显示开关应读取当前保存偏好，路径和端口仍保持批次快照")

    def test_done_attention_keeps_batch_browser_context(self):
        from desktop.jobs import JobManager

        manager = JobManager()
        manager._restored = True
        manager.status = "done"
        manager.batch_settings = SimpleNamespace(
            chrome_path="batch-chrome", chrome_profile="batch-profile", cdp_port=9333,
        )
        manager.rows = [{"execution": "结果待核实"}]
        new_settings = SimpleNamespace(
            chrome_path="new-chrome", chrome_profile="new-profile", cdp_port=9444,
            debug_browser=False,
        )
        web = MagicMock()
        web.cdp_available.return_value = False
        with patch("desktop.jobs.paths.load_settings", return_value=new_settings), \
             patch("desktop.jobs.paths.browser_exe_path", return_value=None), \
             patch("desktop.jobs.paths.browser_source", return_value="batch"), \
             patch("desktop.jobs.load_web", return_value=web):
            status = manager.chrome_status()

        web.reload_paths.assert_not_called()
        self.assertEqual(status["profile"], "batch-profile")
        self.assertEqual(status["cdp_port"], 9333)

    def test_done_cleanup_only_adjusts_visibility_without_global_prune(self):
        from desktop.jobs import JobManager

        manager = JobManager()
        manager.status = "done"
        manager.rows = [{"execution": "已入库"}]
        web = MagicMock()
        manager._hide_chrome_for_fill = MagicMock()
        with patch("desktop.jobs.load_web", return_value=web):
            manager._finish_browser()
        web.prune_automation_tabs.assert_not_called()
        manager._hide_chrome_for_fill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
