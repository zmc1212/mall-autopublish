# -*- coding: utf-8 -*-
"""潮玩盲盒：在已 seed 一行的发布页上执行批量导入 open→观察→verify。"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import extract_result, render_script, run_script  # noqa: E402
from openpyxl import load_workbook  # noqa: E402


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
    files = sorted((ROOT / "output" / "playwright" / "sku-import").glob("SKU导入_*.xls"))
    payload["file"] = str(files[-1].resolve())
    payload["phase"] = "open"
    print("导入文件:", Path(payload["file"]).name)

    session = CliSession()
    opened = run_script(session, "sku_import.js", payload, timeout=90)
    print("OPEN:", json.dumps(opened, ensure_ascii=False)[:300])

    probe_path = render_script("probe_import_dialog.js", {})
    for i in range(10):
        time.sleep(3)
        out = session.cmd("run-code", f"--filename={probe_path}", raw=False, timeout=30)
        r = extract_result(out)
        print(f"t+{(i+1)*3}s:", json.dumps(r, ensure_ascii=False)[:420])
        if isinstance(r, dict) and (r.get("dialogs") or r.get("tableRows")):
            pass

    payload["phase"] = "verify"
    result = run_script(session, "sku_import.js", payload, timeout=150)
    print("VERIFY:", json.dumps(result, ensure_ascii=False)[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
