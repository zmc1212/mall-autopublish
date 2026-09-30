"""The listing pipeline must populate 商品规格, not SKU搜索主图."""
import unittest
from unittest.mock import patch

from web_fill import pipeline as p, material_import as m
from test_web_fill import FakeSession


class SpecColumnRoutingTests(unittest.TestCase):
    def setUp(self):
        self.product = {"title": "测试", "skus": [{"name": "黑色", "image": "sku.jpg"}],
                        "taobao_item_id": "1085482487262", "flow_stage": "complete",
                        "flow_version": "old", "sku_image_strategy": "publish_page"}
        self.web = p._load_web()

    def test_explicit_strategy_selects_the_requested_image_column(self):
        self.assertEqual(p.resolve_sku_strategy({}), "slim_material")
        for setting in ("slim_material", "publish_page", "both"):
            self.assertEqual(p.resolve_sku_strategy(self.product, setting), setting)

    def test_both_existing_item_verifies_spec_before_search_without_recreating(self):
        events = []
        product = {**self.product, 'flow_version': m.FLOW_VERSION,
                   'flow_stage': m.STAGE_COMPLETE,
                   'material_preview': [{'sku_id': '1'}]}
        def verify_spec(*args, **kwargs):
            events.append('spec')
            return {'flow_stage': m.STAGE_COMPLETE}
        def verify_search(session, web, source, item_id, state, on_stage):
            events.append(('search', state['stage']))
            return {**state, 'stage': m.STAGE_COMPLETE}
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, '_repair_existing_spec_images', side_effect=verify_spec), \
             patch.object(p, 'fill_new_product') as create, \
             patch.object(m, 'run_material_flow', side_effect=verify_search):
            out = p.run_batch([product], session=FakeSession(), confirm_submit=True,
                              sku_image_strategy='both')[0]
        self.assertEqual(events, ['spec', ('search', m.STAGE_VERIFYING)])
        create.assert_not_called()
        self.assertEqual(out['flow_version'], p.BOTH_IMAGE_FLOW_VERSION)
        self.assertEqual(out['spec_image_stage'], m.STAGE_COMPLETE)
        self.assertEqual(out['flow_stage'], m.STAGE_COMPLETE)

    def test_both_stops_before_search_when_spec_result_is_uncertain(self):
        product = {**self.product, 'spec_image_stage': m.STAGE_SUBMIT_PENDING}
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, '_repair_existing_spec_images',
                          side_effect=RuntimeError('PAUSE:规格图保存结果不明确')), \
             patch.object(m, 'run_material_flow') as materials:
            out = p.run_batch([product], session=FakeSession(), confirm_submit=True,
                              sku_image_strategy='both')[0]
        materials.assert_not_called()
        self.assertEqual(out['execution'], '暂停')
        self.assertEqual(out['spec_image_stage'], m.STAGE_SUBMIT_PENDING)

    def test_both_new_item_runs_spec_then_search(self):
        product = {"title": "测试", "skus": [{"name": "黑色", "image": "sku.jpg"}]}
        events = []
        def create(*args, **kwargs):
            events.append('create')
            # 建品阶段一律不传规格图，规格图统一入库后分批补传。
            self.assertTrue(kwargs.get('skip_spec_images'))
            return {'execution': '已入库', 'taobao_item_id': '1085482487262'}
        def verify_spec(*args, **kwargs):
            events.append('spec')
            return {'flow_stage': m.STAGE_COMPLETE}
        def verify_search(session, web, source, item_id, state, on_stage):
            events.append('search')
            return {**state, 'stage': m.STAGE_COMPLETE}
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, 'fill_new_product', side_effect=create), \
             patch.object(p, '_repair_existing_spec_images', side_effect=verify_spec), \
             patch.object(m, 'run_material_flow', side_effect=verify_search):
            out = p.run_batch([product], session=FakeSession(), confirm_submit=True,
                              sku_image_strategy='both')[0]
        self.assertEqual(events, ['create', 'spec', 'search'])
        self.assertEqual(out['flow_version'], p.BOTH_IMAGE_FLOW_VERSION)
        self.assertEqual(out['spec_image_stage'], m.STAGE_COMPLETE)

    def test_zero_error_banner_does_not_block_save(self):
        self.assertEqual(p.required_blockers({'banners': ['错误 (0) 建议 (3)'],
                                             'empty': [], 'warehouseOn': True}), [])
        self.assertTrue(p.required_blockers({'banners': ['错误 (2)']}))

    def test_old_complete_repairs_existing_id_without_material_or_new_item(self):
        result = {"flow_stage": "complete", "flow_version": p.SPEC_COLUMN_FLOW_VERSION,
                  "execution": "已入库，图片已核验"}
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, '_repair_existing_spec_images', return_value=result) as repair, \
             patch.object(p, 'fill_new_product') as create, patch.object(m, 'run_material_flow') as materials:
            out = p.run_batch([self.product], session=FakeSession(), confirm_submit=True)
        repair.assert_called_once()
        self.assertEqual(repair.call_args.args[3], self.product['taobao_item_id'])
        create.assert_not_called()
        materials.assert_not_called()
        self.assertEqual(out[0]['sku_image_strategy'], 'publish_page')

    def test_old_complete_cannot_remain_complete_when_repair_fails(self):
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, '_repair_existing_spec_images', side_effect=RuntimeError('PAUSE:需要安全验证')):
            out = p.run_batch([self.product], session=FakeSession(), confirm_submit=True)[0]
        self.assertEqual(out['execution'], '暂停')
        self.assertNotEqual(out['flow_stage'], 'complete')

    def test_missing_spec_sources_are_not_complete(self):
        with patch.object(p, 'run_script', return_value={'total': 1, 'filled': 1,
                                                      'sources': [{'index': 1, 'src': ''}]}):
            _, missing = p._spec_column_state(FakeSession(), self.product)
        self.assertEqual(missing, [1])

    def test_spec_source_normalizes_protocol_only(self):
        for src in ('https://img.alicdn.com/spec.png', '//img.alicdn.com/spec.png'):
            with patch.object(p, 'run_script', return_value={'total': 1,
                 'sources': [{'index': 1, 'src': src}]}):
                sources, missing = p._spec_column_state(FakeSession(), self.product)
            self.assertEqual(sources, {1: '//img.alicdn.com/spec.png'})
            self.assertEqual(missing, [])

    def test_existing_missing_images_require_submission_confirmation(self):
        with patch.object(p, '_recover_existing_item', return_value=[]), \
             patch.object(p, 'run_script', return_value={}), \
             patch.object(p, '_spec_column_state', return_value=({1: ''}, [1])), \
             patch.object(p, 'spec_images_gate') as bind, \
             patch.object(p, '_finish_publish') as submit:
            with self.assertRaisesRegex(RuntimeError, '确认提交'):
                p._repair_existing_spec_images(FakeSession(), self.web, self.product,
                                              self.product['taobao_item_id'], False)
        bind.assert_not_called()
        submit.assert_not_called()

    def test_reload_losing_spec_image_cannot_complete(self):
        with patch.object(p, '_recover_existing_item', return_value=[]), \
             patch.object(m, 'check_rows'), patch.object(p, 'run_script', return_value={}), \
             patch.object(p, '_spec_column_state', side_effect=[({1: 'spec.jpg'}, []), ({1: ''}, [1])]), \
             patch.object(p, '_finish_publish') as submit:
            with self.assertRaisesRegex(RuntimeError, '刷新后'):
                p._repair_existing_spec_images(FakeSession(), self.web, self.product,
                                              self.product['taobao_item_id'], True)
        submit.assert_not_called()

    def test_uncertain_previous_spec_save_is_never_resubmitted(self):
        product = {**self.product, 'flow_version': p.SPEC_COLUMN_FLOW_VERSION,
                   'flow_stage': m.STAGE_SUBMIT_PENDING}
        with patch.object(p, '_recover_existing_item', return_value=[]), \
             patch.object(p, 'run_script', return_value={}), \
             patch.object(p, '_spec_column_state', return_value=({1: ''}, [1])), \
             patch.object(p, 'spec_images_gate') as bind:
            with self.assertRaisesRegex(RuntimeError, '禁止自动重复提交'):
                p._repair_existing_spec_images(FakeSession(), self.web, product,
                                              product['taobao_item_id'], True)
        bind.assert_not_called()

    def test_both_uncertain_spec_save_is_never_resubmitted(self):
        product = {**self.product, 'flow_version': p.BOTH_IMAGE_FLOW_VERSION,
                   'flow_stage': m.STAGE_CREATED,
                   'spec_image_stage': m.STAGE_SUBMIT_PENDING}
        with patch.object(p, '_recover_existing_item', return_value=[]), \
             patch.object(p, 'run_script', return_value={}), \
             patch.object(p, '_spec_column_state', return_value=({1: ''}, [1])), \
             patch.object(p, 'spec_images_gate') as bind:
            with self.assertRaisesRegex(RuntimeError, '禁止自动重复提交'):
                p._repair_existing_spec_images(FakeSession(), self.web, product,
                                              product['taobao_item_id'], True)
        bind.assert_not_called()


