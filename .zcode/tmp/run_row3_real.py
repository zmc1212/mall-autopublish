# -*- coding: utf-8 -*-
"""真实页面验收：用项目 pipeline + 已授权 Chrome 会话跑通第 3 行数据。

与桌面端行为一致：模板导入 SKU、publish_page 策略（入库后分批补规格图）、
条目失败自动重试 1 次。force_new 强制全新建品，不复用失败残留页面。
产物与日志写入项目 output/playwright，结果实时打印供监控。
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
        break
if product is None:
    raise SystemExit("job_session 里没有 row=3 的产品载荷")

# 剥离执行状态字段，保证走全新建品路径（上一次失败发生在建品前，无商品 ID）
STRIP = ("execution", "notice", "errors", "last_error", "flow_stage", "flow_version",
         "taobao_item_id", "view_url", "edit_url", "run_status", "spec_image_stage",
         "sku_material_manifest", "material_result", "material_preview", "material_folder",
         "duration_seconds", "validation")
for key in STRIP:
    product.pop(key, None)

sku_images = sum(1 for s in (product.get("skus") or []) if s.get("image"))
print(f"== 载荷: {product.get('title')} | SKU {len(product.get('skus') or [])} 行"
      f"（带图 {sku_images}）| 主图 {len(product.get('main_images') or [])}"
      f" | 详情图 {len(product.get('detail_images') or [])}"
      f" | 策略 {settings.sku_image_strategy} | 模板导入 {settings.sku_template_import}"
      f" | 规格图每批 {settings.spec_upload_batch_size} | 重试上限 1", flush=True)


def ts():
    return time.strftime("%H:%M:%S")


def on_item_start(p):
    print(f"[{ts()}] 开始: {p.get('product_id')}", flush=True)


def on_item_done(p, item):
    print(f"[{ts()}] 条目结束: {item.get('execution')} | {str(item.get('notice') or '')[:200]}", flush=True)
    print(f"    item_id={item.get('taobao_item_id')} flow_stage={item.get('flow_stage')}", flush=True)


def on_flow(p, item):
    print(f"[{ts()}] flow_stage -> {item.get('flow_stage')}", flush=True)


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
    force_new=True,
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
