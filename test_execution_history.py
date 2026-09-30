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
        self.assertNotIn("火影-001", session.get("execution_history") or {})
        merged = job_session.merge_execution(
            [self._item(2, "火影-001", "fp1")], "清单.xlsx"
        )
        self.assertEqual(merged[0]["execution"], "未执行")

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

    def test_unfinished_rows_are_not_archived(self):
        items = [self._item(2, "火影-001", "fp1")]
        job_session.remember_workbook("清单.xlsx", items)
        session = job_session.load_session()
        self.assertEqual(session.get("execution_history") or {}, {})


if __name__ == "__main__":
    unittest.main()
