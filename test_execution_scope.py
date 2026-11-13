"""入库选择范围、素材身份和默认/显式上限的业务契约回归。"""
import copy
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


class ExecutionScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.temp.name)
        self.stack.enter_context(mock.patch.dict(os.environ, {"QIANNIU_APPDATA": str(self.root / "appdata")}))
        from desktop import jobs, paths, server
        self.jobs, self.paths, self.server = jobs, paths, server
        self.settings = paths.Settings(limit=5, concurrency=2, results_dir=str(self.root / "results"))
        self.stack.enter_context(mock.patch.object(paths, "load_settings", return_value=self.settings))
        self.stack.enter_context(mock.patch.object(server.license_module, "is_activated", return_value=True))
        self.stack.enter_context(mock.patch.object(server.license_module, "require_activated", return_value=None))
        self.stack.enter_context(mock.patch.object(jobs.code_watch, "stale_code_files", return_value=[]))
        self.manager = jobs.JobManager()
        self.manager._restored = True
        self.manager.workbook_path = str(self.root / "清单.xlsx")
        self.manager.rows = [{
            "row": i, "product_id": f"P-{i}", "validation": "通过", "execution": "未执行",
            "flow_stage": "pending", "pack_fingerprint": f"asset-{i}", "errors": [],
        } for i in range(2, 7)]
        self.manager.products = [{"meta": copy.deepcopy(row), "product": {
            "row": row["row"], "product_id": row["product_id"], "title": row["product_id"],
        }} for row in self.manager.rows]

    def test_api_default_and_explicit_limit_have_distinct_meanings(self):
        from fastapi.testclient import TestClient
        client = TestClient(self.server.app)
        for body, expected in [({}, 5), ({"limit": None}, 5), ({"limit": 0}, 0), ({"limit": 2}, 2)]:
            with self.subTest(body=body), mock.patch.object(self.server.MANAGER, "start_job", return_value={"status": "running"}) as start:
                response = client.post("/api/job/start", json=body)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(start.call_args.kwargs["limit"], expected)
        self.settings.limit = 2
        with mock.patch.object(self.server.MANAGER, "start_job", return_value={"status": "running"}) as start:
            client.post("/api/job/start", json={"limit": None})
            self.assertEqual(start.call_args.kwargs["limit"], 2)

    def test_api_rejects_invalid_scope_and_limit_without_starting(self):
        from fastapi.testclient import TestClient
        client = TestClient(self.server.app)
        invalid = [{"limit": value} for value in [-1, True, 1.5, "2"]] + [
            {"selected_rows": []}, {"selected_rows": [{"row": True, "product_id": "P-2"}]},
            {"selected_rows": [{"row": 2, "product_id": ""}]},
        ]
        with mock.patch.object(self.server.MANAGER, "start_job") as start:
            for body in invalid:
                with self.subTest(body=body):
                    self.assertEqual(client.post("/api/job/start", json=body).status_code, 422)
            start.assert_not_called()

    def test_api_preserves_selected_identity_and_source(self):
        from fastapi.testclient import TestClient
        selected = [{"row": 4, "product_id": "P-4", "pack_fingerprint": "asset-4"}]
        with mock.patch.object(self.server.MANAGER, "start_job", return_value={"status": "running"}) as start:
            response = TestClient(self.server.app).post("/api/job/start", json={"limit": 0, "selected_rows": selected, "workbook_path": self.manager.workbook_path})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(start.call_args.kwargs["selected_rows"], selected)
        self.assertEqual(start.call_args.kwargs["workbook_path"], self.manager.workbook_path)

    def test_pending_selection_skips_completed_and_retains_existing_item_id(self):
        self.manager.rows[0].update(flow_stage="complete", sku_image_strategy="slim_material", taobao_item_id="100002", execution="已入库")
        self.manager.rows[2].update(flow_stage="created", taobao_item_id="100004", execution="失败")
        # 兼容历史会话中商品编号仅在 product 中的 bundle。
        self.manager.products[2]["meta"].pop("product_id")
        result = self.manager._pending_products(selected_rows=[{"row": 2, "product_id": "P-2"}, {"row": 4, "product_id": "P-4"}])
        self.assertEqual([row["product_id"] for row in result], ["P-4"])
        self.assertEqual(result[0]["taobao_item_id"], "100004")

    def test_changed_source_identity_fingerprint_or_empty_scope_never_starts(self):
        invalid = [[], [{"row": 4, "product_id": "P-3"}], [{"row": 4, "product_id": "P-4"}] * 2,
                   [{"row": 4, "product_id": "P-4", "pack_fingerprint": "old-assets"}]]
        with mock.patch.object(self.manager, "_hide_chrome_for_fill") as hide, mock.patch.object(self.jobs.threading, "Thread") as thread:
            for selected in invalid:
                with self.subTest(selected=selected), self.assertRaises(RuntimeError):
                    self.manager.start_job(selected_rows=selected)
            with self.assertRaisesRegex(RuntimeError, "清单已变化"):
                self.manager.start_job(workbook_path=str(self.root / "另一份清单.xlsx"))
            hide.assert_not_called()
            thread.assert_not_called()
        self.assertEqual(self.manager.status, "idle")

    def test_start_freezes_selection_before_launching_worker(self):
        selected = [{"row": 4, "product_id": "P-4"}, {"row": 6, "product_id": "P-6"}]
        with mock.patch.object(self.manager, "_hide_chrome_for_fill"), mock.patch.object(self.jobs.threading, "Thread") as thread:
            snap = self.manager.start_job(limit=1, selected_rows=selected, workbook_path=self.manager.workbook_path)
            selected[0]["product_id"] = "changed-after-request"
            self.assertEqual(snap["total"], 1)
            self.assertEqual(thread.call_args.kwargs["kwargs"]["selected_rows"][0]["product_id"], "P-4")

    def test_actual_dispatch_applies_selection_before_cap_for_serial_and_concurrent(self):
        for concurrency, limit, expected in [(1, 1, [4]), (2, 0, [4, 6])]:
            with self.subTest(concurrency=concurrency):
                self.manager.concurrency = concurrency
                self.manager.batch_settings = copy.deepcopy(self.settings)
                self.manager.started_at = 1
                web, seller = mock.MagicMock(), mock.MagicMock()
                seller.load_web_fill.return_value = web
                web.run_batch.return_value = []
                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(self.jobs, "load_seller", return_value=seller))
                    for name in ["configure_environ", "apply_to_loaded_modules"]:
                        stack.enter_context(mock.patch.object(self.paths, name))
                    for name in ["_apply_chrome_pref_for_fill", "_finish_browser", "_watch_progress", "_save_session"]:
                        stack.enter_context(mock.patch.object(self.manager, name))
                    self.manager._run_job(limit=limit, selected_rows=[{"row": 4, "product_id": "P-4"}, {"row": 6, "product_id": "P-6"}])
                self.assertEqual([row["row"] for row in web.run_batch.call_args.args[0]], expected)
                self.assertEqual(web.run_batch.call_args.kwargs["concurrency"], concurrency)


if __name__ == "__main__":
    unittest.main()
