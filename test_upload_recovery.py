import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from test_web_fill import FakeSession
from web_fill import pipeline


class UploadRecoveryTests(unittest.TestCase):
    def test_timeout_covers_cooldown_and_slowest_recovery_rate(self):
        timeout = pipeline._paced_upload_timeout(21)
        self.assertGreaterEqual(timeout, 900 + 21 * (120 + 45))
        with patch.object(pipeline, 'run_script', return_value={'uploaded': True}) as run:
            pipeline._upload_one_by_one(FakeSession(), [f'{i}.jpg' for i in range(21)])
        self.assertEqual(run.call_args.kwargs['timeout'], timeout)

    def test_timeout_respects_custom_window_and_backoff_bounds(self):
        options = {'uploadPacingOptions': {'windowMs': 300000, 'backoffMaxMs': 3600000}}
        self.assertGreaterEqual(pipeline._paced_upload_timeout(3, options), 3600 + 3 * 300)
        bounded = {'uploadPacingOptions': {'backoffBaseMs': 900000, 'backoffMaxMs': 1000}}
        self.assertGreaterEqual(pipeline._paced_upload_timeout(1, bounded), 900 + 120 + 45)

    def test_timeout_invalid_options_use_finite_defaults(self):
        options = {'uploadPacingOptions': {'windowMs': float('inf'), 'backoffMaxMs': 'invalid'}}
        self.assertEqual(pipeline._paced_upload_timeout(2, options), pipeline._paced_upload_timeout(2))

    def test_security_evidence_is_saved_without_polluting_pause_message(self):
        diagnostic = {'phase': 'before-dispatch', 'names': ['a.jpg'],
                      'securityEvidence': [{'text': ['操作过于频繁']}]}
        output = ('### Error\nError: PAUSE:淘宝当前仍提示操作过于频繁；本次未提交图片\n'
                  'UPLOAD_SECURITY_DIAGNOSTIC:' + json.dumps(diagnostic, ensure_ascii=False))
        for raised in (False, True):
            with self.subTest(raised=raised), tempfile.TemporaryDirectory() as directory, \
                 patch.object(pipeline, 'get_output', return_value=Path(directory)):
                session = FakeSession()
                with patch.object(session, 'cmd', side_effect=RuntimeError(output) if raised else None,
                                  return_value=output):
                    with self.assertRaises(RuntimeError) as result:
                        pipeline.run_script(session, 'main_images.js', {})
                self.assertIn('PAUSE:', str(result.exception))
                self.assertNotIn('UPLOAD_SECURITY_DIAGNOSTIC', str(result.exception))
                saved = json.loads((Path(directory) / 'web_fill_upload_security.json').read_text(encoding='utf-8'))
                self.assertEqual(saved, {**diagnostic, 'script': 'main_images.js'})
                self.assertIn('UPLOAD_SECURITY_DIAGNOSTIC',
                              (Path(directory) / 'web_fill_main_images.raw.txt').read_text(encoding='utf-8'))

    def test_upload_result_with_stale_chooser_notice_keeps_submission_receipt(self):
        for receipt in ({'uploaded': True}, {'uploaded': False, 'dispatched': True},
                        {'uploaded': False, 'dispatchUncertain': True}):
            with self.subTest(receipt=receipt), tempfile.TemporaryDirectory() as directory:
                output = ('### Result\n' + json.dumps(receipt) + '\n### Ran Playwright code\n'
                          'code\n### Modal state\n- [File chooser]: can be handled by upload')
                session = FakeSession()
                with patch.object(pipeline, 'get_output', return_value=Path(directory)), \
                     patch.object(session, 'cmd', return_value=output), \
                     patch.object(pipeline, '_dismiss_filechooser') as dismiss:
                    result = pipeline.run_script(session, 'main_images.js', {})
                self.assertEqual(result, receipt)
                dismiss.assert_called_once_with(session)
                self.assertEqual(session.uploads, [])

    def test_dismiss_chooser_cancels_all_pending_notices_without_paths(self):
        session = FakeSession()
        with patch.object(session, 'cmd', side_effect=[
            '### Modal state\n- [File chooser]: can be handled by upload', 'cancelled'
        ]) as command:
            pipeline._dismiss_filechooser(session)
        self.assertEqual(command.call_count, 2)
        self.assertTrue(all(call.args == ('upload',) for call in command.call_args_list))
        self.assertEqual(session.uploads, [])

    def test_open_chooser_verifies_main_and_details_without_sending_files(self):
        for script in ('main_images.js', 'details.js'):
            with self.subTest(script=script):
                session = FakeSession()
                def run(session, name, payload, timeout=120):
                    if payload.get('phase') == 'open':
                        raise pipeline.FileChooserNeeded('File chooser')
                    if payload.get('phase') == 'after_upload':
                        return {'uploaded': True, 'verifiedBy': 'library-search'}
                    return {'selected': [{'name': 'a.jpg', 'pic': {'ok': True}}],
                            'slot': {'imgs': 1}, 'picked': [{'name': 'a.jpg', 'ok': True}],
                            'after': {'imgs': 1, 'dialog': False}, 'confirm': 'OK'}
                with patch.object(pipeline, 'run_script', side_effect=run), \
                     patch.object(pipeline, '_upload_one_by_one') as upload:
                    result = pipeline._image_step(session, script, {'names': ['a.jpg']}, ['a.jpg'])
                self.assertTrue(result['upload']['uploaded'])
                self.assertEqual(session.uploads, [])
                upload.assert_not_called()

    def test_batch_chooser_with_ambiguous_submission_pauses_without_resending(self):
        session = FakeSession()
        with patch.object(pipeline, 'run_script', side_effect=pipeline.FileChooserNeeded('File chooser')):
            with self.assertRaisesRegex(RuntimeError, 'PAUSE:.*停止重复提交'):
                pipeline._upload_one_by_one(session, ['a.jpg', 'b.jpg'])
        self.assertEqual(session.uploads, [])

    def test_dispatched_main_and_detail_images_are_verified_without_resubmission(self):
        for script in ('main_images.js', 'details.js'):
            with self.subTest(script=script):
                session = FakeSession()
                seen = []
                def run(session, name, payload, timeout=120):
                    seen.append(payload.get('phase'))
                    if payload.get('phase') == 'open':
                        return {'uploaded': False, 'need_cli_upload': True,
                                'uploadStatus': {'dispatched': True}, 'missing': ['a.jpg']}
                    if payload.get('phase') == 'after_upload':
                        return {'uploaded': True, 'verifiedBy': 'library-search'}
                    return {'selected': [{'name': 'a.jpg', 'pic': {'ok': True}}],
                            'slot': {'imgs': 1}, 'picked': [{'name': 'a.jpg', 'ok': True}],
                            'after': {'imgs': 1, 'dialog': False}, 'confirm': 'OK'}
                with patch.object(pipeline, 'run_script', side_effect=run), \
                     patch.object(pipeline, '_upload_one_by_one') as upload:
                    result = pipeline._image_step(session, script, {'names': ['a.jpg']}, ['a.jpg'])
                upload.assert_not_called()
                self.assertEqual(session.uploads, [])
                self.assertEqual(seen, ['open', 'after_upload', 'select'])
                self.assertTrue(result['upload']['uploaded'])

    def test_missing_main_and_detail_receipts_do_not_trigger_automatic_reupload(self):
        for script in ('main_images.js', 'details.js'):
            with self.subTest(script=script):
                unconfirmed = {'uploaded': False, 'missing': ['a.jpg']}
                with patch.object(pipeline, '_upload_one_by_one') as upload:
                    result, attempts = pipeline._retry_failed_image_uploads(
                        FakeSession(), script, {}, ['a.jpg'], {'dispatched': True}, unconfirmed)
                upload.assert_not_called()
                self.assertEqual(attempts, [])
                self.assertIs(result, unconfirmed)

    def test_verified_upload_does_not_retry_stale_failure_from_open(self):
        with patch.object(pipeline, '_upload_one_by_one') as upload:
            result, attempts = pipeline._retry_failed_image_uploads(
                FakeSession(), 'spec_images.js', {}, ['a.jpg'],
                {'failedNames': ['a.jpg'], 'retryable': True}, {'uploaded': True})
        upload.assert_not_called()
        self.assertTrue(result['uploaded'])
        self.assertEqual(attempts, [])

    def test_main_verification_chooser_is_dismissed_without_uploading_again(self):
        session = FakeSession()
        seen = []
        def run(session, script, payload, timeout=120):
            phase = payload.get('phase')
            seen.append(phase)
            if phase == 'open':
                return {'dispatched': True, 'uploaded': False}
            if seen.count('after_upload') == 1:
                raise pipeline.FileChooserNeeded('File chooser')
            return {'uploaded': False, 'missing': ['a.jpg']}
        with patch.object(pipeline, 'run_script', side_effect=run), \
             patch.object(pipeline, '_upload_one_by_one') as upload, \
             patch.object(pipeline, '_dismiss_filechooser') as dismiss:
            with self.assertRaisesRegex(RuntimeError, '已停止绑定'):
                pipeline._image_step(session, 'main_images.js', {}, ['a.jpg'])
        upload.assert_not_called()
        dismiss.assert_called_once()
        self.assertEqual(session.uploads, [])
        self.assertNotIn('select', seen)

    def test_large_spec_set_uses_individual_sku_image_controls(self):
        session = FakeSession()
        payload = {'skus': [{'image': f'{i}.jpg'} for i in range(21)]}
        with patch.object(pipeline, '_spec_row_image_step', return_value={
            'bind': {'saved': True, 'filledCount': 21}}) as rows, \
             patch.object(pipeline, '_image_step') as batch:
            result = pipeline.spec_images_gate(session, payload, [])
        self.assertTrue(result['bind']['saved'])
        self.assertEqual(rows.call_count, 1)
        batch.assert_not_called()

    def test_individual_rows_repair_image_lost_after_later_row(self):
        session = FakeSession()
        payload = {'skus': [{'image': f'{i}.jpg'} for i in range(3)]}
        selected = []
        audits = iter([
            {'total': 3, 'filled': 2, 'missing': [2], 'sources': [
                {'index': 1, 'src': 'url0'}, {'index': 2, 'src': ''}, {'index': 3, 'src': 'url2'}]},
            {'total': 3, 'filled': 3, 'missing': [], 'sources': [
                {'index': i + 1, 'src': f'url{i}'} for i in range(3)]},
        ])
        def run(session, script, args, timeout=120):
            if script == 'spec_row_status.js':
                return next(audits)
            if args['phase'] == 'open':
                return {'ready': True}
            selected.append(args['index'])
            return {'saved': True, 'imageSrc': f'url{args["index"]}'}
        with patch.object(pipeline, 'run_script', side_effect=run), \
             patch.object(pipeline.time, 'sleep'):
            result = pipeline._spec_row_image_step(session, payload)
        self.assertEqual(selected, [0, 1, 2, 1])
        self.assertEqual(result['bind']['filledCount'], 3)
        self.assertEqual(result['bind']['auditPasses'], 2)

    def test_individual_row_native_chooser_finishes_before_next_row(self):
        session = FakeSession()
        payload = {'skus': [{'image': 'a.jpg'}, {'image': 'b.jpg'}]}
        phases = []
        def run(session, script, args, timeout=120):
            if script == 'spec_row_status.js':
                return {'total': 2, 'filled': 2, 'missing': [], 'sources': [
                    {'index': 1, 'src': 'url0'}, {'index': 2, 'src': 'url1'}]}
            phases.append((args['index'], args['phase']))
            if args['phase'] == 'open':
                return {'ready': True}
            if args['phase'] == 'select':
                raise pipeline.FileChooserNeeded('file chooser')
            return {'saved': True, 'imageSrc': f'url{args["index"]}'}
        with patch.object(pipeline, 'run_script', side_effect=run), \
             patch.object(pipeline.time, 'sleep') as sleep:
            result = pipeline._spec_row_image_step(session, payload)
        self.assertEqual(session.uploads, ['a.jpg', 'b.jpg'])
        self.assertEqual(phases, [(0, 'open'), (0, 'select'), (0, 'finish'),
                                  (1, 'open'), (1, 'select'), (1, 'finish')])
        self.assertFalse(any(call.args[0] >= 19 for call in sleep.call_args_list))
        self.assertTrue(result['open']['pickerReopenedPerRow'])
        self.assertTrue(result['bind']['saved'])

    def test_individual_rows_repair_wrong_existing_image(self):
        session = FakeSession()
        payload = {'skus': [{'image': 'a.jpg'}, {'image': 'b.jpg'}]}
        selected = []
        audits = iter([
            {'total': 2, 'filled': 2, 'missing': [], 'sources': [
                {'index': 1, 'src': 'url0'}, {'index': 2, 'src': 'url0'}]},
            {'total': 2, 'filled': 2, 'missing': [], 'sources': [
                {'index': 1, 'src': 'url0'}, {'index': 2, 'src': 'url1'}]},
        ])
        def run(session, script, args, timeout=120):
            if script == 'spec_row_status.js':
                return next(audits)
            if args['phase'] == 'open':
                return {'ready': True}
            selected.append(args['index'])
            return {'saved': True, 'imageSrc': f'url{args["index"]}'}
        with patch.object(pipeline, 'run_script', side_effect=run), \
             patch.object(pipeline.time, 'sleep'):
            result = pipeline._spec_row_image_step(session, payload)
        self.assertEqual(selected, [0, 1, 1])
        self.assertEqual(result['bind']['auditPasses'], 2)

    def test_distinct_local_images_cannot_share_one_existing_sku_image(self):
        session = FakeSession()
        with tempfile.TemporaryDirectory() as root:
            a, b = Path(root) / 'a.jpg', Path(root) / 'b.jpg'
            a.write_bytes(b'a')
            b.write_bytes(b'b')
            payload = {'skus': [{'image': str(a)}, {'image': str(b)}]}
            def run(session, script, args, timeout=120):
                if script == 'spec_row_status.js':
                    return {'total': 2, 'filled': 2, 'missing': [], 'sources': [
                        {'index': 1, 'src': 'same'}, {'index': 2, 'src': 'same'}]}
                return {'already': True, 'saved': True, 'imageSrc': 'same'}
            with patch.object(pipeline, 'run_script', side_effect=run), \
                 patch.object(pipeline.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, r'规格图最终复核仍有缺失或错配行：1, 2'):
                    pipeline._spec_row_image_step(session, payload)

    def test_spec_images_use_throttled_upload_batches(self):
        session = FakeSession()
        payload = {'skus': [{'image': f'{i}.jpg'} for i in range(8)]}
        with patch.object(pipeline, '_image_step', return_value={'bind': {'saved': True}}) as image_step:
            pipeline.spec_images_gate(session, payload, [])
        sent = image_step.call_args.args[2]
        self.assertEqual(sent['uploadBatchSize'], 1)
        self.assertEqual(sent['uploadBatchDelayMinMs'], 5000)
        self.assertEqual(sent['uploadBatchDelayMaxMs'], 10000)

    def test_native_chooser_does_not_start_another_batch(self):
        session = FakeSession()
        files = ['one.jpg', 'two.jpg', 'three.jpg']
        with patch.object(pipeline, 'run_script', side_effect=[
            pipeline.FileChooserNeeded('file chooser'), {'uploaded': True}
        ]) as run, patch.object(pipeline.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'PAUSE:.*停止重复提交'):
                pipeline._upload_one_by_one(session, files)
        self.assertEqual(session.uploads, [])
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[2]['files'], files)

    def test_repeated_native_choosers_stop_at_the_first_ambiguous_batch(self):
        session = FakeSession()
        files = ['one.jpg', 'two.jpg', 'three.jpg']
        with patch.object(pipeline, 'run_script', side_effect=[
            pipeline.FileChooserNeeded('file chooser') for _ in files
        ]) as run, patch.object(pipeline.time, 'sleep') as sleep, \
             patch.object(pipeline.random, 'uniform', return_value=7000):
            with self.assertRaisesRegex(RuntimeError, 'PAUSE:.*停止重复提交'):
                pipeline._upload_one_by_one(session, files)
        self.assertEqual(session.uploads, [])
        self.assertEqual([len(call.args[2]['files']) for call in run.call_args_list], [3])
        sleep.assert_not_called()

    def test_spec_fallback_keeps_batch_policy_and_enough_time(self):
        session = FakeSession()
        options = {'uploadBatchSize': 3, 'uploadBatchDelayMinMs': 5000,
                   'uploadBatchDelayMaxMs': 10000}
        files = [f'{i}.jpg' for i in range(15)]
        with patch.object(pipeline, 'run_script', return_value={'uploaded': True}) as run:
            pipeline._upload_one_by_one(session, files, options)
        self.assertEqual(run.call_args.args[1], 'upload_files.js')
        self.assertEqual(run.call_args.args[2], {'files': files, 'uploadPacing': True, **options})
        self.assertGreater(run.call_args.kwargs['timeout'], 180)

    def test_challenge_from_fallback_stops_before_binding(self):
        session = FakeSession()
        phases = []
        def run(session, script, payload, timeout=120):
            phases.append((script, payload.get('phase')))
            if script == 'upload_files.js':
                raise RuntimeError('PAUSE:淘宝触发滑块，请手动完成验证')
            if payload.get('phase') == 'open':
                return {'uploaded': False, 'need_cli_upload': True, 'missing': ['a.jpg']}
            return {'saved': True}
        with patch.object(pipeline, 'run_script', side_effect=run):
            with self.assertRaisesRegex(RuntimeError, 'PAUSE:淘宝触发滑块'):
                pipeline._image_step(session, 'spec_images.js',
                                     {'uploadBatchSize': 3}, ['a.jpg'])
        self.assertNotIn(('spec_images.js', 'bind'), phases)

    def test_unconfirmed_upload_stops_without_per_file_waits(self):
        session = FakeSession()
        with patch.object(pipeline, 'run_script', return_value={'uploaded': False}) as run:
            with self.assertRaisesRegex(RuntimeError, '批量上传未确认成功'):
                pipeline._upload_one_by_one(session, ['a.jpg'] * 21)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(session.uploads, [])

    def test_fallback_without_policy_is_sequential(self):
        session = FakeSession()
        with patch.object(pipeline, 'run_script', return_value={'uploaded': True}) as run:
            pipeline._upload_one_by_one(session, [f'{i}.jpg' for i in range(5)])
        self.assertEqual(run.call_args.args[2]['uploadBatchSize'], 1)
        self.assertGreater(run.call_args.kwargs['timeout'], 90)

    def test_failed_upload_never_enters_binding(self):
        session = FakeSession()
        phases = []
        def run(session, script, payload, timeout=120):
            phases.append(payload.get('phase'))
            if payload.get('phase') == 'open':
                return {'uploaded': False, 'status': {'uploading': True}}
            return {'uploaded': False}
        with patch.object(pipeline, 'run_script', side_effect=run):
            with patch.object(pipeline, '_retry_failed_image_uploads', side_effect=lambda s, n, p, f, o, u: (u, [])):
                with self.assertRaisesRegex(RuntimeError, '已停止绑定'):
                    pipeline._image_step(session, 'spec_images.js', {}, ['a.jpg'])
        self.assertNotIn('bind', phases)

    def test_spec_images_uploads_shared_file_once(self):
        session = FakeSession()
        payload = {'skus': [{'image': 'shared.jpg'}, {'image': 'shared.jpg'}, {'image': 'other.jpg'}]}
        with patch.object(pipeline, '_image_step', return_value={'bind': {'saved': True}}) as image_step:
            pipeline.spec_images_gate(session, payload, [])
        self.assertEqual(image_step.call_args.args[3], ['shared.jpg', 'other.jpg'])

    def test_spec_upload_success_from_open_skips_rechecking_closed_dialog(self):
        session = FakeSession()
        phases = []
        def run(session, script, payload, timeout=120):
            phases.append(payload.get('phase'))
            return {'uploaded': True, 'saved': True}
        with patch.object(pipeline, 'run_script', side_effect=run):
            pipeline._image_step(session, 'spec_images.js', {}, ['a.jpg'])
        self.assertEqual(phases, ['open', 'bind'])

    def test_spec_fallback_uploads_only_missing_library_files(self):
        session = FakeSession()
        seen = []
        files = ['a.jpg', 'b.jpg', 'c.jpg']
        def run(session, script, payload, timeout=120):
            seen.append((script, payload))
            if payload.get('phase') == 'open':
                return {'uploaded': False, 'need_cli_upload': True, 'missing': ['b.jpg']}
            if payload.get('phase') == 'after_upload':
                return {'uploaded': True, 'verifiedBy': 'library-search'}
            return {'saved': True}
        with patch.object(pipeline, 'run_script', side_effect=run), \
             patch.object(pipeline, '_upload_one_by_one', return_value=[{'via': 'batch'}]) as upload:
            pipeline._image_step(session, 'spec_images.js', {}, files)
        self.assertEqual(upload.call_args.args[1], ['b.jpg'])
        after = [payload for script, payload in seen if payload.get('phase') == 'after_upload'][0]
        self.assertEqual(after['uploadNames'], ['b.jpg'])
        self.assertEqual(after['files'], ['b.jpg'])

    def test_spec_fallback_can_verify_library_after_upload_result_disappears(self):
        session = FakeSession()
        phases = []
        def run(session, script, payload, timeout=120):
            phases.append(payload.get('phase'))
            if payload.get('phase') == 'open':
                return {'uploaded': False, 'need_cli_upload': True, 'missing': ['b.jpg']}
            if payload.get('phase') == 'after_upload':
                return {'uploaded': True, 'verifiedBy': 'library-search'}
            return {'saved': True}
        with patch.object(pipeline, 'run_script', side_effect=run), \
             patch.object(pipeline, '_upload_one_by_one', side_effect=RuntimeError('批量上传未确认成功')):
            result = pipeline._image_step(session, 'spec_images.js', {}, ['a.jpg', 'b.jpg'])
        self.assertEqual(phases, ['open', 'after_upload', 'bind'])
        self.assertEqual(result['upload']['verifiedBy'], 'library-search')

    def test_missing_library_files_retry_without_network_error(self):
        session = FakeSession()
        with patch.object(pipeline, '_upload_one_by_one', return_value=[{'via': 'batch'}]) as upload, \
             patch.object(pipeline, 'run_script', return_value={'uploaded': True, 'verifiedBy': 'library-search'}) as run, \
             patch.object(pipeline.time, 'sleep'):
            result, attempts = pipeline._retry_failed_image_uploads(
                session, 'spec_images.js', {}, ['a.jpg', 'b.jpg', 'c.jpg'],
                {}, {'uploaded': False, 'missing': ['b.jpg']})
        self.assertTrue(result['uploaded'])
        self.assertEqual(len(attempts), 1)
        self.assertEqual(upload.call_args.args[1], ['b.jpg'])
        self.assertEqual(run.call_args.args[2]['files'], ['b.jpg'])

    def test_unconfirmed_spec_retry_still_checks_library(self):
        session = FakeSession()
        with patch.object(pipeline, '_upload_one_by_one', side_effect=RuntimeError('批量上传未确认成功')), \
             patch.object(pipeline, 'run_script', return_value={'uploaded': True, 'verifiedBy': 'library-search'}) as run, \
             patch.object(pipeline.time, 'sleep'):
            result, attempts = pipeline._retry_failed_image_uploads(
                session, 'spec_images.js', {}, ['a.jpg'], {},
                {'uploaded': False, 'missing': ['a.jpg']})
        self.assertTrue(result['uploaded'])
        self.assertIn('unconfirmed', attempts[0])
        self.assertEqual(run.call_args.args[2]['phase'], 'after_upload')


if __name__ == '__main__':
    unittest.main()
