"""Concurrency invariants without making writes to the seller account."""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from web_fill import pipeline
from web_fill import concurrent_batch as workers
from web_fill.runtime import CheckpointError, current_runtime


class Session:
    def __init__(self, worker_id):
        self.worker_id = worker_id
        self.items = []
        self.begin_args = []
        self.begin_options = []
        self.existing_keys = set()
        self.preserved = []

    def begin_item(self, key, resume_checkpoint=None, allow_create=True):
        if not allow_create and key not in self.existing_keys:
            raise RuntimeError("商品没有已登记页面，已拒绝新建页面")
        self.items.append(key)
        self.begin_args.append((key, resume_checkpoint))
        self.begin_options.append((key, resume_checkpoint, allow_create))

    def finish_item(self, preserve=False):
        self.preserved.append(preserve)

    def detach(self):
        pass

    def attach(self):
        return self.href()

    def href(self):
        return "https://item.upload.taobao.com/sell/ai/category.htm"

    def snapshot(self):
        return ""

    def seller_account(self):
        return "test-shop"


class ConcurrentPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.web = SimpleNamespace(
            start_persistent_chrome=lambda **kw: None,
            cdp_available=lambda: True,
            assert_logged_in=lambda *args: None,
            SessionLost=type("SessionLost", (RuntimeError,), {}),
        )
        self.sessions = []
        self.session_lock = threading.Lock()

        def factory(web, worker_id, *args):
            session = Session(worker_id)
            session.existing_keys.update(self.session_existing_keys)
            with self.session_lock:
                self.sessions.append(session)
            return session

        for mocked in (
            patch.dict(os.environ, {"QIANNIU_OUTPUT_DIR": self.tmp.name, "QIANNIU_APPDATA": self.tmp.name}),
            patch.object(pipeline, "_load_web", return_value=self.web),
            patch.object(workers, "_make_session", side_effect=factory),
            patch.object(pipeline, "_remember_item"),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)
        self.session_existing_keys = set()

    def products(self, count):
        return [{"row": i + 1, "product_id": f"item-{i + 1}", "title": f"Title {i + 1}"}
                for i in range(count)]

    def run_pool(self, products, **kw):
        return pipeline.run_batch(products, runtime_settings={}, **kw)

    def test_real_overlap_output_isolation_and_input_order(self):
        barrier = threading.Barrier(2, timeout=4)
        lock = threading.Lock()
        active = maximum = 0
        completed = []
        seen_paths = []

        def run(products, **kw):
            nonlocal active, maximum
            product = products[0]
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                output = pipeline.get_output()
                pipeline._write_progress([{"step": product["product_id"]}])
                with lock:
                    seen_paths.append(output)
                if product["row"] <= 2:
                    barrier.wait()
                if product["row"] == 1:
                    time.sleep(0.08)
                data = json.loads((output / "web_fill_progress.json").read_text(encoding="utf-8"))
                self.assertEqual(data[0]["step"], product["product_id"])
                kw["on_item_start"](product)
                return [{**product, "execution": "已入库", "run_status": "completed"}]
            finally:
                with lock:
                    active -= 1

        with patch.object(pipeline, "_run_batch_serial", side_effect=run):
            result = self.run_pool(self.products(5), concurrency=2,
                                   on_item_done=lambda p, i: completed.append(p["row"]))
        self.assertEqual(maximum, 2)
        self.assertEqual([item["row"] for item in result], [1, 2, 3, 4, 5])
        self.assertEqual(sorted(completed), [1, 2, 3, 4, 5])
        self.assertNotEqual(completed[0], 1)
        self.assertEqual(len(set(seen_paths)), 5)
        self.assertIsNone(current_runtime())

    def test_limit_applies_to_batch_and_single_slot_stays_serial(self):
        visited = []

        def run(products, **kw):
            visited.append(products[0]["row"])
            return [{**products[0], "execution": "已入库", "run_status": "completed"}]

        with patch.object(pipeline, "_run_batch_serial", side_effect=run):
            result = self.run_pool(self.products(6), concurrency=1, limit=3)
        self.assertEqual(visited, [1, 2, 3])
        self.assertEqual(len(result), 3)
        self.assertEqual(len(self.sessions), 1)

    def test_cancel_does_not_claim_queued_items(self):
        barrier = threading.Barrier(2, timeout=4)
        cancel = threading.Event()
        visited = []

        def run(products, **kw):
            visited.append(products[0]["row"])
            barrier.wait()
            cancel.set()
            return [{**products[0], "execution": "已停止", "run_status": "stopped"}]

        with patch.object(pipeline, "_run_batch_serial", side_effect=run):
            result = self.run_pool(self.products(8), concurrency=2, cancel_event=cancel)
        self.assertEqual(sorted(visited), [1, 2])
        self.assertEqual(len(result), 2)
        self.assertTrue(all(all(s.preserved) for s in self.sessions))

    def test_slider_is_parked_and_next_item_runs_without_retry(self):
        calls = []

        def fill(session, product, **kw):
            calls.append(product["row"])
            if product["row"] == 1:
                return {"execution": "暂停", "notice": "PAUSE:滑块验证需人工处理"}
            return {"execution": "已填写未提交"}

        with patch.object(pipeline, "fill_new_product", side_effect=fill):
            result = self.run_pool(self.products(3), concurrency=1, item_retry_limit=3)
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual(result[0]["execution"], "暂停")
        self.assertEqual(len(result), 3)
        self.assertTrue(self.sessions[0].preserved[0])

    def test_normal_retry_belongs_to_one_item_and_settles_once(self):
        attempts, done, starts = {}, [], []

        def fill(session, product, **kw):
            row = product["row"]
            attempts[row] = attempts.get(row, 0) + 1
            if attempts[row] == 1:
                return {"execution": "失败", "notice": "网络超时"}
            return {"execution": "已填写未提交"}

        with patch.object(pipeline, "fill_new_product", side_effect=fill), \
                patch.object(pipeline, "_maybe_close_overlays"), patch.object(pipeline, "_dismiss_import_dialog"):
            result = self.run_pool(self.products(2), concurrency=2, item_retry_limit=1,
                                   on_item_done=lambda p, i: done.append(p["row"]),
                                   on_item_start=lambda p: starts.append(p["row"]))
        self.assertEqual(attempts, {1: 2, 2: 2})
        self.assertEqual(sorted(done), [1, 2])
        self.assertEqual(sorted(starts), [1, 2])
        self.assertEqual(len(result), 2)

    def test_uncertain_submit_checkpoint_prevents_retry(self):
        calls = []

        def fill(session, product, **kw):
            calls.append(product["row"])
            current_runtime().checkpoint()
            raise RuntimeError("提交连接超时")

        with patch.object(pipeline, "fill_new_product", side_effect=fill):
            result = self.run_pool(self.products(2), concurrency=2, confirm_submit=True, item_retry_limit=3)
        self.assertEqual(sorted(calls), [1, 2])
        self.assertTrue(all(item["flow_stage"] == "submit_pending" for item in result))
        self.assertTrue(all(item["execution"] == "提交待核实" for item in result))

    def test_checkpoint_failure_stops_dispatch(self):
        events = []

        def run(products, **kw):
            raise CheckpointError("PAUSE:断点保存失败")

        with patch.object(pipeline, "_run_batch_serial", side_effect=run):
            result = self.run_pool(self.products(4), concurrency=1, on_worker_event=events.append)
        self.assertEqual(len(result), 1)
        self.assertTrue(any(event["event"] == "global_blocker" for event in events))

    def test_login_loss_stops_queue_but_slider_classifier_is_local(self):
        self.assertEqual(workers.global_blocker("登录失效或需要人工处理: 滑块验证"), "")
        events = []
        with patch.object(pipeline, "_run_batch_serial", return_value=[{
            **self.products(1)[0], "execution": "暂停", "notice": "登录页，请重新登录", "run_status": "paused",
        }]):
            result = self.run_pool(self.products(4), concurrency=1, on_worker_event=events.append)
        self.assertEqual(len(result), 1)
        self.assertEqual(sum(e["event"] == "global_blocker" for e in events), 1)

    def test_duplicate_rows_and_invalid_concurrency_are_rejected(self):
        for value in (0, 9, True, 1.5, "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_pool(self.products(1), concurrency=value)
        with self.assertRaises(ValueError):
            self.run_pool([self.products(1)[0]] * 2, concurrency=2)

    def test_completion_write_failure_preserves_page_and_stops_queue(self):
        def fail_write(*args):
            raise OSError("disk unavailable")

        with patch.object(pipeline, "_run_batch_serial", return_value=[{
            **self.products(1)[0], "execution": "已入库", "run_status": "completed",
            "taobao_item_id": "12345678901",
        }]):
            result = self.run_pool(self.products(3), concurrency=1, confirm_submit=True,
                                   on_item_done=fail_write)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["execution"], "结果待核实")
        self.assertEqual(self.sessions[0].preserved, [True])

    def test_legacy_checkpoint_is_forwarded_only_with_explicit_publish_href(self):
        product = self.products(1)[0]
        product.update({
            "execution": "已填写未提交",
            "url": "https://item.upload.taobao.com/sell/v2/publish.htm?catId=123",
        })
        with patch.object(pipeline, "_run_batch_serial", return_value=[{
            **product, "execution": "已填写未提交", "run_status": "completed",
        }]):
            result = self.run_pool([product], concurrency=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(self.sessions), 1)
        key, checkpoint = self.sessions[0].begin_args[0]
        self.assertEqual(key, workers.item_key(product, ""))
        self.assertEqual(checkpoint["href"], product["url"])
        self.assertEqual(
            checkpoint["key"],
            pipeline.resume_key(pipeline.product_to_payload(product)),
        )
        self.assertEqual(checkpoint["item_key"], key)

    def test_legacy_uncertain_without_href_pauses_without_new_page_or_fill(self):
        old = self.products(1)[0]
        old.update({"execution": "提交待核实"})
        fresh = self.products(1)[0]
        fresh.update({"row": 2, "product_id": "item-2", "execution": "未执行"})
        filled = []

        def run(products, **kw):
            filled.append(products[0]["row"])
            return [{**products[0], "execution": "已填写未提交", "run_status": "completed"}]

        with patch.object(pipeline, "_run_batch_serial", side_effect=run):
            result = self.run_pool([old, fresh], concurrency=1)
        self.assertEqual(filled, [2])
        self.assertEqual([item["row"] for item in result], [1, 2])
        self.assertEqual(result[0]["execution"], "暂停")
        self.assertIn("禁止新建页面", result[0]["notice"])
        self.assertEqual(self.sessions[0].begin_args, [(workers.item_key(fresh, ""), None)])

    def test_registry_page_has_priority_over_missing_legacy_href(self):
        product = self.products(1)[0]
        product.update({"execution": "提交待核实"})
        key = workers.item_key(product, "")
        self.session_existing_keys.add(key)
        with patch.object(pipeline, "_run_batch_serial", return_value=[{
            **product, "execution": "已填写未提交", "run_status": "completed",
        }]):
            result = self.run_pool([product], concurrency=1)
        self.assertEqual(result[0]["run_status"], "completed")
        self.assertEqual(self.sessions[0].begin_options[0], (key, None, False))

    def write_old_attempt(self, product, checkpoint=None, *, submit=False, response=None):
        directory = Path(self.tmp.name) / 'batches' / 'old-run' / 'worker-1' / 'old-item'
        directory.mkdir(parents=True, exist_ok=True)
        item = {**product, 'last_browser_write': {'script': 'sku_import.js', 'phase': 'open'}}
        (directory / 'item_checkpoint.json').write_text(json.dumps({'item': item}), encoding='utf-8')
        if checkpoint is None:
            payload = pipeline.product_to_payload(product)
            for sku in payload['skus']:
                sku.pop('specs', None)
            checkpoint = {'key': pipeline.resume_key(payload), 'completed': ['attributes'],
                          'href': 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=123'}
        (directory / 'web_fill_checkpoint.json').write_text(json.dumps(checkpoint), encoding='utf-8')
        (directory / 'web_fill_sku_import.json').write_text(
            json.dumps(response if response is not None else {'uploaded': False, 'entry': '批量导入'}), encoding='utf-8')
        if submit:
            (directory / 'web_fill_submit.raw.txt').write_text('interrupted submit', encoding='utf-8')
        return directory

    def test_old_sku_import_pause_recovers_previous_batch_checkpoint(self):
        product = {**self.products(1)[0], 'execution': '暂停', 'notice': 'PAUSE:legacy_checkpoint',
                   'skus': [{'name': 'A', '规格': {'款式描述': 'A'}}]}
        self.write_old_attempt(product)
        with patch.object(pipeline, '_run_batch_serial', side_effect=lambda rows, **kw: [
                {**rows[0], 'execution': '已填写未提交', 'run_status': 'completed'}]):
            result = self.run_pool([product], concurrency=1)
        self.assertFalse(result[0]['resume_checkpoint']['submit_started'])
        self.assertIn('catId=123', self.sessions[0].begin_args[0][1]['href'])

    def test_legacy_blocker_records_do_not_hide_original_pre_submit_attempt(self):
        product = {**self.products(1)[0], 'execution': '暂停', 'notice': 'PAUSE:legacy_checkpoint',
                   'skus': [{'name': 'A', '规格': {'款式描述': 'A'}}]}
        self.write_old_attempt(product)
        # Exported LOGALOGA history: two newer batches only wrote the legacy
        # blocker. The earlier batch has the matching key and SKU-import receipt.
        for batch in ('blocked-one', 'blocked-two'):
            directory = Path(self.tmp.name) / 'batches' / batch / 'worker-1' / 'item'
            directory.mkdir(parents=True)
            (directory / 'item_checkpoint.json').write_text(json.dumps({'item': product}), encoding='utf-8')
        restored = workers._restore_previous_attempt(product, Path(self.tmp.name), pipeline)
        self.assertTrue(workers._can_restart_before_submit(restored))
        checkpoint, error = workers._legacy_resume_checkpoint(restored, pipeline)
        self.assertFalse(error)
        self.assertIn('catId=123', checkpoint['href'])

    def test_closed_pre_submit_page_restarts_but_pending_upload_does_not(self):
        for media_pending in (False, True):
            with self.subTest(media_pending=media_pending):
                product = {**self.products(1)[0], 'execution': '已停止'}
                checkpoint = {'key': pipeline.resume_key(pipeline.product_to_payload(product)),
                              'href': 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=123',
                              'submit_started': False}
                if media_pending:
                    checkpoint['media_pending'] = {'script': 'details.js'}
                product['resume_checkpoint'] = checkpoint
                def begin(session, key, resume_checkpoint=None, allow_create=True):
                    if resume_checkpoint:
                        raise RuntimeError('legacy checkpoint 页面未能唯一匹配，已拒绝新建页面')
                    session.begin_args.append((key, None))
                with patch.object(Session, 'begin_item', new=begin), \
                     patch.object(pipeline, '_run_batch_serial', return_value=[{
                         **product, 'execution': '已填写未提交', 'run_status': 'completed'}]) as fill:
                    result = self.run_pool([product], concurrency=1)
                self.assertEqual(fill.call_count, 0 if media_pending else 1)
                self.assertEqual(result[0]['execution'], '暂停' if media_pending else '已填写未提交')

    def test_old_submit_or_uncertain_media_never_migrates_as_safe_restart(self):
        product = {**self.products(1)[0], 'execution': '暂停'}
        directory = self.write_old_attempt(product, response={'dispatchUncertain': True})
        restored = workers._restore_previous_attempt(product, Path(self.tmp.name), pipeline)
        self.assertFalse(workers._can_restart_before_submit(restored))
        self.write_old_attempt(product, submit=True)
        restored = workers._restore_previous_attempt(product, Path(self.tmp.name), pipeline)
        self.assertEqual(restored['flow_stage'], 'submit_pending')
        self.assertFalse(workers._can_restart_before_submit(restored))

    def test_changed_product_and_execution_reset_do_not_adopt_old_attempt(self):
        product = {**self.products(1)[0], 'execution': '暂停'}
        self.write_old_attempt(product)
        for changed in ({**product, 'title': 'another title'}, {**product, 'execution_reset_id': 'new-run'}):
            restored = workers._restore_previous_attempt(changed, Path(self.tmp.name), pipeline)
            self.assertNotIn('resume_checkpoint', restored)

    def test_failed_before_category_with_durable_proof_can_start_again(self):
        product = {**self.products(1)[0], 'execution': '失败',
                   'resume_checkpoint': {'submit_started': False}}
        with patch.object(pipeline, '_run_batch_serial', return_value=[{
                **product, 'execution': '已填写未提交', 'run_status': 'completed'}]) as fill:
            result = self.run_pool([product], concurrency=1)
        fill.assert_called_once()
        self.assertIsNone(self.sessions[0].begin_args[0][1])
        self.assertEqual(result[0]['execution'], '已填写未提交')

    def test_login_pause_code_is_global_and_page_close_only_stops_when_cdp_is_gone(self):
        self.assertTrue(workers.global_blocker("PAUSE:login:需要重新登录"))
        self.assertTrue(workers.global_blocker("PAUSE：login 需要重新登录"))
        self.web.cdp_available = lambda: False
        events = []
        with patch.object(pipeline, "_run_batch_serial", side_effect=RuntimeError(
            "Target page, context or browser has been closed"
        )):
            result = self.run_pool(self.products(2), concurrency=1, on_worker_event=events.append)
        self.assertEqual(len(result), 1)
        self.assertTrue(any(event["event"] == "global_blocker" for event in events))

    def test_cli_attach_websocket_failure_is_global_but_page_timeout_is_local(self):
        timeout = "Timeout 30000ms exceeded while retrieving websocket url from http://127.0.0.1:9222"
        econn = "ECONNRESET while retrieving websocket url from http://127.0.0.1:9222"
        page_timeout = "Timeout 30000ms exceeded while waiting for selector"
        self.assertTrue(workers.global_blocker(timeout))
        self.assertTrue(workers.global_blocker(econn))
        self.assertEqual(workers.global_blocker(page_timeout), "")

        events = []
        with patch.object(pipeline, "_run_batch_serial", side_effect=RuntimeError(timeout)):
            result = self.run_pool(self.products(2), concurrency=1, on_worker_event=events.append)
        self.assertEqual(len(result), 1)
        self.assertTrue(any(event["event"] == "global_blocker" for event in events))


if __name__ == "__main__":
    unittest.main()
