# -*- coding: utf-8 -*-
"""诊断：对比第 3 行输入 SKU 与已建商品实际 SKU（会话文件 vs 11:31 probe 结果）。"""
import json
import os
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

session_path = Path(os.environ["APPDATA"]) / "千牛自动上架" / "job_session.json"
data = json.loads(session_path.read_text(encoding="utf-8"))

# 输入端：products 里 row=3 的 product.skus
input_skus = None
meta_row3 = None
for bundle in data.get("products") or []:
    meta = bundle.get("meta") or {}
    if meta.get("row") == 3:
        meta_row3 = meta
        input_skus = (bundle.get("product") or {}).get("skus") or []
        break

if input_skus is None:
    print("products 未找到 row3，顶层 keys:", list(data.keys()))
else:
    print("=== 输入（Excel 第 3 行）SKU:", len(input_skus), "行 ===")
    for s in input_skus:
        print("  ", s.get("name"), "| 价:", s.get("price"), "| 库:", s.get("stock"))

if meta_row3:
    print("\n=== 会话记录的执行状态 ===")
    for k in ("execution", "notice", "flow_stage", "run_status", "taobao_item_id"):
        print(f"  {k} =", str(meta_row3.get(k))[:120])
    errs = meta_row3.get("errors") or []
    for e in errs:
        print("  error:", str(e)[:160])

# 已建商品实际 SKU（来自 11:31 probe_state）
probe_path = Path(os.environ["APPDATA"]) / "千牛自动上架" / "logs" / "playwright" / "web_fill_probe_state.json"
probe = json.loads(probe_path.read_text(encoding="utf-8"))
product_names = probe.get("skuNames") or []
print("\n=== 已建商品 1089583476155 实际 SKU:", len(product_names), "行 ===")
for n in product_names:
    print("  ", n)

if input_skus is not None:
    in_names = [str(s.get("name") or "").strip() for s in input_skus]
    missing = [n for n in in_names if n not in product_names]
    extra = [n for n in product_names if n not in in_names]
    print("\n=== 差异 ===")
    print("输入有而商品没有:", len(missing))
    for n in missing[:20]:
        print("  -", n)
    print("商品有而输入没有:", len(extra))
    for n in extra[:20]:
        print("  +", n)
