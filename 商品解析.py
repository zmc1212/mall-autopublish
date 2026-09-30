"""图片包扫描、分类模板加载、商品行解析。可供 CLI 与日后桌面端共用。"""

import json
import os
import re
from pathlib import Path


def get_templates_dir():
    override = os.environ.get("QIANNIU_TEMPLATES_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "templates"


def reload_paths():
    global TEMPLATES_DIR
    TEMPLATES_DIR = get_templates_dir()


TEMPLATES_DIR = get_templates_dir()
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".wmv", ".flv", ".3gp", ".mkv", ".webm"}
PORTRAIT_NAME = re.compile(r"3比4|3-4")
# 兼容常见的“方图主图NN”命名。文件名只是提示，最终仍结合像素比例判断
# “宝贝主图NN”到底是 1:1 还是 3:4，避免把竖图误当成正方形主图。
MAIN_NAME = re.compile(r"^(?:(?:宝贝|方图)?主图)(\d+)")
# 图片包可能同时带“宝贝主图”和“方图主图”两套备选主图。分组排序保证
# 两组各自连续，页面上传位不足时截取前几张仍是完整的一组而不是交错混合。
MAIN_GROUP_ORDER = {"宝贝主图": 0, "方图主图": 1}
DETAIL_NAME = re.compile(r"^详情(\d+)")
SKU_NAME = re.compile(r"^(颜色\d+)\s*[-－](.+)$")
KIND_KEYS = {
    "attributes": ("attributes", "商品属性模板*", "商品属性模板"),
    "logistics": ("logistics", "物流模板*", "物流模板"),
    "sales": ("sales", "销售模板*", "销售模板"),
}


def present(value):
    return value is not None and str(value).strip() != ""


def first_present(mapping, *keys):
    for key in keys:
        if mapping is not None and present(mapping.get(key)):
            return mapping.get(key)
    return ""


def resolve_path(raw, base_dir=None):
    path = Path(str(raw).strip())
    return path if path.is_absolute() else Path(base_dir or Path.cwd()) / path


def split_paths(value):
    return [part.strip() for part in str(value or "").split("|") if part.strip()]


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _pixel_ratio(path):
    try:
        from PIL import Image
        with Image.open(path) as picture:
            picture.load()
            width, height = picture.size
        return width / height if height else 0
    except Exception:
        return None


def _is_portrait_ratio(path):
    ratio = _pixel_ratio(path)
    return ratio is not None and 0.7 <= ratio <= 0.8


def _sort_num(stem):
    match = re.search(r"(\d+)", stem)
    return int(match.group(1)) if match else 10**9


def load_registry(templates_dir=None):
    root = Path(templates_dir or get_templates_dir())
    path = root / "registry.json"
    if not path.is_file():
        raise FileNotFoundError(f"找不到模板目录清单: {path}")
    data = _read_json(path)
    return {
        "attributes": [str(x).strip() for x in data.get("attributes") or [] if str(x).strip()],
        "logistics": [str(x).strip() for x in data.get("logistics") or [] if str(x).strip()],
        "sales": [str(x).strip() for x in data.get("sales") or [] if str(x).strip()],
    }


def _pick_name(names, kind):
    return str(first_present(names or {}, *KIND_KEYS[kind])).strip()


def _load_named(kind, name, templates_dir, registry):
    label = {"attributes": "商品属性", "logistics": "物流", "sales": "销售"}[kind]
    allowed = registry.get(kind) or []
    if name not in allowed:
        options = " / ".join(allowed) or "（空）"
        raise ValueError(f"未知{label}模板: {name}，可选: {options}")
    path = Path(templates_dir) / kind / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"{label}模板文件不存在: {path}")
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{label}模板必须是对象: {path}")
    data.setdefault("name", name)
    return data


def load_templates(names=None, templates_dir=None):
    """按模板名合并属性 / 物流 / 销售 JSON。names 可用英文或 Excel 列名。"""
    root = Path(templates_dir or get_templates_dir())
    registry = load_registry(root)
    names = names or {}
    merged = {"attributes": {}, "logistics": {}, "sales": {}}
    for kind in ("attributes", "logistics", "sales"):
        name = _pick_name(names, kind)
        if name:
            merged[kind] = _load_named(kind, name, root, registry)
    return merged


