# -*- coding: utf-8 -*-
"""filechooser 方式批量导入实验：seed 一行规格 → 打开弹窗 → 真实文件选择
对话框方式上传卖家原版模板 → 抓上传网络与确认识别请求/响应。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import extract_result, render_script, run_script  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

TEMPLATE = ROOT / "testdata" / "SKU模板_潮玩盲盒.xls"


def build_payload():
    import 千牛自动上架 as seller  # noqa: E402
    from web_fill.pipeline import product_to_payload  # noqa: E402

    root = ROOT / "testdata" / "潮玩盲盒测试工作空间"
    wb = load_workbook(root / "商品清单.xlsx")
    rows = list(wb["商品清单"].iter_rows(values_only=True))
    headers = [str(c or "").strip() for c in rows[0]]
    data = dict(zip(headers, rows[1]))
    product = seller.row_to_product(data, root, sku_rows=[])
    return product_to_payload(product)


def main() -> int:
    from 千牛网页执行 import CliSession  # noqa: E402

    payload = build_payload()
    session = CliSession()
    web = pipeline_web = __import__("web_fill.pipeline", fromlist=["_load_web"])._load_web()

    href = __import__("web_fill.pipeline", fromlist=["ensure_new_category_tab"]).ensure_new_category_tab(session, web)
    print("category tab:", href[:80])
    steps = []
    category = run_script(session, "category.js", payload, timeout=90)
    print("category:", json.dumps(category, ensure_ascii=False)[:160])

    # seed 一行规格（批量导入按钮需至少一行规格值才启用）
    seed = {**payload, "skus": payload["skus"][:1]}
    seed_result = run_script(session, "skus.js", seed, timeout=300)
    print("SEED:", json.dumps({k: seed_result.get(k) for k in ("opened", "log", "filled")}, ensure_ascii=False)[:220])

    try:
        run_script(session, "close_import_dialog.js", {}, timeout=30)
    except Exception:
        pass

    experiment = {**payload, "file": str(TEMPLATE), "skus": payload["skus"][:2]}
    path = render_script("filechooser_upload.js", experiment)
    out = session.cmd("run-code", f"--filename={path}", raw=False, timeout=180)
    r = extract_result(out)
    if isinstance(r, dict):
        print("OPEN:", json.dumps(r.get("opened"), ensure_ascii=False))
        print("DROP:", json.dumps(r.get("dropInfo"), ensure_ascii=False))
        print("CHOOSER:", json.dumps(r.get("chooserState"), ensure_ascii=False))
        print("AFTER_UPLOAD:", json.dumps(r.get("afterUpload"), ensure_ascii=False)[:450])
        rec = r.get("recognized") or {}
        print("RECOGNIZE.status:", rec.get("status"), "clicked:", rec.get("clicked"))
        print("RECOGNIZE.body:", str(rec.get("body"))[:400])
        print("RECOGNIZE.post:", str(rec.get("post"))[:900])
        for i, s in enumerate(r.get("samples", [])):
            print(f"t+{(i+1)*3}s:", json.dumps(s, ensure_ascii=False)[:240])
        print("NET:", json.dumps(r.get("net"), ensure_ascii=False, indent=1)[:900])
    else:
        print(str(r)[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
