# -*- coding: utf-8 -*-
"""真实页面验收（收尾）：复用已建商品 1088558441311，走修复后的核验与分批补规格图。

不带 force_new：prior_id + flow_stage=created 进入"只续跑补图，不重新建品"路径；
建品后核验已改为深扫描（本商品实际 37 行规格，此前是核验误报）。
"""
import io
import json
import os
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from desktop import paths

settings = paths.configure_environ()
import web_fill

session_data = json.loads(
    (Path(os.environ["APPDATA"]) / "千牛自动上架" / "job_session.json").read_text(encoding="utf-8"))
product = None
for bundle in session_data.get("products") or []:
    meta = bundle.get("meta") or {}
    if meta.get("row") == 3:
        product = dict(bundle.get("product") or {})
        meta = bundle.get("meta") or {}
        break
if product is None:
    raise SystemExit("job_session 里没有 row=3 的产品载荷")

# 复用已建商品：注入上一次运行落盘的商品 ID 与断点阶段
ITEM_ID = "1088558441311"
product["taobao_item_id"] = ITEM_ID
product["flow_stage"] = "created"
product["flow_version"] = web_fill.pipeline.SPEC_COLUMN_FLOW_VERSION
for key in ("notice", "errors", "last_error", "run_status", "duration_seconds"):
    product.pop(key, None)

sku_images = sum(1 for s in (product.get("skus") or []) if s.get("image"))
print(f"== 收尾运行: 商品 {ITEM_ID} | SKU {len(product.get('skus') or [])} 行（带图 {sku_images}）"
      f" | 策略 {settings.sku_image_strategy} | 每批 {settings.spec_upload_batch_size}", flush=True)


def ts():
    return time.strftime("%H:%M:%S")


def on_item_start(p):
    print(f"[{ts()}] 开始: {p.get('product_id')}", flush=True)


def on_item_done(p, item):
    print(f"[{ts()}] 条目结束: {item.get('execution')} | {str(item.get('notice') or '')[:200]}", flush=True)
    print(f"    item_id={item.get('taobao_item_id')} flow_stage={item.get('flow_stage')}", flush=True)


def on_flow(p, item):
    print(f"[{ts()}] flow: {item.get('flow_stage')} / spec={item.get('spec_image_stage')}", flush=True)


def on_retry(p, item, attempt, limit):
    print(f"[{ts()}] *** 自动重试 {attempt}/{limit}: {str(item.get('notice') or '')[:160]}", flush=True)


started = time.time()
updated = web_fill.run_batch(
    [product],
    confirm_submit=True,
    cancel_event=None,
    on_item_start=on_item_start,
    on_item_done=on_item_done,
    on_item_retry=on_retry,
    on_flow_stage=on_flow,
    force_new=False,
    sku_template_import=bool(settings.sku_template_import),
    skip_spec_images=bool(settings.skip_spec_images),
    sku_image_strategy=settings.sku_image_strategy,
    spec_upload_batch_size=settings.spec_upload_batch_size,
    item_retry_limit=1,
)
print(f"== run_batch 结束，总用时 {time.time() - started:.0f}s", flush=True)
ok = False
for item in updated or []:
    execution = item.get("execution")
    print(f"== 最终: {execution} | id={item.get('taobao_item_id')} | {str(item.get('notice') or '')[:200]}", flush=True)
    if str(execution).startswith("已入库"):
        ok = True
print("== 验收结论:", "通过（已入库）" if ok else "未通过", flush=True)
sys.exit(0 if ok else 2)
