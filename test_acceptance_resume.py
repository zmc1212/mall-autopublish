import tempfile
import unittest
from pathlib import Path

from tools import verify_concurrent_live as acceptance


class AcceptanceResumeTests(unittest.TestCase):
    def test_restore_keeps_identity_pending_submit_and_skips_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            products = [{"row": i, "product_id": str(i), "title": f"测试{i}"} for i in (1, 2, 3)]
            acceptance.write_json(root / "inputs.json", products)
            acceptance.write_json(root / "report.json", {"batches": [{"results": [
                {**products[0], "run_status": "completed", "taobao_item_id": "123456789"},
                {**products[1], "run_status": "paused", "flow_stage": "submit_pending", "url": "https://example.test/publish"},
            ]}]})
            acceptance.write_json(root / "state" / "job_session.json", {"workbook_path": "original.xlsx", "rows": products})
            before = (root / "report.json").read_bytes()
            context = acceptance._resume_context(root)
            groups = acceptance._resume_groups(context["products"], context["completed"])
            self.assertEqual([(n, [p["row"] for p in rows]) for n, rows in groups], [(2, [2, 3])])
            self.assertEqual(groups[0][1][0]["flow_stage"], "submit_pending")
            self.assertEqual(groups[0][1][0]["title"], "测试2")
            self.assertEqual(context["workbook_path"], "original.xlsx")
            target, _ = acceptance._prepare_attempt(root, resume=True, attempt_id="resume-1", context=context)
            acceptance.write_json(target / "report.json", {"batches": [], "status": "needs_review"})
            acceptance._write_report_latest(root, {"status": "needs_review", "attempt_id": "resume-1"})
            self.assertEqual((root / "report.json").read_bytes(), before)
            self.assertEqual((target / "source-report.json").read_bytes(), before)
            self.assertTrue((root / "report-latest.json").is_file())

    def test_incomplete_resume_directory_fails_before_creating_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises((OSError, ValueError)):
                acceptance._resume_context(root)
            self.assertFalse((root / "attempts").exists())


if __name__ == "__main__":
    unittest.main()
