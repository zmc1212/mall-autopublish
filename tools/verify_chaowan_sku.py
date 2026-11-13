# -*- coding: utf-8 -*-
"""分步验收潮玩盲盒 SKU 批量导入（真实页面，聚焦卡点，窗口最小化）。

前置：已授权会话（9222）。脚本会新开类目标签进入潮玩盲盒发布页，
执行 import_skus_from_template（模板生成→批量导入→确认识别→行核对），
并在完成后输出 SKU 表格快照供人工复核。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill import pipeline, sku_import  # noqa: E402
from openpyxl import load_workbook  # noqa: E402


def build_payload():
    import 千牛自动上架 as seller

    root = ROOT / "testdata" / "潮玩盲盒测试工作空间"
    wb = load_workbook(root / "商品清单.xlsx")
    ws = wb["商品清单"]
    rows = list(ws.iter_rows(values_only=True))
    headers = [str(c or "").strip() for c in rows[0]]
    data = dict(zip(headers, rows[1]))
    product = seller.row_to_product(data, root, sku_rows=[])
    return pipeline.product_to_payload(product)


def main() -> int:
    from 千牛网页执行 import CliSession  # noqa: E402

    payload = build_payload()
    assert sku_import.supports_product(payload), "payload 未命中潮玩盲盒 SKU 模板"
    print("payload:", payload["category_id"], payload["spec_name"],
          [s["name"] for s in payload["skus"]])

    session = CliSession()
    web = pipeline._load_web()
    href = pipeline.ensure_new_category_tab(session, web)
    print("category tab:", href[:90])

    steps = []
    category = pipeline.run_gate(session, "category.js", payload, steps, "category", timeout=90)
    print("category:", json.dumps(category, ensure_ascii=False)[:260])
    web.assert_safe_url(session.href())
    assert web.is_publish_page(session.href()), "未进入发布页: " + session.href()

    pipeline.import_skus_from_template(session, payload, steps)
    for step in steps:
        print("step:", json.dumps(step, ensure_ascii=False)[:400])

    # 导入后核对：probe_state 读 SKU 表格行
    probe = pipeline.run_script(session, "probe_state.js", {}, timeout=60)
    print("probe:", json.dumps(probe, ensure_ascii=False)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
