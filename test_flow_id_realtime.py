"""建品成功瞬间 ID/执行状态实时回显的回归测试。

背景（2026-10-04 用户反馈）：执行明细里“已入库，待补图”配着“未执行/无ID”，
首页“已入库”计数停在 0，要等整条补图流程终态才纠正。根因是 on_flow 只回写
FLOW_FIELDS，ID/execution/view_url/edit_url 要等 on_done 才回填。

三层防线：
1. pipeline 建品成功即设 execution=已入库，待补图；
2. jobs.on_flow 把 ID/execution/链接随 flow 字段实时写进 rows 并经
   patch_flow_state 落盘（崩溃后 ID 不丢，续跑不会重复建品）；
3. merge_execution 恢复回贴不再以 execution != “未执行”为唯一门。
"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import job_session


class PatchFlowStateItemIdTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(
            os.environ,
            {
                "QIANNIU_APPDATA": str(Path(self.temp.name) / "appdata"),
                "QIANNIU_RESULTS_DIR": str(Path(self.temp.name) / "results"),
            },
            clear=False,
        )
        env.start()
        self.addCleanup(env.stop)

    def _seed(self):
        rows = [
            {
                "row": 1,
                "product_id": "P-1",
                "validation": "通过",
                "product": {"title": "商品 1"},
            },
        ]
        job_session.remember_workbook(str(Path(self.temp.name) / "清单.xlsx"), rows)
        return rows

    def test_patch_flow_state_persists_item_id_and_execution(self):
        self._seed()
        job_session.patch_flow_state(1, "P-1", {
            "flow_stage": "created",
            "execution": "已入库，待补图",
            "taobao_item_id": "1234567890123",
        })
        saved = job_session.load_session()
        row = saved["rows"][0]
        self.assertEqual(row["taobao_item_id"], "1234567890123")
        self.assertEqual(row["execution"], "已入库，待补图")
        self.assertEqual(row["flow_stage"], "created")
        # 显式 ID 出现时同步生成查看/编辑链接
        self.assertIn("id=1234567890123", row["view_url"])
        self.assertIn("itemId=1234567890123", row["edit_url"])
        meta = saved["products"][0]["meta"]
        self.assertEqual(meta["taobao_item_id"], "1234567890123")
        self.assertEqual(meta["execution"], "已入库，待补图")

    def test_patch_flow_state_without_item_id_keeps_links_untouched(self):
        self._seed()
        job_session.patch_flow_state(1, "P-1", {"flow_stage": "created",
                                                "taobao_item_id": "1234567890123"})
        # 后续只带 flow 字段的 emit 不清空已落盘的 ID/链接
        job_session.patch_flow_state(1, "P-1", {"flow_stage": "material_reviewed",
                                                "material_folder": "F-1"})
        row = job_session.load_session()["rows"][0]
        self.assertEqual(row["taobao_item_id"], "1234567890123")
        self.assertEqual(row["flow_stage"], "material_reviewed")
        self.assertIn("id=1234567890123", row["view_url"])

    def test_merge_execution_repastes_item_id_when_execution_untouched(self):
        self._seed()

        # 模拟旧版本断点：execution 仍是“未执行”，但 ID/flow_stage 已落盘
        def mutate(data):
            data["rows"][0].update({
                "execution": "未执行",
                "taobao_item_id": "9876543210123",
                "flow_stage": "created",
                "updated_at": "2026-10-04T01:00:00",
            })
            data["products"][0]["meta"].update({
                "execution": "未执行",
                "taobao_item_id": "9876543210123",
                "flow_stage": "created",
                "updated_at": "2026-10-04T01:00:00",
            })

        job_session.update_session(mutate)
        results = [{
            "row": 1,
            "product_id": "P-1",
            "validation": "通过",
            "pack_fingerprint": "",
            "product": {"title": "商品 1"},
        }]
        merged = job_session.merge_execution(results, str(Path(self.temp.name) / "清单.xlsx"))[0]
        self.assertEqual(merged["taobao_item_id"], "9876543210123")
        self.assertEqual(merged["flow_stage"], "created")
        # execution 未落盘时不强行覆盖展示文案（保持默认“未执行”）
        self.assertEqual(merged.get("execution") or "未执行", "未执行")


class OnFlowRealtimeTests(unittest.TestCase):
    """on_flow 必须在条目终态前就把 ID/执行状态发布进 rows 与会话落盘。"""

    ITEM_ID = "1234567890123"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(
            os.environ,
            {
                "QIANNIU_APPDATA": str(Path(self.temp.name) / "appdata"),
                "QIANNIU_RESULTS_DIR": str(Path(self.temp.name) / "results"),
            },
            clear=False,
        )
        env.start()
        self.addCleanup(env.stop)
        from desktop.paths import configure_environ
        configure_environ()
        # 生产上导入清单/工作空间即建立会话；不 seed 的话 patch_flow_state
        # 会按“无会话”no-op，测试就偏离了真实时序。
        job_session.remember_workbook(str(Path(self.temp.name) / "清单.xlsx"), [
            {"row": 1, "product_id": "P-1", "validation": "通过", "product": {"title": "商品 1"}},
        ])

    def _make_manager(self):
        from desktop.jobs import JobManager, serialize_row

        manager = JobManager()
        item = {"row": 1, "product_id": "P-1", "validation": "通过", "product": {"title": "商品 1"}}
        row = serialize_row(item)
        manager.rows = [row]
        manager.products = [{
            "meta": dict(item),
            "product": {"row": 1, "product_id": "P-1", "title": "商品 1"},
        }]
        return manager

    def _run_with_fake_pipeline(self, manager, mid_run_assert):
        import desktop.jobs as jobs

        created_item = {
            "execution": "已入库，待补图",
            "flow_stage": "created",
            "flow_version": "flow-test",
            "taobao_item_id": self.ITEM_ID,
            "notice": "提交成功 商品ID: " + self.ITEM_ID,
        }
        # _run_job 会把 run_batch 内的异常吞进任务日志，mid 断言失败必须
        # 延后重抛，否则测试只看到被级联污染的终态。
        pending_errors = []

        def fake_run_batch(products, **kwargs):
            product = products[0]
            # 建品成功瞬间：pipeline 会先 emit flow，再继续补图，条目尚未终态。
            kwargs["on_flow_stage"](product, dict(created_item))
            try:
                mid_run_assert(manager)
            except Exception as exc:  # noqa: BLE001 - 延后到 _run_job 返回后重抛
                pending_errors.append(exc)
            final_item = {
                **created_item,
                "row": product.get("row"),
                "execution": "已入库，搜索主图已核验",
                "run_status": "completed",
                "duration_seconds": 12.0,
            }
            kwargs["on_item_done"](product, final_item)
            return [final_item]

        seller = SimpleNamespace(
            load_web_fill=lambda: SimpleNamespace(run_batch=fake_run_batch),
            write_log=lambda *args, **kwargs: None,
        )
        with patch.object(jobs, "load_seller", return_value=seller):
            manager._run_job(confirm_submit=True)
        if pending_errors:
            raise pending_errors[0]

    def test_on_flow_publishes_item_id_before_item_done(self):
        def mid_run_assert(manager):
            # 1) 内存 rows：执行明细即时显示 ID/执行/入库状态
            snapshot = manager.snapshot()
            row = snapshot["rows"][0]
            self.assertEqual(row["taobao_item_id"], self.ITEM_ID)
            self.assertEqual(row["execution"], "已入库，待补图")
            self.assertEqual(row["flow_stage"], "created")
            self.assertIn("id=" + self.ITEM_ID, row["view_url"])
            # 2) 会话落盘：此刻断电/被杀，续跑也拿得到 ID，不会重复建品
            saved = job_session.load_session()
            saved_row = next(r for r in saved["rows"] if r.get("row") == 1)
            self.assertEqual(saved_row["taobao_item_id"], self.ITEM_ID)
            self.assertEqual(saved_row["execution"], "已入库，待补图")

        manager = self._make_manager()
        self._run_with_fake_pipeline(manager, mid_run_assert)

        # 终态回填不回退：ID 保留，execution 更新为最终文案
        row = manager.rows[0]
        self.assertEqual(row["taobao_item_id"], self.ITEM_ID)
        self.assertEqual(row["execution"], "已入库，搜索主图已核验")
        self.assertEqual(manager.status, "done")

    def test_on_flow_without_item_id_keeps_previous_row_state(self):
        from desktop.jobs import JobManager, serialize_row

        manager = JobManager()
        item = {"row": 1, "product_id": "P-1", "validation": "通过", "product": {"title": "商品 1"}}
        row = serialize_row(item)
        row["taobao_item_id"] = self.ITEM_ID
        row["view_url"] = f"https://item.taobao.com/item.htm?id={self.ITEM_ID}"
        manager.rows = [row]
        manager.products = [{
            "meta": {**item, "taobao_item_id": self.ITEM_ID},
            "product": {"row": 1, "product_id": "P-1"},
        }]
        # 真实续跑场景：上一轮已把 ID 持久化进会话，本次中途 emit 不得清掉它。
        def seed_item_id(data):
            data["rows"][0].update({"taobao_item_id": self.ITEM_ID})
            data["products"][0]["meta"].update({"taobao_item_id": self.ITEM_ID})

        job_session.update_session(seed_item_id)

        pending_errors = []

        def mid_run_assert(_manager):
            saved = job_session.load_session()
            saved_row = next(r for r in saved["rows"] if r.get("row") == 1)
            self.assertEqual(saved_row["taobao_item_id"], self.ITEM_ID)

        def fake_run_batch(products, **kwargs):
            product = products[0]
            # 续跑补图路径的 emit 只带 flow 字段，没有 taobao_item_id
            kwargs["on_flow_stage"](product, {
                "flow_stage": "material_reviewed",
                "execution": "已入库，待补图",
                "material_folder": "F-1",
            })
            try:
                mid_run_assert(manager)
            except Exception as exc:  # noqa: BLE001 - 延后到 _run_job 返回后重抛
                pending_errors.append(exc)
            final_item = {"row": product.get("row"), "execution": "已入库，图片已核验", "run_status": "completed"}
            kwargs["on_item_done"](product, final_item)
            return [final_item]

        seller = SimpleNamespace(
            load_web_fill=lambda: SimpleNamespace(run_batch=fake_run_batch),
            write_log=lambda *args, **kwargs: None,
        )
        import desktop.jobs as jobs
        with patch.object(jobs, "load_seller", return_value=seller):
            manager._run_job(confirm_submit=True)
        if pending_errors:
            raise pending_errors[0]

        # 缺 ID 的中途 emit 不得清空已回填的 ID/链接
        row = manager.rows[0]
        self.assertEqual(row["taobao_item_id"], self.ITEM_ID)
        self.assertIn("id=" + self.ITEM_ID, row["view_url"])
        self.assertEqual(row["execution"], "已入库，图片已核验")


class PipelineCreatedExecutionTests(unittest.TestCase):
    """建品成功分支必须把 execution 同步为“已入库，待补图”。"""

    def test_created_branch_sets_execution(self):
        from web_fill import pipeline

        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        anchor = 'item["taobao_item_id"] = created'
        position = source.index(anchor)
        window = source[position:position + 300]
        self.assertIn('item["execution"] = "已入库，待补图"', window)
        self.assertIn("material_import.STAGE_CREATED", window)


if __name__ == "__main__":
    unittest.main()
