"""离线并发验收分析器的证据边界回归测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from tools.analyze_concurrent_live import analyze_events, analyze_item, analyze_run


def _product(row: int, product_id: str | None = None) -> dict:
    name_one = "忍道版1弹【特别款】1支"
    name_two = "【忍道版1弹】1小支"
    return {
        "row": row,
        "product_id": product_id or f"item-{row}",
        "title": f"并发验收-{row}",
        "skus": [
            {"name": name_one, "sku_id": f"sku-{row}-1", "price": "9.90", "stock": "20",
             "search_title": "-", "attributes_text": "书写粗细: 0.05mm"},
            {"name": name_two, "sku_id": f"sku-{row}-2", "price": "9.90", "stock": "20",
             "search_title": "-", "attributes_text": "书写粗细: 0.05mm"},
        ],
    }


def _event(kind: str, row: int, product_id: str, at: float, worker: int,
           phase: str | None = None, **extra: object) -> dict:
    value = {"event": kind, "row": row, "product_id": product_id,
             "at": at, "worker_id": worker}
    if phase is not None:
        value["phase"] = phase
    value.update(extra)
    return value


class ConcurrentLiveAnalyzerTests(unittest.TestCase):
    def test_missing_probes_are_unknown_instead_of_observed_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_item(_product(1), Path(directory))
        self.assertEqual(result["sales_spec_images"]["presence"], "无法判断")
        self.assertEqual(result["non_image_fields"]["status"], "无法判断")
        self.assertNotIn("warehouse", result["non_image_fields"]["verified"])
        self.assertEqual(result["non_image_fields"]["differences"], [])

    def test_paused_probes_preserve_material_evidence_and_preview_boundary(self) -> None:
        product = _product(2)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "web_fill_probe_state.json").write_text(json.dumps({
                "title": product["title"],
                "warehouse": [{"checked": True, "t": "放入仓库"}],
                "freight": True,
                "ship48": True,
                "skuRows": 2,
                "skuNames": [sku["name"] for sku in product["skus"]],
            }, ensure_ascii=False), encoding="utf-8")
            (output / "web_fill_spec_row_status.json").write_text(json.dumps({
                "total": 2,
                "filled": 2,
                "missing": [],
                "sources": [{"index": 1, "src": "//img.example/1.jpg"},
                            {"index": 2, "src": "//img.example/2.jpg"}],
            }), encoding="utf-8")
            (output / "web_fill_material_import.json").write_text(json.dumps({
                "rows": [
                    {"name": product["skus"][0]["name"], "sku_id": "sku-1", "price": "9.90",
                     "stock": "20", "search_title": "-", "attributes_text": "-", "image": "img-1"},
                    {"name": product["skus"][1]["name"], "sku_id": "sku-2", "price": "9.90",
                     "stock": "20", "search_title": "-", "attributes_text": "-", "image": "img-2"},
                ],
            }, ensure_ascii=False), encoding="utf-8")

            result = analyze_item(product, output, report_item={
                "sku_material_manifest": product["skus"],
                "material_result": [],
                "material_preview": [],
            })

        self.assertEqual(len(result["sku_material_manifest"]), 2)
        self.assertEqual(result["material_result"], [])
        self.assertEqual(len(result["material_preview"]), 2)
        self.assertEqual(result["sales_spec_images"]["status"], "无法判断")
        self.assertEqual(result["sales_spec_images"]["presence"], "通过")
        self.assertEqual(result["sales_spec_images"]["identity_status"], "无法判断")
        self.assertEqual(result["search_main_images"]["identity"], "preview_not_adopted")
        self.assertEqual(result["search_main_images"]["preview_presence"], "通过")
        self.assertEqual(result["non_image_fields"]["status"], "无法判断")
        self.assertIn("attributes_text", result["non_image_fields"]["missing"])
        self.assertEqual(result["non_image_fields"]["server_differences"], [])
        self.assertTrue(all(item["server_state"] == "无法判断"
                            for item in result["non_image_fields"]["preview_differences"]))
        self.assertTrue(any("acceptance-server-evidence.json" in error
                            for error in result["evidence_errors"]))

    def test_slot_overlap_does_not_claim_business_overlap_without_progress_intersection(self) -> None:
        expected = {(1, "one"): _product(1, "one"), (2, "two"): _product(2, "two")}
        events = [
            _event("start", 1, "one", 0, 1),
            _event("start", 2, "two", 0.5, 2),
            _event("progress", 1, "one", 1, 1, "填写"),
            _event("progress", 1, "one", 2, 1, "上传"),
            _event("progress", 2, "two", 8, 2, "填写"),
            _event("progress", 2, "two", 9, 2, "上传"),
            _event("done", 1, "one", 10, 1, status="completed"),
            _event("done", 2, "two", 10, 2, status="completed"),
        ]

        result = analyze_events(events, expected, concurrency=2)

        self.assertTrue(result["valid_pairing"])
        self.assertGreater(result["slot_occupancy_overlap_seconds"], 0)
        self.assertTrue(result["slot_occupancy_overlap"])
        self.assertEqual(result["progress_overlap_seconds"], 0)
        self.assertFalse(result["progress_overlap"])
        self.assertFalse(result["business_overlap"])

    def test_progress_intersection_is_the_business_overlap_metric(self) -> None:
        expected = {(1, "one"): _product(1, "one"), (2, "two"): _product(2, "two")}
        events = [
            _event("start", 1, "one", 0, 1),
            _event("start", 2, "two", 0.5, 2),
            _event("progress", 1, "one", 1, 1, "填写"),
            _event("progress", 1, "one", 4, 1, "上传"),
            _event("progress", 2, "two", 3, 2, "填写"),
            _event("progress", 2, "two", 6, 2, "上传"),
            _event("done", 1, "one", 7, 1, status="completed"),
            _event("done", 2, "two", 8, 2, status="completed"),
        ]

        result = analyze_events(events, expected, concurrency=2)

        self.assertEqual(result["progress_overlap_seconds"], 1.0)
        self.assertTrue(result["progress_overlap"])
        self.assertEqual(result["business_overlap_seconds"], 1.0)

    def test_completed_lifecycle_without_correctness_evidence_stays_needs_review(self) -> None:
        products = [_product(index) for index in range(1, 4)]
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "inputs.json").write_text(json.dumps(products, ensure_ascii=False), encoding="utf-8")
            def result_item(product: dict) -> dict:
                return {"row": product["row"], "product_id": product["product_id"],
                        "execution": "已入库", "run_status": "completed"}

            report = {"status": "completed", "batches": [
                {"concurrency": 1, "results": [result_item(products[0])]},
                {"concurrency": 2, "results": [result_item(products[1]), result_item(products[2])]},
            ]}
            (run / "report.json").write_text(json.dumps(report), encoding="utf-8")
            one = products[0]
            (run / "events-1.json").write_text(json.dumps([
                _event("start", one["row"], one["product_id"], 0, 1),
                _event("progress", one["row"], one["product_id"], 1, 1, "填写"),
                _event("progress", one["row"], one["product_id"], 2, 1, "上传"),
                _event("done", one["row"], one["product_id"], 3, 1, status="completed"),
            ]), encoding="utf-8")
            two, three = products[1:]
            (run / "events-2.json").write_text(json.dumps([
                _event("start", two["row"], two["product_id"], 0, 1),
                _event("start", three["row"], three["product_id"], 0.5, 2),
                _event("progress", two["row"], two["product_id"], 1, 1, "填写"),
                _event("progress", two["row"], two["product_id"], 4, 1, "上传"),
                _event("progress", three["row"], three["product_id"], 2, 2, "填写"),
                _event("progress", three["row"], three["product_id"], 5, 2, "上传"),
                _event("done", two["row"], two["product_id"], 6, 1, status="completed"),
                _event("done", three["row"], three["product_id"], 7, 2, status="completed"),
            ]), encoding="utf-8")

            result = analyze_run(run)

        self.assertTrue(result["batches"][1]["event_analysis"]["latest_all_completed"])
        self.assertTrue(result["batches"][1]["event_analysis"]["progress_overlap"])
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["correctness_basis"]["ready"])
        self.assertTrue(result["correctness_basis"]["unverified_items"])


if __name__ == "__main__":
    unittest.main()