def _main_group(stem):
    for prefix, order in MAIN_GROUP_ORDER.items():
        if stem.startswith(prefix):
            return order
    return len(MAIN_GROUP_ORDER)


def scan_main_video(folder):
    """在扁平图片包里选主视频：优先文件名含“主视频”，否则取排序第一个视频。"""
    videos = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS),
        key=lambda p: p.name,
    )
    named = [p for p in videos if "主视频" in p.stem]
    return (named or videos or [None])[0]


def scan_image_pack(dir_path):
    """扫描扁平图片包：方图/宝贝主图、3:4 主图、详情和颜色NN-规格名。"""
    folder = Path(dir_path)
    if not folder.is_dir():
        raise FileNotFoundError(f"图片包不存在或不是目录: {folder}")
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    mains, portraits, details, skus = [], [], [], []
    classified = set()
    for path in files:
        stem = path.stem
        if PORTRAIT_NAME.search(stem):
            portraits.append((_sort_num(stem), path.name, path))
            classified.add(path)
            continue
        match = MAIN_NAME.match(stem)
        if match:
            # “宝贝主图”在不同来源中既可能是方图，也可能是 3:4 竖图；
            # “方图主图”则保留为 1:1 主图。无法读取尺寸时沿用主图命名。
            if stem.startswith("宝贝主图") and _is_portrait_ratio(path):
                portraits.append((_sort_num(stem), path.name, path))
            else:
                mains.append((_main_group(stem), int(match.group(1)), path.name, path))
            classified.add(path)
            continue
        match = DETAIL_NAME.match(stem)
        if match:
            details.append((int(match.group(1)), path.name, path))
            classified.add(path)
            continue
        match = SKU_NAME.match(stem)
        if match:
            skus.append({
                "slot": match.group(1),
                "name": match.group(2).strip(),
                "image": path,
                "_n": _sort_num(match.group(1)),
            })
            classified.add(path)
    for path in files:
        if path in classified:
            continue
        ratio = _pixel_ratio(path)
        if ratio is not None and 0.7 <= ratio <= 0.8:
            portraits.append((_sort_num(path.stem), path.name, path))
    mains.sort()
    portraits.sort()
    details.sort()
    skus.sort(key=lambda item: (item["_n"], item["slot"]))
    return {
        "main_1_1": [item[3] for item in mains],
        "main_3_4": [item[2] for item in portraits],
        "details": [item[2] for item in details],
        "skus": [{k: v for k, v in item.items() if k != "_n"} for item in skus],
        "main_video": scan_main_video(folder),
    }


def _parse_row_json(row, field):
    raw = row.get(field)
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


def _sku_overrides(sku_rows, product_id):
    overrides = {}
    for item in sku_rows or []:
        owner = str(item.get("商品标识") or "").strip()
        if owner and product_id and owner != product_id:
            continue
        slot = str(item.get("色号") or "").strip()
        if not slot:
            continue
        overrides[slot] = item
    return overrides


def _legacy_dimensions(row):
    dimensions = {}
    for index in (1, 2, 3):
        name = row.get(f"规格{index}名称")
        options = _parse_row_json(row, f"规格{index}值(JSON)") or []
        if present(name) and options:
            dimensions[str(name)] = options
    return dimensions


def _legacy_skus(row):
    parsed = _parse_row_json(row, "SKU明细(JSON)")
    if parsed is None:
        parsed = _parse_row_json(row, "SKU明细(JSON)*")
    return parsed if isinstance(parsed, list) else []


