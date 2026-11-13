import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from web_fill import pipeline
from web_fill.runtime import CheckpointError, WorkerRuntime, worker_runtime


class WorkerCheckpointTests(unittest.TestCase):
    def runtime(self, directory):
        return WorkerRuntime(1, 2, "test-product", "key", Path(directory),
                             pipeline.get_scripts(), Path(directory) / "logs")

    def test_upload_intent_is_on_disk_before_browser_command(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.runtime(directory)
            session = Mock(cancel_event=None)

            def command(*args, **kwargs):
                saved = json.loads((Path(directory) / "item_checkpoint.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["item"]["last_browser_write"]["script"], "upload_files.js")
                raise RuntimeError("test stops at browser boundary")

            session.cmd.side_effect = command
            with worker_runtime(runtime), self.assertRaisesRegex(RuntimeError, "browser boundary"):
                pipeline.run_script(session, "upload_files.js", {"files": ["test.png"]})
            session.cmd.assert_called_once()

    def test_failed_checkpoint_prevents_upload_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.runtime(directory)
            session = Mock(cancel_event=None)
            with worker_runtime(runtime), patch.object(runtime, "save_checkpoint", side_effect=CheckpointError("disk full")), \
                    patch.object(pipeline, "render_script") as render:
                with self.assertRaisesRegex(CheckpointError, "disk full"):
                    pipeline.run_script(session, "main_images.js", {"phase": "open", "files": ["test.png"]})
            session.cmd.assert_not_called()
            render.assert_not_called()

    def test_publish_page_checkpoint_is_durable_and_not_overwritten_by_old_item_state(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.runtime(directory)
            payload = pipeline.product_to_payload({'title': 'test'})
            checkpoint = {'key': pipeline.resume_key(payload), 'completed': ['category'],
                          'href': 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=123',
                          'submit_started': False}
            with worker_runtime(runtime), patch.object(pipeline, 'run_script', return_value=checkpoint), \
                 patch('job_session.patch_flow_state') as persist:
                pipeline._save_checkpoint(Mock(), payload, {'category'})
                persist.assert_called_once_with(2, 'test-product', {'resume_checkpoint': checkpoint})
                item = {'resume_checkpoint': {'key': 'stale'}}
                pipeline._sync_worker_resume(item)
                self.assertEqual(item['resume_checkpoint'], checkpoint)
            saved = json.loads((Path(directory) / 'item_checkpoint.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['item']['resume_checkpoint'], checkpoint)

    def test_pending_submit_marker_cannot_be_reset_by_later_page_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.runtime(directory)
            runtime.pending_creation = True
            with worker_runtime(runtime), patch.object(pipeline, 'run_script', return_value={}) as run:
                pipeline._save_checkpoint(Mock(), {'title': 'test'}, {'attributes'})
            self.assertTrue(run.call_args.args[2]['submit_started'])

    def test_confirmed_validation_rejection_allows_continue_but_unknown_submit_does_not(self):
        for rejected in (True, False):
            with self.subTest(rejected=rejected), tempfile.TemporaryDirectory() as directory:
                runtime = self.runtime(directory)
                runtime.pending_creation = True
                runtime.latest_item = {'resume_checkpoint': {'submit_started': True},
                                       'flow_stage': 'submit_pending'}
                session = Mock()
                session.href.return_value = 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=123'
                web = Mock()
                web.warehouse_selected.return_value = True
                web.is_publish_page.return_value = True
                with worker_runtime(runtime), patch.object(pipeline, '_prepare_submit', return_value=(True, '')), \
                     patch.object(pipeline, '_audit_spec_rows_before_submit'), \
                     patch.object(pipeline, 'run_script', return_value={'hasFail': rejected, 'hasSuccess': False,
                                                                      'notice': '必填项未填' if rejected else ''}), \
                     patch('job_session.patch_flow_state'):
                    pipeline._finish_publish(session, {}, True, web, [])
                self.assertEqual(runtime.pending_creation, not rejected)
                self.assertEqual(runtime.latest_item['resume_checkpoint']['submit_started'], not rejected)


if __name__ == "__main__":
    unittest.main()
