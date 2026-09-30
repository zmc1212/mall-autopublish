import copy
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_web_fill import FakeSession
from web_fill import pipeline as p


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.product = {'title': '晨光大美之诗静音按动中性笔书写行家速干水笔中国风ins高颜值学生考试刷题ST头按压式签字笔黑色0.5AGPK3319',
                        'skus': [{'name': '规格'+str(i), 'image': str(i)+'.jpg'} for i in range(21)],
                        'main_images': ['main.jpg']}
        self.payload = p.product_to_payload(self.product)
        self.state = {'title': p.display_title(self.product['title']), 'skuRows': 21,
                      'specImgs': 21, 'mainImgs': 0, 'skuNames': ['规格'+str(i) for i in range(21)]}

    def test_legacy_truncated_title_requires_matching_skus(self):
        self.assertFalse(p.page_conflicts(self.state, self.payload))
        wrong = {**self.state, 'skuNames': ['another product']}
        self.assertTrue(p.page_conflicts(wrong, self.payload))

    def test_checkpoint_cannot_skip_deleted_images_or_changed_product(self):
        state = {**self.state, 'checkpoint': {'key': p.resume_key(self.payload), 'completed': ['attributes','spec_images']}}
        self.assertNotIn('spec_images', p.decide_skips(state, self.payload))
        state['specImgs'] = 20
        self.assertNotIn('spec_images', p.decide_skips(state, self.payload))
        other = copy.deepcopy(self.payload)
        other['skus'][0]['image'] = 'changed.jpg'
        self.assertTrue(p.page_conflicts(state, other))

    def test_interrupt_at_main_resumes_before_attributes_and_skus(self):
        session = FakeSession()
        state = {**self.state, 'title': '', 'skuRows': 0, 'specImgs': 0}
        calls = []
        interrupted = [False]
        def run(s, name, payload, timeout=120):
            calls.append(name)
            if name == 'probe_state.js': return copy.deepcopy(state)
            if name == 'checkpoint.js':
                state['checkpoint'] = copy.deepcopy(payload)
                return payload
            if name == 'attributes.js': state['title'] = self.state['title']
            return {'ok': True}
        def specs(s, payload, steps):
            state.update(skuRows=21, specImgs=21)
            return {'saved': True}
        def image(s, name, payload, files):
            if not interrupted[0]:
                interrupted[0] = True
                raise p.UserStopped('PAUSE:测试中断')
            state['mainImgs'] = 1
            return {'uploaded': True}
        with tempfile.TemporaryDirectory() as directory, patch.object(p, 'get_output', return_value=Path(directory)), \
             patch.object(p, 'run_script', side_effect=run), patch.object(p, 'spec_images_gate', side_effect=specs) as spec_call, \
             patch.object(p, '_image_step', side_effect=image), \
             patch.object(p, '_finish_publish', return_value={'execution': '已填写未提交', 'notice': '', 'errors': []}):
            first = p.fill_new_product(session, self.product)
            self.assertEqual(first['execution'], '暂停', first)
            self.assertEqual(spec_call.call_count, 0)
            self.assertNotIn('attributes.js', calls)
            self.assertNotIn('skus.js', calls)
            calls.clear()
            second = p.fill_new_product(session, self.product)
            self.assertEqual(second['execution'], '已填写未提交')
            self.assertEqual(spec_call.call_count, 1)
            self.assertIn('attributes.js', calls)
            self.assertIn('skus.js', calls)
            self.assertFalse(any(c[0] == 'tab-new' for c in session.calls))

    def test_cancel_checked_before_browser_action(self):
        s = FakeSession()
        s.cancel_event = threading.Event()
        s.cancel_event.set()
        with self.assertRaises(p.UserStopped):
            p.run_script(s, 'main_images.js', {})
        self.assertEqual(s.calls, [])

    def test_failed_batch_keeps_page_and_does_not_start_next_product(self):
        s = FakeSession()
        web = p._load_web()
        with patch.object(p, '_prune_tabs') as prune, patch.object(web, 'assert_logged_in'), \
             patch.object(p, '_remember_item'), patch.object(p, '_write_progress'), \
             patch.object(p, 'fill_new_product', return_value={'execution':'失败','notice':'主图超时'}) as fill:
            result = p.run_batch([self.product, self.product], session=s)
        self.assertEqual(len(result), 1)
        self.assertEqual(fill.call_count, 1)
        self.assertEqual(prune.call_args.kwargs['keep_url'], s.href())


if __name__ == '__main__':
    unittest.main()