def resolve_product(row, sku_rows=None, pack=None, templates=None, base_dir=None):
    """把 Excel 行 + SKU规格 + 图片包 + 分类模板收成现有 product dict。"""
    row = row or {}
    templates = templates or {}
    attr_tpl = templates.get("attributes") or {}
    log_tpl = templates.get("logistics") or {}
    sales_tpl = templates.get("sales") or {}
    attrs = dict(attr_tpl.get("attributes") or {})
    extra = _parse_row_json(row, "商品属性(JSON)")
    if isinstance(extra, dict):
        attrs.update(extra)
    brand = str(first_present(row, "品牌*", "品牌") or attrs.get("品牌") or "").strip()
    model = str(first_present(row, "型号") or attrs.get("型号") or "").strip()
    if brand:
        attrs["品牌"] = brand
    if model:
        attrs["型号"] = model
    pack = pack or {}
    pack_mains = list(pack.get("main_1_1") or [])
    pack_portraits = list(pack.get("main_3_4") or [])
    pack_details = list(pack.get("details") or [])
    pack_skus = list(pack.get("skus") or [])
    main_images = pack_mains or [resolve_path(p, base_dir) for p in split_paths(row.get("主图路径*"))]
    portrait_images = pack_portraits or [resolve_path(p, base_dir) for p in split_paths(row.get("3:4主图路径"))]
    detail_images = pack_details or [resolve_path(p, base_dir) for p in split_paths(row.get("详情图路径"))]
    spec_name = str(sales_tpl.get("spec_name") or "商品规格").strip() or "商品规格"
    default_price = first_present(row, "价格*") if present(first_present(row, "价格*")) else row.get("价格*")
    default_stock = first_present(row, "库存*") if present(first_present(row, "库存*")) else row.get("库存*")
    product_id = str(row.get("商品标识*") or "").strip()
    overrides = _sku_overrides(sku_rows, product_id)
    skus = []
    names = []
    if pack_skus:
        for item in pack_skus:
            override = overrides.get(item.get("slot"), {})
            name = str(first_present(override, "规格名称") or item.get("name") or "").strip()
            price = override.get("价格") if present(override.get("价格")) else default_price
            stock = override.get("库存") if present(override.get("库存")) else default_stock
            names.append(name)
            image = item.get("image")
            skus.append({
                "name": name,
                "image": image,
                "price": price,
                "stock": stock,
                "规格": {spec_name: name},
                "价格": price,
                "库存": stock,
                "slot": item.get("slot"),
            })
    else:
        skus = _legacy_skus(row)
        names = []
    dimensions = {spec_name: names} if names else _legacy_dimensions(row)
    thickness = sales_tpl.get("thickness") or ""
    pack_dir = ""
    if present(row.get("图片包路径*")):
        pack_dir = str(resolve_path(row.get("图片包路径*"), base_dir))
    elif pack:
        for group in (pack.get("main_1_1"), pack.get("main_3_4"), pack.get("details")):
            if group:
                pack_dir = str(Path(group[0]).parent)
                break
        if not pack_dir:
            for item in pack.get("skus") or []:
                if item.get("image"):
                    pack_dir = str(Path(item["image"]).parent)
                    break
    return {
        "product_id": product_id,
        "title": str(row.get("商品标题*") or "").strip(),
        "guide_title": str(first_present(row, "导购标题") or "").strip(),
        "category": str(first_present(row, "类目*") or attr_tpl.get("category") or "").strip(),
        "category_id": str(attr_tpl.get("category_id") or "").strip(),
        "brand": brand,
        "model": model,
        "outer_id": str(first_present(row, "货号", "商家编码") or "").strip(),
        "attributes": attrs,
        "dimensions": dimensions,
        "skus": skus,
        "price": default_price,
        "stock": default_stock,
        "main_images": main_images,
        "portrait_images": portrait_images,
        "detail_images": detail_images,
        "description": str(row.get("商品描述") or "").strip(),
        "freight": str(first_present(row, "运费模板") or log_tpl.get("freight") or "").strip(),
        "ship_time": str(first_present(row, "发货时间") or log_tpl.get("ship_time") or "").strip(),
        "ship_from": str(first_present(row, "发货地") or log_tpl.get("ship_from") or "").strip(),
        "use_logistics": bool(log_tpl.get("use_logistics", True)) if log_tpl else True,
        "region_limit": bool(log_tpl.get("region_limit", False)) if log_tpl else False,
        "stock_deduction": str(first_present(row, "库存扣减方式") or sales_tpl.get("stock_deduction") or "").strip(),
        "listing_time": str(first_present(row, "上架时间") or sales_tpl.get("listing_time") or "").strip(),
        "thickness": str(thickness).strip(),
        "sku_category": str(first_present(row, "SKU分类") or sales_tpl.get("sku_category") or "单品").strip() or "单品",
        "spec_mode": str(sales_tpl.get("spec_mode") or "").strip(),
        "spec_name": spec_name,
        "warehouse": (str(first_present(row, "上架时间") or sales_tpl.get("listing_time") or "放入仓库").strip() == "放入仓库"),
        "main_video": pack.get("main_video"),
        "pack_dir": pack_dir,
    }
