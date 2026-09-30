"""入库后官方 SKU 搜索主图素材导入的内部服务。

供 web_fill.pipeline 的批任务主链路调用；不含 CLI、命令行参数或独立进度文件。
原 CLI 原型 material_flow.py 复用这里的实现，仅保留开发调试入口。

已验证的目标字段是「SKU 搜索主图」。是否同步为商品详情页销售规格图尚未核实，
因此所有文案必须使用「SKU 搜索主图」，不得宣称销售规格图已补齐。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from decimal import Decimal
from pathlib import Path

from . import pipeline

SKU_URL = "https://myseller.taobao.com/home.htm/SellManage/all_skucenter?from=qn_entry&current=1&pageSize=10"

FLOW_VERSION = 1
STRATEGY_SLIM = "slim_material"
STRATEGY_PUBLISH = "publish_page"
STRATEGIES = (STRATEGY_SLIM, STRATEGY_PUBLISH)

# 阶段与计划 6.1 对齐。UI 文案由 desktop/jobs.py 映射。
STAGE_FILLED = "filled"
STAGE_SUBMIT_PENDING = "submit_pending"
STAGE_CREATED = "created"
STAGE_PREPARED = "material_prepared"
STAGE_UPLOAD_PENDING = "material_upload_pending"
STAGE_RECOGNIZING = "material_recognizing"
STAGE_REVIEWED = "material_reviewed"
STAGE_ADOPT_PENDING = "material_adopt_pending"
STAGE_VERIFYING = "material_verifying"
STAGE_COMPLETE = "complete"

_RECOVERABLE_STAGES = {
    STAGE_FILLED,
    STAGE_SUBMIT_PENDING,
    STAGE_CREATED,
    STAGE_PREPARED,
    STAGE_UPLOAD_PENDING,
    STAGE_RECOGNIZING,
    STAGE_REVIEWED,
    STAGE_ADOPT_PENDING,
    STAGE_VERIFYING,
    STAGE_COMPLETE,
}

# 旧原型进度文件的阶段名迁移：new→filled 表示尚未创建商品；ready 等映射到新阶段。
_LEGACY_STAGE_MAP = {
    "new": STAGE_FILLED,
    "ready": STAGE_PREPARED,
    "upload_pending": STAGE_UPLOAD_PENDING,
    "preview": STAGE_REVIEWED,
    "adopt_pending": STAGE_ADOPT_PENDING,
    "verifying": STAGE_VERIFYING,
}

_UNSAFE_NAME = re.compile(r'[<>:"/\|?*\x00-\x1f]')
_DEVICE_NAME = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:.|$)", re.I)
_ITEM_ID = re.compile(r"\d{8,20}")
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def normalize_stage(value):
    stage = str(value or "").strip()
    if stage in _RECOVERABLE_STAGES:
        return stage
    return _LEGACY_STAGE_MAP.get(stage, STAGE_FILLED)


def validate_materials(product):
    """本地预检：标题、SKU 名称、图片、价格库存。返回参与指纹的文件列表。"""
    if not product.get("title") or not product.get("skus"):
        raise ValueError("需要商品标题和完整 SKU 列表")
    seen = set()
    files = []
    for sku in product["skus"]:
        name = str(sku.get("name") or "")
        if (
            not name
            or name != name.strip()
            or name.endswith(".")
            or len(name) > 100
            or _UNSAFE_NAME.search(name)
            or _DEVICE_NAME.match(name)
        ):
            raise ValueError(f"SKU 名称不能原样用作文件名，请先修正：{name!r}")
        if name.casefold() in seen:
            raise ValueError(f"SKU 名称重复或文件名冲突：{name}")
        seen.add(name.casefold())
        image = Path(sku.get("image") or "")
        if not image.is_file() or image.suffix.lower() not in _IMAGE_EXTS:
            raise ValueError(f"SKU 图片不存在或格式不支持：{name}: {image}")
        price, stock = Decimal(str(sku.get("price"))), Decimal(str(sku.get("stock")))
        if (
            not price.is_finite()
            or price <= 0
            or not stock.is_finite()
            or stock < 0
            or stock != int(stock)
        ):
            raise ValueError(f"SKU 价格或库存无效：{name}")
        files.append(image)
    for key in ("main_images", "portrait_images", "detail_images"):
        for value in product.get(key, []):
            image = Path(value)
            if not image.is_file():
                raise ValueError(f"图片不存在：{image}")
            files.append(image)
    return files


def fingerprint(product):
    digest = hashlib.sha256(json.dumps(product, ensure_ascii=False, sort_keys=True, default=str).encode())
    for path in validate_materials(product):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _safe_folder_key(value):
    text = re.sub(r'[<>:"/\|?*\x00-\x1f]', "_", str(value or "product").strip())
    text = text.rstrip(". ")
    return text[:80] or "product"


def material_root(base=None, product_key=""):
    base = Path(base) if base else pipeline.get_output() / "material_flow"
    return base / _safe_folder_key(product_key)


def build_material_folder(product, item_id, directory, product_key=""):
    """按后台 SKU 顺序生成编号素材目录，返回绝对路径。"""
    if not _ITEM_ID.fullmatch(str(item_id)):
        raise ValueError("商品 ID 无效")
    validate_materials(product)
    root = Path(directory).resolve()
    key_dir = root / _safe_folder_key(product_key) if product_key else root
    folder = key_dir / str(item_id)
    expected = {
        f"{index:04d}_{sku['name']}{Path(sku['image']).suffix.lower()}"
        for index, sku in enumerate(product["skus"], 1)
    }
    if folder.exists() and any(p.name not in expected or not p.is_file() for p in folder.iterdir()):
        raise ValueError("素材文件夹有额外内容，停止以免上传其他数据")
    folder.mkdir(parents=True, exist_ok=True)
    for index, sku in enumerate(product["skus"], 1):
        shutil.copyfile(
            sku["image"],
            folder / f"{index:04d}_{sku['name']}{Path(sku['image']).suffix.lower()}",
        )
    return folder.resolve()


def check_rows(rows, product, baseline=None, images=False):
    """核对后台/确认页 SKU 行与输入商品：行数、名称、ID、价格库存、搜索标题与图片。"""
    expected = {sku["name"]: sku for sku in product["skus"]}
    if len(rows) != len(expected) or {r["name"] for r in rows} != set(expected):
        raise RuntimeError("PAUSE:SKU 行数或名称与输入不一致")
    ids = [row.get("sku_id", "") for row in rows]
    if any(not _ITEM_ID.fullmatch(value) for value in ids) or len(set(ids)) != len(ids):
        raise RuntimeError("PAUSE:SKU ID 缺失或重复")
    previous = {row["name"]: row for row in baseline or []}
    for row in rows:
        source = previous.get(row["name"], expected[row["name"]])
        if Decimal(str(row["price"])) != Decimal(str(source["price"])) or Decimal(str(row["stock"])) != Decimal(str(source["stock"])):
            raise RuntimeError(f"PAUSE:{row['name']} 的价格或库存发生变化")
        if previous and row["sku_id"] != source["sku_id"]:
            raise RuntimeError("PAUSE:识别到了其他商品的 SKU")
        if images and not row.get("image"):
            raise RuntimeError(f"PAUSE:{row['name']} 未匹配搜索主图")
        if previous and row.get("search_title", "") != source.get("search_title", ""):
            raise RuntimeError("PAUSE:素材识别还改变了搜索标题，需人工核对")
        for field in ("attributes_text", "merchant_code"):
            if previous and field in source and row.get(field) != source[field]:
                raise RuntimeError("PAUSE:素材识别改变了属性或商家编码，需人工核对")


def item_id_from_result(result):
    from urllib.parse import parse_qs, urlparse

    result = result or {}
    if result.get("execution") in {"失败", "暂停", "提交失败"}:
        return ""
    value = str(result.get("taobao_item_id") or "")
    if _ITEM_ID.fullmatch(value):
        return value
    url = urlparse(result.get("url", ""))
    if url.hostname == "item.upload.taobao.com" and url.path.endswith("/success.htm"):
        value = parse_qs(url.query).get("primaryId", [""])[0]
        if _ITEM_ID.fullmatch(value):
            return value
    return ""


def _script(session, web, item_id, title, phase, **extra):
    return pipeline.run_script(
        session,
        "material_import.js",
        {"phase": phase, "item_id": item_id, "title": title, **extra},
        timeout=50,
    )


def ensure_sku_tab(session):
    """打开或复用官方 SKU 管理页标签；不依赖当前选中行。"""
    prefix = SKU_URL.split("?")[0]
    tabs = pipeline.parse_tabs(session.tab_list())
    found = next((index for index, url in tabs if url.startswith(prefix)), None)
    if found is None:
        session.tab_new(SKU_URL)
    else:
        session.tab_select(found)


def inspect_target_skus(session, web, item_id, title):
    """按商品 ID 定位并读取后台 SKU ID、名称、顺序与基线字段。"""
    ensure_sku_tab(session)
    baseline = _script(session, web, item_id, title, "baseline")
    return baseline.get("rows") or []


def upload_materials(session, web, item_id, title, folder, baseline):
    ensure_sku_tab(session)
    _script(session, web, item_id, title, "upload", folder=str(folder), baseline=baseline)


def await_recognition(session, web, item_id, title, product, baseline, timeout=180):
    """有限等待素材识别；识别完成前轮询确认页，返回核对后的预览行。"""
    ensure_sku_tab(session)
    deadline = time.monotonic() + timeout
    while True:
        pipeline._check_cancel(session)
        preview = _script(session, web, item_id, title, "preview", baseline=baseline)
        if preview.get("ready"):
            rows = preview.get("rows") or []
            check_rows(rows, product, baseline, images=True)
            return rows
        if time.monotonic() >= deadline:
            raise RuntimeError("PAUSE:素材识别未完成；保留页面和进度，继续任务可接着等待")
        time.sleep(3)


def review_materials(session, web, item_id, title, baseline, preview):
    """采纳前再次核对确认页并执行采纳。"""
    ensure_sku_tab(session)
    current = _script(session, web, item_id, title, "preview", baseline=baseline)
    if not current.get("ready") or (current.get("rows") or []) != preview:
        raise RuntimeError("PAUSE:素材确认页面已变化，请核对")
    _script(session, web, item_id, title, "adopt", baseline=baseline, preview=preview)


def verify_materials(session, web, item_id, title, product, baseline, preview):
    """采纳后刷新并按 SKU ID 逐行核验图片持久化。"""
    ensure_sku_tab(session)
    verified = _script(session, web, item_id, title, "verify", baseline=baseline, preview=preview)
    rows = verified.get("rows") or []
    check_rows(rows, product, baseline, images=True)
    return rows


def run_material_flow(session, web, product, item_id, state, on_stage=None, recognize_timeout=180):
    """按 state 中的 stage 续跑素材导入；state 由调用方负责持久化。

    返回 state。on_stage(stage, **values) 在每次阶段迁移时被调用，便于调用方立即落盘。
    """
    state = dict(state or {})
    stage = normalize_stage(state.get("stage"))
    baseline = list(state.get("baseline") or [])
    preview = list(state.get("preview") or [])
    title = str(product.get("title") or "")

    def move(next_stage, **values):
        nonlocal stage, baseline, preview
        stage = next_stage
        state.update(values, stage=next_stage)
        state.pop("error", None)
        if on_stage:
            on_stage(next_stage, state)

    try:
        if stage == STAGE_COMPLETE:
            return state
        if not _ITEM_ID.fullmatch(str(item_id)):
            raise ValueError("商品 ID 无效，无法定位商品补图")

        if stage == STAGE_CREATED:
            rows = inspect_target_skus(session, web, item_id, title)
            check_rows(rows, product)
            by_name = {sku["name"]: sku for sku in product["skus"]}
            ordered = {**product, "skus": [by_name[row["name"]] for row in rows]}
            root = material_root(state.get("material_root"), state.get("product_key") or "")
            folder = build_material_folder(ordered, item_id, root, state.get("product_key") or "")
            baseline = rows
            move(STAGE_PREPARED, baseline=rows, folder=str(folder))

        if stage == STAGE_PREPARED:
            folder = state.get("folder")
            if not folder or not Path(folder).is_dir():
                raise RuntimeError("PAUSE:素材目录缺失，重新生成前请核对原任务")
            move(STAGE_UPLOAD_PENDING)
            upload_materials(session, web, item_id, title, folder, baseline)

        if stage in {STAGE_UPLOAD_PENDING, STAGE_RECOGNIZING}:
            move(STAGE_RECOGNIZING)
            preview = await_recognition(session, web, item_id, title, product, baseline, recognize_timeout)
            move(STAGE_REVIEWED, preview=preview)

        if stage == STAGE_REVIEWED:
            move(STAGE_ADOPT_PENDING)
            review_materials(session, web, item_id, title, baseline, preview)

        if stage in {STAGE_ADOPT_PENDING, STAGE_VERIFYING}:
            move(STAGE_VERIFYING)
            verified = verify_materials(session, web, item_id, title, product, baseline, preview)
            move(STAGE_COMPLETE, verified=verified, notice="SKU 搜索主图已采纳并复核")

        return state
    except Exception as exc:
        state["error"] = str(exc)
        if on_stage:
            on_stage(stage, state)
        raise
