import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop import paths
from desktop.jobs import JobManager
from test_web_fill import FakeSession
from web_fill import pipeline as p, material_import as m


class SearchMainRoutingTests(unittest.TestCase):
    def setUp(self):
        self.web = p._load_web()
        self.product = {'title': '测试', 'skus': [{'name': '蓝杆', 'image': 'blue.jpg'}]}

    def run_batch(self, product, material, **kwargs):
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, '_repair_existing_spec_images') as spec, \
             patch.object(p, 'fill_new_product', return_value={
                 'execution': '结果待核实', 'taobao_item_id': '1085270103015'}) as fill, \
             patch.object(m, 'run_material_flow', side_effect=material):
            out = p.run_batch([product], session=FakeSession(), confirm_submit=True, **kwargs)[0]
        spec.assert_not_called()
        return out, fill

    def test_default_new_product_skips_spec_and_uses_existing_import_service(self):
        calls = []
        def material(session, web, product, item_id, state, on_stage):
            calls.append((item_id, state['stage']))
            on_stage(m.STAGE_COMPLETE, {'verified': [{'sku_id': '6141276652863'}]})
            return {**state, 'stage': m.STAGE_COMPLETE}
        out, fill = self.run_batch(self.product, material)
        self.assertTrue(fill.call_args.kwargs['skip_spec_images'])
        self.assertEqual(calls, [('1085270103015', m.STAGE_CREATED)])
        self.assertEqual(out['execution'], '已入库，搜索主图已核验')
        self.assertIn('销售规格图未执行', out['notice'])

    def test_resume_retains_preview_and_never_creates_or_uploads(self):
        preview = [{'name': '蓝杆', 'sku_id': '6141276652863', 'image': 'image.jpg'}]
        product = {**self.product, 'taobao_item_id': '1085270103015',
                   'flow_stage': m.STAGE_ADOPT_PENDING, 'material_preview': preview,
                   'sku_material_manifest': preview, 'material_folder': 'saved-folder'}
        def material(session, web, product, item_id, state, on_stage):
            self.assertEqual(state['preview'], preview)
            self.assertEqual(state['folder'], 'saved-folder')
            self.assertEqual(state['stage'], m.STAGE_ADOPT_PENDING)
            raise RuntimeError('PAUSE:服务器结果待核实')
        out, fill = self.run_batch(product, material)
        fill.assert_not_called()
        self.assertEqual(out['execution'], '暂停')
        self.assertEqual(out['material_preview'], preview)
        self.assertNotEqual(out['flow_stage'], m.STAGE_COMPLETE)

    def test_old_spec_complete_begins_search_import_without_new_item(self):
        product = {**self.product, 'taobao_item_id': '1085270103015',
                   'flow_stage': m.STAGE_COMPLETE, 'flow_version': p.SPEC_COLUMN_FLOW_VERSION,
                   'sku_image_strategy': m.STRATEGY_PUBLISH, 'material_preview': ['stale']}
        def material(session, web, product, item_id, state, on_stage):
            self.assertEqual(state['stage'], m.STAGE_CREATED)
            self.assertEqual(state['preview'], [])
        _, fill = self.run_batch(product, material, sku_image_strategy=m.STRATEGY_SLIM)
        fill.assert_not_called()

    def test_search_complete_is_reverified_not_reuploaded(self):
        product = {**self.product, 'taobao_item_id': '1085270103015',
                   'flow_stage': m.STAGE_COMPLETE, 'flow_version': m.FLOW_VERSION,
                   'material_result': [{'image': 'previous.jpg'}]}
        def material(session, web, product, item_id, state, on_stage):
            self.assertEqual(state['stage'], m.STAGE_VERIFYING)
            self.assertEqual(state['preview'], product['material_result'])
        _, fill = self.run_batch(product, material)
        fill.assert_not_called()

    def test_old_settings_migrate_and_explicit_v3_choice_persists(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / 'settings.json'
            with patch.object(paths, 'settings_path', return_value=file):
                file.write_text(json.dumps({'settings_version': 2, 'sku_image_strategy': 'publish_page'}))
                self.assertEqual(paths.load_settings().sku_image_strategy, m.STRATEGY_SLIM)
                paths.save_settings(paths.Settings(sku_image_strategy=m.STRATEGY_PUBLISH))
                self.assertEqual(paths.load_settings().sku_image_strategy, m.STRATEGY_PUBLISH)
                paths.save_settings(paths.Settings(sku_image_strategy='both'))
                self.assertEqual(paths.load_settings().sku_image_strategy, 'both')

    def test_search_completion_is_done_for_its_own_flow(self):
        manager = JobManager()
        row = {'flow_stage': m.STAGE_COMPLETE, 'sku_image_strategy': m.STRATEGY_SLIM,
               'taobao_item_id': '1085270103015'}
        # _row_flow_done 读取当前设置里的策略；隔离真实 settings.json。
        with patch.object(paths, 'load_settings',
                          return_value=paths.Settings(sku_image_strategy=m.STRATEGY_SLIM)):
            self.assertTrue(manager._row_flow_done(row))
            self.assertFalse(manager._row_flow_resumable(row))

    def test_selecting_both_reopens_a_completed_single_target_record(self):
        manager = JobManager()
        row = {'flow_stage': m.STAGE_COMPLETE, 'sku_image_strategy': m.STRATEGY_SLIM,
               'taobao_item_id': '1085270103015'}
        with patch.object(paths, 'load_settings', return_value=paths.Settings(sku_image_strategy='both')):
            self.assertFalse(manager._row_flow_done(row))
            self.assertTrue(manager._row_flow_done({**row, 'sku_image_strategy': 'both'}))


if __name__ == '__main__':
    unittest.main()
