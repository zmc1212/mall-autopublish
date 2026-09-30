import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_web_fill import FakeSession
from web_fill import pipeline as p


class MediaFirstFlowTests(unittest.TestCase):
    def setUp(self):
        self.product = {'title': '图片优先测试', 'category_id': '50012720',
                        'spec_name': '商品规格', 'main_images': ['main.jpg'],
                        'portrait_images': ['portrait.jpg'], 'detail_images': ['detail.jpg'],
                        'skus': [{'name': '甲', 'image': 'sku.jpg', 'price': 1, 'stock': 1}]}
        self.payload = p.product_to_payload(self.product)

    def test_media_precedes_attributes_and_both_sku_strategies(self):
        for template in (False, True):
            with self.subTest(template=template), tempfile.TemporaryDirectory() as directory:
                calls = []
                session = FakeSession()
                def run(s, script, args, timeout=120):
                    calls.append(script)
                    return {'title': ''} if script == 'probe_state.js' else {'ok': True}
                def image(s, script, args, files):
                    calls.append(args.get('field', script))
                    return {'uploaded': True}
                with patch.object(p, 'get_output', return_value=Path(directory)), \
                     patch.object(p, 'run_script', side_effect=run), \
                     patch.object(p, '_image_step', side_effect=image), \
                     patch.object(p, 'import_skus_from_template', side_effect=lambda *a: calls.append('import-skus')), \
                     patch.object(p, 'spec_images_gate', side_effect=lambda *a: calls.append('spec-images')), \
                     patch.object(p, '_finish_publish', return_value={'execution': '已填写未提交'}):
                    result = p.fill_new_product(session, self.product, sku_template_import=template)
                self.assertEqual(result['execution'], '已填写未提交', result)
                ordered = ['#sell-field-mainImagesGroup', '#sell-field-threeToFourImages', 'details.js',
                           'attributes.js', 'import-skus' if template else 'skus.js', 'spec-images']
                positions = [calls.index(step) for step in ordered]
                self.assertEqual(positions, sorted(positions), calls)

    def test_media_popup_before_attributes_never_skips_attributes_or_skus(self):
        state = {'title': '', 'skuRows': 0, 'specImgs': 0, 'mainImgs': 1,
                 'popup': True, 'checkpoint': {'key': p.resume_key(self.payload),
                                               'completed': ['category', 'main_images']}}
        self.assertFalse(p.page_conflicts(state, self.payload))
        self.assertEqual(p.decide_skips(state, self.payload), {'main_images'})
        state['skuRows'] = 1  # The form's default row is not a filled SKU.
        self.assertEqual(p.decide_skips(state, self.payload), {'main_images'})

    def test_upload_pause_preserves_scene_without_running_warehouse_cleanup(self):
        session, calls = FakeSession(), []
        def run(s, script, args, timeout=120):
            calls.append(script)
            return {'title': ''} if script == 'probe_state.js' else {'ok': True}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(p, 'get_output', return_value=Path(directory)), \
             patch.object(p, 'run_script', side_effect=run), \
             patch.object(p, '_image_step', side_effect=RuntimeError('PAUSE:请滑动验证码')):
            result = p.fill_new_product(session, self.product)
        self.assertEqual(result['execution'], '暂停')
        self.assertNotIn('warehouse.js', calls)
        self.assertNotIn('attributes.js', calls)
        self.assertNotIn('skus.js', calls)

    def test_portrait_only_progress_resumes_before_title(self):
        state = {'title': '', 'p34Imgs': 1,
                 'checkpoint': {'key': p.resume_key(self.payload),
                                'completed': ['category', 'portraits']}}
        self.assertFalse(p.page_conflicts(state, self.payload))
        self.assertEqual(p.decide_skips(state, self.payload), {'portraits'})

    def test_old_checkpoint_cannot_skip_empty_title_or_default_sku_row(self):
        state = {'title': '', 'detailImgs': 1, 'skuRows': 1, 'skuNames': [''],
                 'popup': True, 'checkpoint': {'key': p.resume_key(self.payload),
                     'completed': ['attributes', 'skus', 'main_images', 'spec_images']}}
        self.assertEqual(p.decide_skips(state, self.payload), {'details'})
        # Keep genuinely filled SKUs, but refill the missing title/attributes.
        state['skuNames'] = ['甲']
        self.assertEqual(p.decide_skips(state, self.payload), {'details', 'skus'})

    def test_legacy_completion_uploads_media_before_attributes_and_sku_images(self):
        session, calls = FakeSession(), []
        def run(s, script, args, timeout=120):
            calls.append(script)
            return {'ok': True}
        def image(s, script, args, files):
            calls.append(script)
            return {'uploaded': True}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(p, 'get_output', return_value=Path(directory)), \
             patch.object(p, 'select_kayou_tab', return_value=session.href()), \
             patch.object(p, 'run_script', side_effect=run), \
             patch.object(p, '_image_step', side_effect=image), \
             patch.object(p, 'spec_images_gate', side_effect=lambda *a: calls.append('spec-images')), \
             patch.object(p, '_finish_publish', return_value={'execution': '已填写未提交'}):
            result = p.complete_current_product(session, self.product, confirm_submit=False)
        self.assertEqual(result['execution'], '已填写未提交', result)
        ordered = ['main_images.js', 'details.js', 'attributes.js', 'sku_category.js', 'spec-images']
        positions = [calls.index(step) for step in ordered]
        self.assertEqual(positions, sorted(positions), calls)
        self.assertEqual(session.uploads, [])

    def test_sku_popup_does_not_hide_completed_media(self):
        state = {'title': self.product['title'], 'skuRows': 1, 'specImgs': 0,
                 'mainImgs': 1, 'p34Imgs': 1, 'detailImgs': 1, 'specDialog': True, 'popup': True}
        self.assertEqual(p.decide_skips(state, self.payload),
                         {'attributes', 'skus', 'main_images', 'portraits', 'details'})

    def test_resume_after_media_before_title_keeps_uploaded_images(self):
        state = {'title': '', 'skuRows': 0, 'specImgs': 0, 'mainImgs': 1, 'p34Imgs': 1,
                 'detailImgs': 0, 'popup': True,
                 'checkpoint': {'key': p.resume_key(self.payload),
                                'completed': ['category', 'main_images', 'portraits']}}
        session = FakeSession()
        calls, images = [], []
        def run(s, script, args, timeout=120):
            calls.append(script)
            return copy.deepcopy(state) if script == 'probe_state.js' else {'ok': True}
        def image(s, script, args, files):
            images.append(script)
            return {'uploaded': True}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(p, 'get_output', return_value=Path(directory)), \
             patch.object(p, 'run_script', side_effect=run), \
             patch.object(p, '_image_step', side_effect=image), \
             patch.object(p, 'spec_images_gate'), \
             patch.object(p, '_finish_publish', return_value={'execution': '已填写未提交'}):
            result = p.fill_new_product(session, self.product)
        self.assertEqual(result['execution'], '已填写未提交', result)
        self.assertEqual(images, ['details.js'])
        self.assertIn('attributes.js', calls)
        self.assertIn('skus.js', calls)
        self.assertIn('close_overlays.js', calls)
        self.assertFalse(any(call[0] == 'tab-new' for call in session.calls))


if __name__ == '__main__':
    unittest.main()
