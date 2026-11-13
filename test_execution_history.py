"""执行历史档案：文件夹删除/恢复后的执行状态回贴与内容指纹守卫。"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import job_session
import workspace
from test_workspace import write_mini_pack


def _seller():
    return workspace._seller()


class PackFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _validate(self):
        synced = workspace.sync_workbook(self.root, {"品牌": "卡游"})
        return synced, _seller().validate_workbook(synced["path"])

    def test_fingerprint_stable_while_content_unchanged(self):
        write_mini_pack(self.root / "火影-001")
        first_synced, first = self._validate()
        again = _seller().validate_workbook(first_synced["path"])
        self.assertTrue(first[0]["pack_fingerprint"])
        self.assertEqual(first[0]["pack_fingerprint"], again[0]["pack_fingerprint"])

    def test_fingerprint_changes_when_image_replaced(self):
        write_mini_pack(self.root / "火影-001")
        synced, first = self._validate()
        Image.new("RGB", (16, 16), "red").save(self.root / "火影-001" / "宝贝主图01.jpg")
        again = _seller().validate_workbook(synced["path"])
        self.assertNotEqual(first[0]["pack_fingerprint"], again[0]["pack_fingerprint"])

    def test_fingerprint_empty_when_folder_missing(self):
        write_mini_pack(self.root / "火影-001")
        synced, _ = self._validate()
        copy = self.root / "手工清单.xlsx"
        shutil.copyfile(synced["path"], copy)
        shutil.rmtree(self.root / "火影-001")
        results = _seller().validate_workbook(str(copy))
        self.assertEqual(results[0]["pack_fingerprint"], "")


class ExecutionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["QIANNIU_APPDATA"] = self.temp.name
        self.addCleanup(os.environ.pop, "QIANNIU_APPDATA", None)

    def _item(self, row, pid, fingerprint, execution="未执行", **extra):
        item = {
            "row": row,
            "product_id": pid,
            "validation": "通过",
            "execution": execution,
            "notice": "",
            "errors": [],
            "pack_fingerprint": fingerprint,
            "product": {"title": f"商品{pid}"},
        }
        item.update(extra)
        return item

    def test_folder_removed_then_returns_relinks_from_history(self):
        items = [self._item(2, "火影-001", "fp1", execution="已上架", taobao_item_id="123")]
        job_session.remember_workbook("清单.xlsx", items)
        # 行被移除后重新出现，行号变化，只能靠执行历史按商品标识回贴。
        merged = job_session.merge_execution(
            [self._item(5, "火影-001", "fp1")], "清单.xlsx"
        )
        self.assertEqual(merged[0]["execution"], "已上架")
        self.assertEqual(merged[0]["taobao_item_id"], "123")

    def test_content_fingerprint_mismatch_does_not_relink(self):
        items = [self._item(2, "火影-001", "fp1", execution="已上架", taobao_item_id="123")]
        job_session.remember_workbook("清单.xlsx", items)
        merged = job_session.merge_execution(
            [self._item(2, "火影-001", "fp2")], "清单.xlsx"
        )
        self.assertEqual(merged[0]["execution"], "未执行")
        self.assertFalse(merged[0].get("taobao_item_id"))

    def test_missing_current_fingerprint_falls_back_to_relink(self):
        # 指纹缺失（图片夹暂不可读）视为无法判断，保持原有回贴行为。
        items = [self._item(2, "火影-001", "fp1", execution="已上架", taobao_item_id="123")]
        job_session.remember_workbook("清单.xlsx", items)
        merged = job_session.merge_execution(
            [self._item(2, "火影-001", "")], "清单.xlsx"
        )
        self.assertEqual(merged[0]["execution"], "已上架")

    def test_legacy_session_without_fingerprint_relinks(self):
        # 旧版本会话没有指纹字段，升级后仍应回贴执行状态。
        items = [self._item(2, "火影-001", "", execution="已上架", taobao_item_id="123")]
        job_session.remember_workbook("清单.xlsx", items)
        merged = job_session.merge_execution(
            [self._item(2, "火影-001", "fp1")], "清单.xlsx"
        )
        self.assertEqual(merged[0]["execution"], "已上架")

    def test_row_number_fallback_is_gone(self):
        items = [self._item(2, "甲", "fp1", execution="已上架", taobao_item_id="123")]
        job_session.remember_workbook("清单.xlsx", items)
        merged = job_session.merge_execution(
            [self._item(2, "乙", "fp2")], "清单.xlsx"
        )
        self.assertEqual(merged[0]["execution"], "未执行")

    def test_forget_execution_prevents_relink(self):
        items = [self._item(2, "火影-001", "fp1", execution="已上架", taobao_item_id="123")]
        job_session.remember_workbook("清单.xlsx", items)
        job_session.forget_execution(row=2, product_id="火影-001")
        session = job_session.load_session()
        reset = session["execution_history"]["火影-001"]
        self.assertFalse(reset["taobao_item_id"])
        self.assertTrue(reset["execution_reset_id"])
        merged = job_session.merge_execution(
            [self._item(2, "火影-001", "fp1")], "清单.xlsx"
        )
        self.assertEqual(merged[0]["execution"], "未执行")
        self.assertEqual(merged[0]["execution_reset_id"], reset["execution_reset_id"])

    def test_forget_executions_batch_prevents_relink(self):
        items = [
            self._item(2, "火影-001", "fp1", execution="已上架", taobao_item_id="123"),
            self._item(3, "火影-002", "fp2", execution="已上架", taobao_item_id="456"),
        ]
        job_session.remember_workbook("清单.xlsx", items)
        job_session.forget_executions(rows=[2, 3])
        session = job_session.load_session()
        history = session["execution_history"]
        self.assertFalse(history["火影-001"]["taobao_item_id"])
        self.assertFalse(history["火影-002"]["taobao_item_id"])
        self.assertNotEqual(history["火影-001"]["execution_reset_id"], history["火影-002"]["execution_reset_id"])
        merged = job_session.merge_execution(
            [self._item(2, "火影-001", "fp1"), self._item(3, "火影-002", "fp2")], "清单.xlsx"
        )
        self.assertEqual(merged[0]["execution"], "未执行")
        self.assertEqual(merged[1]["execution"], "未执行")

    def test_reset_survives_revalidation_and_folder_disappearance(self):
        job_session.remember_workbook("清单.xlsx", [
            self._item(2, "火影-001", "fp1", execution="已上架", taobao_item_id="123")])
        job_session.forget_execution(row=2, product_id="火影-001")
        reset_id = job_session.load_session()["rows"][0]["execution_reset_id"]
        # Revalidating an empty workspace must retain the reset decision by product.
        job_session.remember_workbook("清单.xlsx", [])
        merged = job_session.merge_execution([self._item(4, "火影-001", "fp1")], "清单.xlsx")
        job_session.remember_workbook("清单.xlsx", merged)
        session = job_session.load_session()
        self.assertEqual(session["rows"][0]["execution_reset_id"], reset_id)
        self.assertFalse(session["rows"][0]["taobao_item_id"])
        job_session.forget_execution(row=4, product_id="火影-001")
        self.assertNotEqual(job_session.load_session()["rows"][0]["execution_reset_id"], reset_id)

    def test_patch_execution_archives_state(self):
        items = [self._item(2, "火影-001", "fp1")]
        job_session.remember_workbook("清单.xlsx", items)
        job_session.patch_execution(
            2, "火影-001", "已上架", notice="商品ID: 123", extra={"taobao_item_id": "123"}
        )
        history = job_session.load_session().get("execution_history") or {}
        self.assertEqual(history["火影-001"]["taobao_item_id"], "123")
        self.assertEqual(history["火影-001"]["pack_fingerprint"], "fp1")

    def test_patch_flow_state_archives_flow_stage(self):
        items = [self._item(2, "火影-001", "fp1")]
        job_session.remember_workbook("清单.xlsx", items)
        job_session.patch_flow_state(2, "火影-001", {"flow_stage": "complete"})
        history = job_session.load_session().get("execution_history") or {}
        self.assertEqual(history["火影-001"]["flow_stage"], "complete")
        self.assertEqual(history["火影-001"]["pack_fingerprint"], "fp1")

    def test_confirmed_video_warning_clear_survives_restart_and_history_restore(self):
        warning = "主视频未上传：索引未确认"
        for patch_kind in ("execution", "flow"):
            with self.subTest(patch_kind=patch_kind):
                item = self._item(2, "火影-001", "fp1", execution="已入库",
                                  taobao_item_id="123", video_warning=warning)
                item["product"]["video_warning"] = warning
                job_session.remember_workbook("清单.xlsx", [item])
                if patch_kind == "execution":
                    job_session.patch_execution(2, "火影-001", "已入库", extra={"video_warning": ""})
                else:
                    job_session.patch_flow_state(2, "火影-001", {"video_warning": ""})
                session = job_session.load_session()
                self.assertEqual(session["rows"][0]["video_warning"], "")
                self.assertEqual(session["products"][0]["meta"]["video_warning"], "")
                self.assertEqual(session["products"][0]["product"]["video_warning"], "")
                self.assertEqual(session["execution_history"]["火影-001"]["video_warning"], "")
                restored = job_session.merge_execution([
                    self._item(2, "火影-001", "fp1", video_warning=warning)], "清单.xlsx")
                self.assertEqual(restored[0]["video_warning"], "")

    def test_publish_checkpoint_and_write_intent_survive_restart(self):
        item = self._item(2, '火影-001', 'fp1', execution='暂停')
        job_session.remember_workbook('清单.xlsx', [item])
        before = {'key': 'same-product', 'href': 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=123',
                  'submit_started': False}
        intent = {'script': 'sku_import.js', 'phase': 'open'}
        job_session.patch_flow_state(2, '火影-001', {'resume_checkpoint': before, 'last_browser_write': intent})
        pending = {**before, 'submit_started': True}
        job_session.patch_execution(2, '火影-001', '提交待核实', extra={'resume_checkpoint': pending})
        session = job_session.load_session()
        self.assertEqual(session['rows'][0]['resume_checkpoint'], pending)
        self.assertEqual(session['products'][0]['meta']['resume_checkpoint'], pending)
        self.assertEqual(session['products'][0]['product']['resume_checkpoint'], pending)
        restored = job_session.merge_execution([self._item(2, '火影-001', 'fp1')], '清单.xlsx')
        self.assertEqual(restored[0]['resume_checkpoint'], pending)
        self.assertEqual(restored[0]['last_browser_write'], intent)

    def test_video_status_survives_restart_and_replaces_previous_failure(self):
        item = self._item(2, '火影-001', 'fp1', execution='已入库', taobao_item_id='123456789',
                          video_status='failed', video_warning='主视频未上传')
        item['product']['video_status'] = 'failed'
        job_session.remember_workbook('清单.xlsx', [item])
        job_session.patch_flow_state(2, '火影-001', {'video_status': 'uploaded', 'video_warning': ''})
        state = job_session.load_session()
        self.assertEqual(state['rows'][0]['video_status'], 'uploaded')
        self.assertEqual(state['products'][0]['product']['video_status'], 'uploaded')
        restored = job_session.merge_execution([self._item(2, '火影-001', 'fp1')], '清单.xlsx')
        self.assertEqual(restored[0]['video_status'], 'uploaded')
        self.assertEqual(restored[0]['video_warning'], '')

    def test_unfinished_rows_are_not_archived(self):
        items = [self._item(2, "火影-001", "fp1")]
        job_session.remember_workbook("清单.xlsx", items)
        session = job_session.load_session()
        self.assertEqual(session.get("execution_history") or {}, {})


if __name__ == "__main__":
    unittest.main()
