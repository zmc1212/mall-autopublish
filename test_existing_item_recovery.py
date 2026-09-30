"""Offline tests: an existing item ID must never silently create a duplicate."""
import copy
import unittest
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
        self.session = FakeSession()
        self.web = p._load_web()

    def recover(self, state=None, risk=None, rows=None, product=None):
        with patch.object(p, 'run_script', side_effect=[state or self.state, risk or {}]) as script, \
             patch.object(m, 'inspect_target_skus', return_value=self.rows if rows is None else rows):
            result = p._recover_existing_item(self.session, self.web, product or self.product, self.item_id)
        self.assertEqual([c.args[1] for c in script.call_args_list], ['probe_state.js', 'upload_status.js'])
        self.assertTrue(script.call_args_list[0].args[2]['waitForReady'])
        self.assertFalse(self.session.uploads)
        self.assertEqual([c[0] for c in self.session.calls], ['tab-new'])
        return result

    def test_readonly_recovery_checks_server_page_and_sku_values(self):
        self.assertEqual(self.recover(), self.rows)

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
                        {'skuNames': ['其他颜色']}, {'skuRows': 0},
                        {'mainImgs': 0}, {'detailImgs': 0},
                        {'warehouse': [{'t': '放入仓库', 'checked': False}]}):
            with self.subTest(changed=changed), \
                 patch.object(p, 'run_script', side_effect=[{**self.state, **changed}, {}]), \
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

    def batch(self, product=None, confirm=True, force_new=False, recovery_error=None):
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, '_recover_existing_item', return_value=self.rows, side_effect=recovery_error) as recover, \
             patch.object(p, '_spec_column_state', return_value=({1: 'spec.jpg'}, [])), \
             patch.object(p, 'run_script', return_value={}), \
             patch.object(p, 'fill_new_product', return_value={'execution': '已填写未提交'}) as fill, \
             patch.object(m, 'run_material_flow', return_value={'stage': m.STAGE_COMPLETE}) as material:
            result = p.run_batch([product or self.product], session=self.session,
                                 confirm_submit=confirm, force_new=force_new)
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


if __name__ == '__main__':
    unittest.main()
