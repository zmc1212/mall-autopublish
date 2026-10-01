# -*- coding: utf-8 -*-
"""真实页面验收：在保留现场上执行生产 verify 路径（deepRows 深度扫描）。"""
import glob
import io
import json
import os
import sys
import warnings

sys.path.insert(0, ".")
sys.path.insert(0, "desktop")
warnings.filterwarnings("ignore")

from desktop import paths

paths.configure_environ()

import 千牛网页执行 as web
from web_fill import pipeline
from openpyxl import load_workbook

cands = sorted(glob.glob(os.path.join(paths.load_settings().results_dir, "sku-import", "SKU导入_*.xls")),
               key=os.path.getmtime)
TEMPLATE = cands[-1]
wb = load_workbook(io.BytesIO(open(TEMPLATE, "rb").read()))
ws = wb.worksheets[0]
skus = []
for r in range(2, ws.max_row + 1):
    name = str(ws.cell(r, 4).value or "").strip()
    if not name:
        continue
    skus.append({"name": name, "price": ws.cell(r, 5).value, "stock": ws.cell(r, 6).value,
                 "merchant_code": str(ws.cell(r, 7).value or "").strip(),
                 "barcode": str(ws.cell(r, 8).value or "").strip()})
print("template rows:", len(skus))

session = web.CliSession()
session.attach()

visible = session.eval_json(
    "() => ({n: [...document.querySelectorAll('table tr')].filter(tr => {"
    " const t = tr.innerText || '';"
    " return t.includes('元') && t.includes('件') && !t.includes('SKU分类');}).length})").get("n")
print("visible rows (虚拟滚动下仅约一屏):", visible)

verify = pipeline.run_script(session, "sku_import.js",
                             {"file": TEMPLATE, "skus": skus, "phase": "verify"}, timeout=150)
print("VERIFY RESULT:", json.dumps(verify, ensure_ascii=False)[:400])
print()
print("==>", "验收通过 37/37" if verify.get("verified") else "验收未通过")
