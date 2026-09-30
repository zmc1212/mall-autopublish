"""Offline regression tests: never connect to Taobao or upload files."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_upload_slider as subject


class UploadSliderSafetyTests(unittest.TestCase):
    def run_case(self, *, risk=None, before=None, outcomes=None, href=None):
        web, pipeline = Mock(), Mock()
        web.CliSession.return_value.href.return_value = href or 'https://item.upload.taobao.com/sell/publish.htm'
        pipeline.product_to_payload.return_value = {}
        pipeline.ensure_fill_tab.return_value = ('https://item.upload.taobao.com/sell/publish.htm', 'reuse-publish')
        pipeline.run_script.side_effect = [risk or {}, before or {}]
        pipeline._image_step.side_effect = outcomes or [{'bind': {'verified': True}}, {'bind': {'verified': True}}]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(subject, 'ROOT', Path(directory)), \
                patch.object(subject, '_load_web', return_value=web), \
                patch.object(subject, '_load_pipeline', return_value=pipeline), \
                contextlib.redirect_stdout(io.StringIO()):
            status = subject.main(['--live'])
            report = json.loads((Path(directory) / 'output/playwright/upload_slider_test.json').read_text(encoding='utf-8'))
        return status, report, pipeline

    def test_no_live_flag_never_attaches(self):
        with patch.object(subject, '_load_web') as load, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(subject.main([]), 2)
        load.assert_not_called()

    def test_existing_challenge_prevents_all_uploads(self):
        for risk in ({'securityChallenge': '滑块验证'}, {'status': {'securityLimit': True}}):
            with self.subTest(risk=risk):
                code, report, pipeline = self.run_case(risk=risk)
                self.assertEqual(code, 1)
                self.assertTrue(report['detail_images']['skipped'])
                pipeline._image_step.assert_not_called()
                pipeline.ensure_fill_tab.assert_not_called()

    def test_main_failure_never_continues_to_details(self):
        for message in ('PAUSE:操作过于频繁，请滑动验证码', '上传结果未确认'):
            with self.subTest(message=message):
                code, report, pipeline = self.run_case(outcomes=[RuntimeError(message)])
                self.assertEqual(code, 1)
                self.assertEqual(pipeline._image_step.call_count, 1)
                self.assertIn('skipped', report['detail_images'])

    def test_details_failure_does_not_report_success(self):
        code, report, pipeline = self.run_case(outcomes=[{'bind': {'verified': True}}, RuntimeError('PAUSE:请滑动验证码')])
        self.assertEqual(code, 1)
        self.assertEqual(pipeline._image_step.call_count, 2)
        self.assertIn('error', report['detail_images'])

    def test_populated_draft_and_existing_item_are_preserved(self):
        for before in ({'title': 'Existing draft'}, {'mainImgs': 1}, {'detailImgs': 1}):
            code, _, pipeline = self.run_case(before=before)
            self.assertEqual(code, 1)
            pipeline._image_step.assert_not_called()
        code, _, pipeline = self.run_case(href='https://item.upload.taobao.com/sell/publish.htm?itemId=123456789')
        self.assertEqual(code, 1)
        pipeline._image_step.assert_not_called()

    def test_only_verified_main_and_details_report_success(self):
        code, report, pipeline = self.run_case()
        self.assertEqual(code, 0)
        self.assertEqual(pipeline._image_step.call_count, 2)
        self.assertTrue(report['main_images']['bind']['verified'])
        self.assertTrue(report['detail_images']['bind']['verified'])


if __name__ == '__main__':
    unittest.main()
