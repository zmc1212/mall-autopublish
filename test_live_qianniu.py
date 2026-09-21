"""实机冒烟：连已登录的千牛 Chrome，只走类目页，不提交。"""

import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _prepare():
    os.chdir(ROOT)
    from desktop import paths
    from desktop.modules import load_web

    paths.configure_environ()
    paths.apply_to_loaded_modules()
    return load_web()


class LiveCategorySmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = _prepare()
        cls.skip_reason = ""
        if not cls.web.cdp_available():
            cls.skip_reason = "Chrome 调试端口 9222 未开"
            return
        try:
            cls.probe = cls.web.probe()
        except Exception as exc:
            cls.skip_reason = f"probe 失败: {exc}"
            return
        if not cls.probe.get("logged_in"):
            cls.skip_reason = "卖家中心未登录: " + str(cls.probe.get("url") or "")

    def setUp(self):
        if self.skip_reason:
            self.skipTest(self.skip_reason)

    def test_category_opens_search_publish_and_reaches_new_item(self):
        from web_fill import pipeline

        session = self.web.CliSession()
        session.attach()
        href = pipeline.ensure_new_category_tab(session, self.web)
        self.assertIn("category.htm", href.lower())
        payload = {
            "leaf": "中性笔",
            "brand": "卡游",
            "model": "忍道版第1弹",
        }
        result = pipeline.run_script(session, "category.js", payload, timeout=90)
        self.assertIsInstance(result, dict)
        url = str(result.get("url") or session.href())
        self.assertRegex(url, r"/sell/v2/publish\.htm")
        self.assertNotRegex(url.lower(), r"itemid=|edit\.htm")
        self.assertIn("中性笔", result.get("leaf") or "")
        out = Path(os.environ["QIANNIU_OUTPUT_DIR"]) / "live_category_smoke.json"
        out.write_text(json.dumps({"href": url, "result": result}, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_fill_attributes_and_warehouse_without_submit(self):
        from web_fill import pipeline

        product = {
            "row": 99,
            "product_id": "live-smoke",
            "title": "卡游火影忍者中性笔自动化冒烟",
            "brand": "卡游",
            "model": "忍道版第1弹",
            "category": "文具用品/文化用品/商务用品>>笔类/书写工具>>中性笔",
            "attributes": {
                "笔头类型": "子弹头",
                "笔芯颜色": "炭黑",
                "闭合方式": "按动式",
                "风格": "简约",
                "功能": "考试专用",
                "适用场景": "日常书写",
                "适用人群": "通用",
                "包装方式": "单支装",
                "采购地": "中国内地（大陆）",
                "品牌": "卡游",
                "型号": "忍道版第1弹",
            },
            "skus": [],
            "main_images": [],
            "detail_images": [],
            "thickness": "0.05mm",
            "ship_time": "48小时内发货",
            "freight": "文具用品 包邮",
            "stock_deduction": "拍下减库存",
        }
        session = self.web.CliSession()
        result = pipeline.fill_new_product(session, product, confirm_submit=False, web=self.web)
        steps = [item.get("step") for item in (result.get("steps") or [])]
        Path(os.environ["QIANNIU_OUTPUT_DIR"]).joinpath("live_fill_smoke.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        self.assertIn("category", steps)
        self.assertIn("attributes", steps)
        self.assertIn("logistics", steps)
        attr = next((item.get("result") or {} for item in (result.get("steps") or []) if item.get("step") == "attributes"), {})
        self.assertEqual(attr.get("missing") or [], [])
        self.assertNotEqual(result.get("execution"), "失败")
        self.assertNotEqual(result.get("execution"), "暂停")
        self.assertIn(result.get("execution"), ("已填写未提交", "结果待核实"))
        self.assertNotIn("submit.js", str(result.get("steps")))


if __name__ == "__main__":
    unittest.main()
