# -*- coding: utf-8 -*-
"""用深扫描审计核对已建商品的真实 SKU 行数（虚拟滚动全量，非可视区）。"""
import io
import json
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from desktop import paths

paths.configure_environ()
import web_fill

pipeline = web_fill.pipeline
web = pipeline._load_web()

session_data = json.loads(
    (Path(os.environ["APPDATA"]) / "千牛自动上架" / "job_session.json").read_text(encoding="utf-8"))
skus = None
for bundle in session_data.get("products") or []:
    if (bundle.get("meta") or {}).get("row") == 3:
        skus = (bundle.get("product") or {}).get("skus") or []
        break
if skus is None:
    raise SystemExit("没有 row3 载荷")

item_id = sys.argv[1] if len(sys.argv) > 1 else "1088558441311"
session = web.CliSession()
try:
    session.attach()
    pipeline._open_item_edit_tab(session, item_id)
    result = pipeline.run_script(session, "sku_import.js", {"phase": "audit", "skus": skus}, timeout=120)
    print("商品", item_id, "深扫描审计结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
finally:
    try:
        session.detach()
    except Exception:
        pass
