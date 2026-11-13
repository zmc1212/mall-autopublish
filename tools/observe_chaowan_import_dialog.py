# -*- coding: utf-8 -*-
"""分步观察潮玩盲盒“批量导入”弹窗结构：open 阶段后逐秒采样弹窗文本。"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import extract_result, render_script, run_script  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

PROBE_SRC = """
async page => {
  /*PAYLOAD*/
  /*HELPERS*/
  const sample = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dialogs = [...document.querySelectorAll(".next-dialog, [role=dialog], .next-overlay-wrapper")].filter(visible)
      .map((el) => (el.innerText||"").replace(/\\s+/g," ").trim().slice(0,500));
    const fileInputs = [...document.querySelectorAll("input[type=file]")].map((el) => ({accept: String(el.accept||""), visible: visible(el)}));
    const tableRows = [...document.querySelectorAll("table tr")].filter((tr)=>/元|件/.test(tr.innerText||"")).length;
    return { dialogs, fileInputs, tableRows };
  });
  return JSON.stringify(sample);
}
"""


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
    payload["file"] = str((ROOT / "output" / "playwright" / "sku-import" / "SKU导入_b0e51ad19607423a99f637f411184717.xls").resolve())
    payload["phase"] = "open"

    session = CliSession()
    open_result = run_script(session, "sku_import.js", payload, timeout=90)
    print("OPEN:", json.dumps(open_result, ensure_ascii=False)[:400])

    probe_path = render_script("probe_import_dialog.js", {})
    for i in range(14):
        time.sleep(3)
        out = session.cmd("run-code", f"--filename={probe_path}", raw=False, timeout=30)
        r = extract_result(out)
        print(f"t+{(i+1)*3}s:", json.dumps(r, ensure_ascii=False)[:450])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
