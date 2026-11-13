"""Offline tests: an existing item ID must never silently create a duplicate."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_web_fill import FakeSession
from web_fill import material_import as m, pipeline as p


class ExistingItemRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.item_id = '1087608952245'
        self.product = {
            'title': '测试商品', 'execution': '暂停', 'taobao_item_id': self.item_id,
            'sku_image_strategy': m.STRATEGY_SLIM,
            'main_images': ['main.jpg'], 'detail_images': ['detail.jpg'],
            'skus': [{'name': '黑色', 'price': 6.9, 'stock': 10, 'image': 'sku.jpg'}],
        }
        self.rows = [{'name': '黑色', 'sku_id': '6141276652863', 'price': '6.90',
                      'stock': '10', 'image': '', 'search_title': '-'}]
        self.state = {'href': 'https://item.upload.taobao.com/sell/v2/publish.htm?itemId=' + self.item_id,
                      'title': '测试商品', 'skuRows': 1, 'skuNames': ['黑色'],
                      'mainImgs': 1, 'detailImgs': 1,
                      'warehouse': [{'t': '放入仓库', 'checked': True}]}
        self.audit = {'audit': True, 'count': 1, 'missing': [], 'extra': []}
        self.session = FakeSession()
        self.web = p._load_web()

    def recover(self, state=None, risk=None, rows=None, product=None):
        with patch.object(p, 'run_script', side_effect=[state or self.state, risk or {}, self.audit]) as script, \
             patch.object(m, 'inspect_target_skus', return_value=self.rows if rows is None else rows):
            result = p._recover_existing_item(self.session, self.web, product or self.product, self.item_id)
        self.assertEqual([c.args[1] for c in script.call_args_list], ['probe_state.js', 'upload_status.js', 'sku_import.js'])
        self.assertEqual(script.call_args_list[2].args[2]['phase'], 'audit')
        self.assertTrue(script.call_args_list[0].args[2]['waitForReady'])
        self.assertFalse(self.session.uploads)
        self.assertEqual(sum(c[0] == 'tab-new' for c in self.session.calls), 1)
        self.assertTrue(all(c[0] in {'tab-new', 'tab-list', 'tab-select'} for c in self.session.calls))
        return result

    def test_readonly_recovery_checks_server_page_and_sku_values(self):
        self.assertEqual(self.recover(), self.rows)

    def test_recovery_can_verify_server_without_opening_material_drawer(self):
        with patch.object(p, 'run_script', side_effect=[self.state, {}, self.audit]) as script, \
             patch.object(m, 'inspect_target_skus') as inspect:
            result = p._recover_existing_item(
                self.session, self.web, self.product, self.item_id,
                inspect_material=False,
            )
        self.assertIsNone(result)
        inspect.assert_not_called()
        self.assertEqual([c.args[1] for c in script.call_args_list],
                         ['probe_state.js', 'upload_status.js', 'sku_import.js'])
        self.assertEqual(script.call_args_list[2].args[2]['phase'], 'audit')
        self.assertFalse(self.session.uploads)

    def test_long_title_uses_existing_display_convention(self):
        product = {**self.product, 'title': '测试商品' * 30}
        state = {**self.state, 'title': p.display_title(product['title'])}
        self.assertEqual(self.recover(state=state, product=product), self.rows)

    def test_invalid_id_has_no_browser_action(self):
        with self.assertRaisesRegex(RuntimeError, '已有商品 ID 无效'):
            p._recover_existing_item(self.session, self.web, self.product, 'bad-id')
        self.assertEqual(self.session.calls, [])

    def test_wrong_item_title_skus_media_or_warehouse_cannot_migrate(self):
        for changed in ({'href': 'https://example.test/?itemId=' + self.item_id},
                        {'href': self.state['href'] + '0'}, {'title': '其他商品'},
                        {'mainImgs': 0}, {'detailImgs': 0},
                        {'warehouse': [{'t': '放入仓库', 'checked': False}]}):
            with self.subTest(changed=changed), \
                 patch.object(p, 'run_script', side_effect=[{**self.state, **changed}, {}, self.audit]), \
                 patch.object(m, 'inspect_target_skus') as inspect, \
                 self.assertRaisesRegex(RuntimeError, 'PAUSE:'):
                p._recover_existing_item(self.session, self.web, self.product, self.item_id)
            inspect.assert_not_called()

    def test_deep_sku_audit_rejects_missing_extra_or_incomplete_rows(self):
        for audit in ({}, {**self.audit, 'count': 0},
                      {**self.audit, 'missing': ['黑色']}, {**self.audit, 'extra': ['其他颜色']}):
            with self.subTest(audit=audit), \
                 patch.object(p, 'run_script', side_effect=[self.state, {}, audit]), \
                 patch.object(m, 'inspect_target_skus') as inspect, \
                 self.assertRaisesRegex(RuntimeError, 'PAUSE:'):
                p._recover_existing_item(self.session, self.web, self.product, self.item_id)
            inspect.assert_not_called()

    def test_security_gate_never_reaches_materials(self):
        for state, risk in (({**self.state, 'captchaVisible': True}, {}),
                            (self.state, {'securityChallenge': 'captcha'}),
                            (self.state, {'status': {'securityLimit': True}})):
            with self.subTest(risk=risk), \
                 patch.object(p, 'run_script', side_effect=[state, risk]), \
                 patch.object(m, 'inspect_target_skus') as inspect, \
                 self.assertRaisesRegex(RuntimeError, '安全验证'):
                p._recover_existing_item(self.session, self.web, self.product, self.item_id)
            inspect.assert_not_called()

    def test_changed_prices_stock_or_ids_are_rejected(self):
        for change in ({'price': '7'}, {'stock': '9'}, {'sku_id': ''}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.recover(rows=[{**self.rows[0], **change}])

    def batch(self, product=None, confirm=True, force_new=False, recovery_error=None,
              fill_result=None, retry_limit=0):
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, '_recover_existing_item', return_value=self.rows, side_effect=recovery_error) as recover, \
             patch.object(p, '_spec_column_state', return_value=({1: 'spec.jpg'}, [])), \
             patch.object(p, 'run_script', return_value={}), \
             patch.object(p, 'fill_new_product', return_value=fill_result or {'execution': '已填写未提交'}) as fill, \
             patch.object(m, 'run_material_flow', return_value={'stage': m.STAGE_COMPLETE}) as material:
            result = p.run_batch([product or self.product], session=self.session,
                                 confirm_submit=confirm, force_new=force_new, item_retry_limit=retry_limit)
        return result[0], recover, fill, material

    def test_id_only_legacy_record_recovers_and_never_creates(self):
        original = copy.deepcopy(self.product)
        result, recover, fill, material = self.batch()
        self.assertEqual(self.product, original)
        self.assertEqual(recover.call_count, 1)
        fill.assert_not_called()
        material.assert_called_once()
        self.assertEqual(result['flow_stage'], m.STAGE_COMPLETE)
        self.assertEqual(result['run_status'], 'completed')
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['last_error'], '')

    def test_both_resume_with_completed_spec_skips_spec_repair_and_resumes_search(self):
        product = {
            **self.product,
            'sku_image_strategy': 'both',
            'flow_version': p.BOTH_IMAGE_FLOW_VERSION,
            'flow_stage': m.STAGE_RECOGNIZING,
            'spec_image_stage': m.STAGE_COMPLETE,
        }
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, '_recover_existing_item', return_value=None) as recover, \
             patch.object(p, '_spec_column_state', return_value=({1: 'spec.jpg'}, [])) as spec_state, \
             patch.object(p, '_repair_existing_spec_images') as repair, \
             patch.object(p, '_finish_product_tabs'), \
             patch.object(p, '_run_search_images') as search:
            def resume_search(_session, _web, _product, item, _on_flow_stage=None, combined=False):
                self.assertTrue(combined)
                item.update(flow_stage=m.STAGE_COMPLETE, execution='已入库，图片已核验',
                            run_status='completed', errors=[], last_error='')

            search.side_effect = resume_search
            result = p.run_batch([product], session=self.session, confirm_submit=True)

        self.assertEqual(result[0]['run_status'], 'completed')
        repair.assert_not_called()
        recover.assert_called_once_with(
            self.session, self.web, product, self.item_id, inspect_material=False
        )
        spec_state.assert_called_once_with(self.session, product)
        search.assert_called_once()
        self.assertTrue(search.call_args.kwargs['combined'])

    def test_both_completed_spec_missing_stops_without_spec_repair(self):
        product = {
            **self.product,
            'sku_image_strategy': 'both',
            'flow_version': p.BOTH_IMAGE_FLOW_VERSION,
            'flow_stage': m.STAGE_RECOGNIZING,
            'spec_image_stage': m.STAGE_COMPLETE,
        }
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, '_recover_existing_item', return_value=None) as recover, \
             patch.object(p, '_spec_column_state', return_value=({1: ''}, [1])), \
             patch.object(p, '_repair_existing_spec_images') as repair, \
             patch.object(p, '_run_search_images') as search:
            result = p.run_batch([product], session=self.session, confirm_submit=True)

        self.assertEqual(result[0]['execution'], '暂停')
        self.assertIn('规格图缺失', result[0]['notice'])
        self.assertIn('禁止自动重复', result[0]['notice'])
        repair.assert_not_called()
        search.assert_not_called()
        recover.assert_called_once_with(
            self.session, self.web, product, self.item_id, inspect_material=False
        )

    def test_unknown_or_pending_stages_with_id_never_fall_through(self):
        for stage in ('', 'pending', 'unexpected', m.STAGE_FILLED, m.STAGE_SUBMIT_PENDING):
            with self.subTest(stage=stage):
                _, recover, fill, material = self.batch({**self.product, 'flow_stage': stage})
                self.assertEqual(recover.call_count, 1)
                fill.assert_not_called()
                material.assert_called_once()

    def test_recovery_failure_cannot_submit_or_upload(self):
        result, _, fill, material = self.batch(recovery_error=RuntimeError('PAUSE:目标商品不符'))
        fill.assert_not_called()
        material.assert_not_called()
        self.assertEqual(result['execution'], '暂停')
        self.assertNotEqual(result.get('flow_stage'), m.STAGE_COMPLETE)

    def test_unconfirmed_run_never_starts_material_upload(self):
        result, recover, fill, material = self.batch(confirm=False)
        self.assertEqual(recover.call_count, 1)
        fill.assert_not_called()
        material.assert_not_called()
        self.assertEqual(result['flow_stage'], m.STAGE_CREATED)

    def test_publish_strategy_completes_only_after_spec_column_verification(self):
        result, _, fill, material = self.batch({**self.product, 'sku_image_strategy': m.STRATEGY_PUBLISH})
        fill.assert_not_called()
        material.assert_not_called()
        self.assertEqual(result['execution'], '已入库，图片已核验')
        self.assertEqual(result.get('flow_stage'), m.STAGE_COMPLETE)

    def test_force_new_still_requires_explicit_option(self):
        _, recover, fill, material = self.batch(confirm=False, force_new=True)
        recover.assert_not_called()
        fill.assert_called_once()
        material.assert_not_called()

    def test_submit_pending_without_id_still_never_resubmits(self):
        result, recover, fill, material = self.batch({**self.product, 'taobao_item_id': '',
                                                   'flow_stage': m.STAGE_SUBMIT_PENDING})
        recover.assert_not_called()
        fill.assert_not_called()
        material.assert_not_called()
        self.assertEqual(result['execution'], '暂停')

    def test_lost_id_recovers_from_results_without_creating(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'QIANNIU_RESULTS_DIR': directory}):
            Path(directory, '清单.结果-20261007.json').write_text(json.dumps({'results': [
                {**self.product, 'product_id': 'blind-box-apple'}]}), encoding='utf-8')
            product = {**self.product, 'product_id': 'blind-box-apple', 'taobao_item_id': '', 'flow_stage': ''}
            result, recover, fill, material = self.batch(product)
        self.assertEqual(result['taobao_item_id'], self.item_id)
        fill.assert_not_called()
        recover.assert_called_once()
        material.assert_called_once()

    def test_ambiguous_history_cannot_create_or_upload(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'QIANNIU_RESULTS_DIR': directory}):
            Path(directory, '清单.结果-20261007.json').write_text(json.dumps({'rows': [
                self.product, {**self.product, 'taobao_item_id': '1087608952246'}]}), encoding='utf-8')
            result, recover, fill, material = self.batch({**self.product, 'taobao_item_id': '', 'flow_stage': ''})
        self.assertIn('多个已创建商品 ID', result['notice'])
        recover.assert_not_called()
        fill.assert_not_called()
        material.assert_not_called()

    def test_history_does_not_recover_a_different_product_or_seller(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'QIANNIU_RESULTS_DIR': directory}):
            Path(directory, '清单.结果-20261007.json').write_text(json.dumps({'rows': [
                {**self.product, 'product_id': 'other-product'},
                {**self.product, 'product_id': 'target-product', 'seller_account': 'other-seller'}]}), encoding='utf-8')
            self.assertIsNone(p._historical_item_for_product(
                {**self.product, 'product_id': 'target-product'}, 'target-seller'))

    def test_clear_then_continue_after_restart_only_recreates_cleared_product(self):
        import job_session
        from desktop.jobs import JobManager

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'QIANNIU_APPDATA': directory, 'QIANNIU_RESULTS_DIR': directory}):
            manager = JobManager()
            manager.workbook_path = str(Path(directory, '清单.xlsx'))
            failed = {**self.product, 'row': 3, 'product_id': 'apple', 'validation': '通过',
                      'url': self.state['href'], 'resume_checkpoint': {'key': 'old'},
                      'last_browser_write': {'script': 'submit.js'}}
            completed = {**failed, 'row': 2, 'product_id': 'other', 'flow_stage': 'complete',
                         'sku_image_strategy': 'both', 'flow_version': p.BOTH_IMAGE_FLOW_VERSION,
                         'taobao_item_id': '1087608952246', 'execution': '已入库，图片已核验'}
            manager.rows = [dict(completed), dict(failed)]
            manager.products = [{'meta': dict(item), 'product': dict(item)} for item in manager.rows]
            manager._save_session()
            Path(directory, '清单.结果-20261012.json').write_text(
                json.dumps({'results': [completed, failed]}), encoding='utf-8')
            manager.clear_row_state(3, 'apple')
            # The normal revalidate/restart path must carry the user's reset.
            fresh = [{'row': item['row'], 'product_id': item['product_id'], 'validation': '通过',
                      'product': {'title': item['title'], 'skus': item['skus']}}
                     for item in [completed, failed]]
            merged = job_session.merge_execution(fresh, manager.workbook_path)
            job_session.remember_workbook(manager.workbook_path, merged)
            restored = job_session.load_session()
            restarted = JobManager()
            restarted.rows, restarted.products = restored['rows'], restored['products']
            pending = restarted._pending_products()
            self.assertEqual([item['product_id'] for item in pending], ['apple'])
            self.assertTrue(pending[0]['execution_reset_id'])
            self.assertFalse(pending[0]['taobao_item_id'])
            self.assertFalse(pending[0].get('url'))
            self.assertFalse(pending[0].get('resume_checkpoint'))
            self.assertFalse(pending[0].get('last_browser_write'))
            result, recover, fill, material = self.batch(pending[0], confirm=False)
            recover.assert_not_called()
            fill.assert_called_once()
            self.assertTrue(fill.call_args.kwargs['force_new'])
            material.assert_not_called()
            self.assertEqual(result['execution_reset_id'], pending[0]['execution_reset_id'])
            self.assertEqual(restarted.rows[0]['taobao_item_id'], completed['taobao_item_id'])

    def test_reset_changes_browser_lease_and_checkpoint_identity(self):
        from web_fill.concurrent_batch import item_key

        original = {**self.product, 'row': 3, 'product_id': 'apple'}
        reset = {**original, 'execution_reset_id': 'reset-1', 'taobao_item_id': '', 'execution': '未执行'}
        again = {**reset, 'execution_reset_id': 'reset-2'}
        self.assertNotEqual(item_key(original), item_key(reset))
        self.assertNotEqual(item_key(reset), item_key(again))
        self.assertNotEqual(p.resume_key(p.product_to_payload(original)),
                            p.resume_key(p.product_to_payload(reset)))
        # Automatic retry/resume within the reset keeps the same browser lease.
        resumed = {**reset, 'taobao_item_id': self.item_id, 'flow_stage': m.STAGE_CREATED}
        self.assertEqual(item_key(reset), item_key(resumed))

    def test_reset_generation_recovers_only_id_created_after_that_reset(self):
        reset_id = 'current-reset'
        new_id = '1087608952247'
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'QIANNIU_APPDATA': directory, 'QIANNIU_RESULTS_DIR': directory}):
            Path(directory, '清单.结果-20261012.json').write_text(json.dumps({'results': [
                self.product, {**self.product, 'execution_reset_id': 'previous-reset'},
                {**self.product, 'execution_reset_id': reset_id, 'taobao_item_id': new_id}]}), encoding='utf-8')
            result, recover, fill, _ = self.batch({**self.product, 'taobao_item_id': '',
                'flow_stage': '', 'execution_reset_id': reset_id})
            self.assertEqual(result['taobao_item_id'], new_id)
            self.assertEqual(recover.call_args.args[3], new_id)
            fill.assert_not_called()

    def test_uncertain_submit_after_clear_never_repeats_creation(self):
        result, recover, fill, material = self.batch(
            {**self.product, 'taobao_item_id': '', 'flow_stage': '', 'execution_reset_id': 'reset'},
            fill_result={'execution': '提交待核实', 'flow_stage': m.STAGE_SUBMIT_PENDING,
                         'notice': '提交结果不明确；禁止自动重复提交'}, retry_limit=3)
        fill.assert_called_once()
        recover.assert_not_called()
        material.assert_not_called()
        self.assertEqual(result['flow_stage'], m.STAGE_SUBMIT_PENDING)
        result, recover, fill, material = self.batch(result, retry_limit=3)
        fill.assert_not_called()
        recover.assert_not_called()
        material.assert_not_called()

    def test_deleted_item_pauses_without_create_upload_or_automatic_retry(self):
        deleted = {**self.state, 'title': '', 'pageError': {
            'code': 'item_deleted', 'message': '当前商品已被删除无法编辑！'}}
        with patch.object(p, 'run_script', side_effect=[deleted, {}]), \
             patch.object(m, 'inspect_target_skus') as inspect, \
             self.assertRaisesRegex(RuntimeError, '历史商品已被删除.*清除记录.*继续入库') as error:
            p._recover_existing_item(self.session, self.web, self.product, self.item_id)
        inspect.assert_not_called()
        self.assertFalse(p.gate_error_retryable(error.exception))
        result, recover, fill, material = self.batch(recovery_error=error.exception, retry_limit=3)
        recover.assert_called_once()
        fill.assert_not_called()
        material.assert_not_called()
        self.assertEqual(result['taobao_item_id'], self.item_id)
        self.assertEqual(result['execution'], '暂停')


if __name__ == '__main__':
    unittest.main()