class SpecBatchUploadTests(unittest.TestCase):
    """规格图入库后分批补传：每批只处理 N 行，保存后退出编辑页再进下一批。"""

    def setUp(self):
        self.item_id = '1087608952245'
        self.web = p._load_web()

    def test_spec_gate_scopes_small_sku_sets_through_payload(self):
        skus = [{"name": "甲", "image": "a.jpg"}, {"name": "乙", "image": "b.jpg"},
                {"name": "丙", "image": "c.jpg"}]
        captured = {}

        def fake_image_step(session, script, upload_payload, files, on_bind_progress=None, **kwargs):
            captured["files"] = list(files)
            captured["onlyRows"] = upload_payload.get("onlyRows")
            captured["payloadFiles"] = upload_payload.get("files")
            return {"bind": {"saved": True}}

        with patch.object(p, '_image_step', side_effect=fake_image_step):
            p.spec_images_gate(FakeSession(), {"skus": skus}, [], only_rows=[1])
        self.assertEqual(captured["files"], ["b.jpg"])
        self.assertEqual(captured["onlyRows"], [1])
        self.assertEqual(captured["payloadFiles"], ["b.jpg"])

    def test_spec_gate_scopes_large_sku_sets_by_row_indexes(self):
        skus = [{"name": f"规格{i}", "image": f"{i}.jpg"} for i in range(13)]
        captured = {}

        def fake_row_step(session, upload_payload, on_bind_progress=None, only_indexes=None, **kwargs):
            captured["only_indexes"] = only_indexes
            return {"bind": {"saved": True}}

        with patch.object(p, '_spec_row_image_step', side_effect=fake_row_step):
            p.spec_images_gate(FakeSession(), {"skus": skus}, [], only_rows=[5, 2])
        self.assertEqual(captured["only_indexes"], [2, 5])

    def test_spec_images_unbound_counts_only_scoped_rows(self):
        payload = {"skus": [{"name": "甲", "image": "a.jpg"}, {"name": "乙", "image": "b.jpg"}]}
        step = {"bind": {"filledCount": 1}}
        self.assertFalse(p.spec_images_unbound(step, payload, only_rows=[0]))
        self.assertTrue(p.spec_images_unbound(step, payload))

    def test_spec_batch_loop_saves_per_batch_and_exits_edit_page(self):
        product = {"title": "测试",
                   "skus": [{"name": f"规格{i}", "image": f"{i}.jpg"} for i in range(1, 5)]}
        bound_rows = []
        gate_calls = []
        finished = []

        def gate(session, payload, steps, **kwargs):
            rows = kwargs["only_rows"]
            gate_calls.append(list(rows))
            for row in rows:
                bound_rows.append(row + 1)
            sources = {row: f"s{row}.jpg" for row in bound_rows}
            return {"bind": {"saved": True}}

        def column_state(session, product):
            sources = {row: f"s{row}.jpg" for row in bound_rows}
            missing = [row for row in range(1, 5) if row not in sources]
            return sources, missing

        with patch.object(p, '_recover_existing_item', return_value=[]), \
             patch.object(m, 'check_rows'), patch.object(p, 'run_script', return_value={}), \
             patch.object(p, '_spec_column_state', side_effect=column_state), \
             patch.object(p, 'spec_images_gate', side_effect=gate), \
             patch.object(p, '_finish_publish', side_effect=lambda *a, **k: finished.append(1) or {
                 'taobao_item_id': self.item_id}), \
             patch.object(p, '_prune_tabs') as prune, patch.object(p, '_write_progress'):
            result = p._repair_existing_spec_images(FakeSession(), self.web, product,
                                                    self.item_id, True, spec_batch_size=2)
        self.assertEqual(gate_calls, [[0, 1], [2, 3]])
        self.assertEqual(len(finished), 2)
        self.assertEqual(prune.call_count, 2)
        self.assertEqual(result['flow_stage'], m.STAGE_COMPLETE)
        self.assertEqual(result['spec_image_stage'], m.STAGE_COMPLETE)
        self.assertEqual(result['execution'], '已入库，图片已核验')

    def test_spec_batch_loop_pauses_when_save_result_uncertain(self):
        product = {"title": "测试", "skus": [{"name": "黑色", "image": "sku.jpg"}]}
        bound = []

        def column_state(session, product):
            sources = {1: 's1.jpg'} if bound else {}
            return sources, [] if bound else [1]

        def gate(session, payload, steps, **kwargs):
            bound.extend(row + 1 for row in kwargs["only_rows"])
            return {"bind": {"saved": True}}

        with patch.object(p, '_recover_existing_item', return_value=[]), \
             patch.object(m, 'check_rows'), patch.object(p, 'run_script', return_value={}), \
             patch.object(p, '_spec_column_state', side_effect=column_state), \
             patch.object(p, 'spec_images_gate', side_effect=gate), \
             patch.object(p, '_finish_publish', return_value={}), \
             patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'):
            with self.assertRaisesRegex(RuntimeError, '待核实'):
                p._repair_existing_spec_images(FakeSession(), self.web, product,
                                               self.item_id, True, spec_batch_size=1)

    def test_new_item_defers_spec_images_to_batches_after_creation(self):
        product = {"title": "测试", "skus": [{"name": "黑色", "image": "sku.jpg"}]}
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, 'fill_new_product', return_value={
                 'execution': '结果待核实', 'taobao_item_id': self.item_id}) as create, \
             patch.object(p, '_repair_existing_spec_images', return_value={
                 'flow_stage': m.STAGE_COMPLETE, 'execution': '已入库，图片已核验'}) as repair:
            out = p.run_batch([product], session=FakeSession(), confirm_submit=True,
                              sku_image_strategy='publish_page', spec_upload_batch_size=2)[0]
        self.assertTrue(create.call_args.kwargs.get('skip_spec_images'))
        self.assertEqual(repair.call_args.args[3], self.item_id)
        self.assertTrue(repair.call_args.args[4])
        self.assertEqual(repair.call_args.kwargs.get('spec_batch_size'), 2)
        self.assertEqual(out['flow_stage'], m.STAGE_COMPLETE)

    def test_existing_id_resume_uses_configured_batch_size(self):
        product = {"title": "测试", "skus": [{"name": "黑色", "image": "sku.jpg"}],
                   "taobao_item_id": self.item_id, "flow_stage": m.STAGE_COMPLETE,
                   "flow_version": "old", "sku_image_strategy": "publish_page"}
        with patch.object(p, '_prune_tabs'), patch.object(p, '_write_progress'), \
             patch.object(p, '_remember_item'), patch.object(self.web, 'assert_logged_in'), \
             patch.object(p, '_repair_existing_spec_images', return_value={
                 'flow_stage': m.STAGE_COMPLETE, 'execution': '已入库，图片已核验'}) as repair, \
             patch.object(p, 'fill_new_product') as create:
            p.run_batch([product], session=FakeSession(), confirm_submit=True,
                        spec_upload_batch_size=3)
        create.assert_not_called()
        self.assertEqual(repair.call_args.kwargs.get('spec_batch_size'), 3)


if __name__ == '__main__':
    unittest.main()
