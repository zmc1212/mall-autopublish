"""工作空间扫描：支持一级商品目录或“类别/商品”两级目录。CLI 与桌面共用。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from 商品解析 import IMAGE_EXTS, load_registry, scan_image_pack

DEFAULTS_NAME = "批次默认.json"
WORKBOOK_NAME = "商品清单.xlsx"
SELECTED_CATEGORIES_KEY = "selected_categories"
KNOWN_CATEGORIES_KEY = "known_categories"
MISSING_STATUS = "资料缺失"
MISSING_NOTICE = "图片夹不存在或没有可识别图片"
TITLE_MAX_WIDTH = 60

DEFAULT_DEFAULTS = {
    "品牌": "卡游",
    "商品属性模板": "中性笔",
    "物流模板": "48小时",
    "销售模板": "仓库多规格",
    "价格": 9.9,
    "库存": 20,
}

_API_TO_FILE = {
    "brand": "品牌",
    "attributes_template": "商品属性模板",
    "logistics_template": "物流模板",
    "sales_template": "销售模板",
    "price": "价格",
    "stock": "库存",
}
_FILE_TO_API = {value: key for key, value in _API_TO_FILE.items()}


def _present(value):
    return value is not None and str(value).strip() != ""


def _seller():
    from desktop.modules import load_seller

    return load_seller()


def title_width(text):
    return sum(2 if ord(ch) > 127 else 1 for ch in str(text or ""))


def clip_title(text, max_width=TITLE_MAX_WIDTH):
    out = []
    width = 0
    for char in str(text or ""):
        step = 2 if ord(char) > 127 else 1
        if width + step > max_width:
            break
        out.append(char)
        width += step
    return "".join(out)


def template_registry():
    try:
        data = load_registry()
    except Exception:
        data = {}
    return {
        "attributes": list(data.get("attributes") or ["中性笔"]),
        "logistics": list(data.get("logistics") or ["48小时", "24小时"]),
        "sales": list(data.get("sales") or ["仓库多规格"]),
    }


def normalize_defaults(data=None):
    merged = dict(DEFAULT_DEFAULTS)
    raw = dict(data or {})
    for api_key, file_key in _API_TO_FILE.items():
        if _present(raw.get(file_key)):
            merged[file_key] = raw.get(file_key)
        elif _present(raw.get(api_key)):
            merged[file_key] = raw.get(api_key)
    price = merged.get("价格")
    stock = merged.get("库存")
    try:
        merged["价格"] = float(price) if price not in (None, "") else DEFAULT_DEFAULTS["价格"]
    except (TypeError, ValueError):
        merged["价格"] = DEFAULT_DEFAULTS["价格"]
    try:
        merged["库存"] = int(stock) if stock not in (None, "") else DEFAULT_DEFAULTS["库存"]
    except (TypeError, ValueError):
        merged["库存"] = DEFAULT_DEFAULTS["库存"]
    for key in ("品牌", "商品属性模板", "物流模板", "销售模板"):
        merged[key] = str(merged.get(key) or "").strip()
    if not merged["商品属性模板"]:
        merged["商品属性模板"] = DEFAULT_DEFAULTS["商品属性模板"]
    if not merged["物流模板"]:
        merged["物流模板"] = DEFAULT_DEFAULTS["物流模板"]
    if not merged["销售模板"]:
        merged["销售模板"] = DEFAULT_DEFAULTS["销售模板"]
    for key in (SELECTED_CATEGORIES_KEY, KNOWN_CATEGORIES_KEY):
        if key in raw and isinstance(raw.get(key), list):
            merged[key] = sorted({str(item).strip() for item in raw[key] if str(item).strip()})
    return merged


def defaults_for_api(data=None):
    merged = normalize_defaults(data)
    return {api_key: merged.get(file_key) for api_key, file_key in _API_TO_FILE.items()}


def workbook_path(root):
    return Path(root).expanduser().resolve() / WORKBOOK_NAME


def defaults_path(root):
    return Path(root).expanduser().resolve() / DEFAULTS_NAME


def load_defaults(root):
    path = defaults_path(root)
    data = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    return normalize_defaults(data)


def save_defaults(root, data=None):
    folder = Path(root).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    current = load_defaults(folder)
    raw = dict(data or {})
    patch = {}
    for api_key, file_key in _API_TO_FILE.items():
        if api_key in raw and raw[api_key] is not None:
            patch[file_key] = raw[api_key]
        elif file_key in raw and raw[file_key] is not None:
            patch[file_key] = raw[file_key]
    for key in (SELECTED_CATEGORIES_KEY, KNOWN_CATEGORIES_KEY):
        if key in raw and isinstance(raw.get(key), list):
            patch[key] = raw[key]
    merged = normalize_defaults({**current, **patch})
    path = defaults_path(folder)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return merged


def _relative_folder(root, folder):
    try:
        return Path(os.path.relpath(folder, root)).as_posix()
    except ValueError:
        return str(folder)


def _pack_has_media(pack):
    return bool(
        pack.get("main_1_1")
        or pack.get("main_3_4")
        or pack.get("details")
        or pack.get("skus")
    )


def _sku_summary(pack):
    items = []
    for sku in pack.get("skus") or []:
        items.append({
            "slot": str(sku.get("slot") or "").strip(),
            "name": str(sku.get("name") or "").strip(),
        })
    return [item for item in items if item["slot"]]


def _scan_pack(root, pack_folder, category="", selected=True):
    name = pack_folder.name
    files = [path for path in pack_folder.iterdir() if path.is_file()]
    images = [path for path in files if path.suffix.lower() in IMAGE_EXTS]
    if not files:
        return None, {"folder": name, "category": category, "reason": "空目录"}, None
    if not images:
        return None, None, {"folder": name, "category": category, "error": "没有可识别图片"}
    try:
        pack = scan_image_pack(pack_folder)
    except Exception as exc:
        return None, None, {"folder": name, "category": category, "error": str(exc)}
    if not _pack_has_media(pack):
        return None, None, {"folder": name, "category": category, "error": "没有可识别图片"}
    product_id = f"{category}-{name}" if category else name
    return ({
        "product_id": product_id,
        "name": name,
        "category": category,
        "category_path": _relative_folder(root, pack_folder.parent) if category else "",
        "selected": bool(selected),
        "path": str(pack_folder),
        "relative": _relative_folder(root, pack_folder),
        "main_count": len(pack.get("main_1_1") or []),
        "portrait_count": len(pack.get("main_3_4") or []),
        "detail_count": len(pack.get("details") or []),
        "sku_count": len(pack.get("skus") or []),
        "video_count": 1 if pack.get("main_video") else 0,
        "skus": _sku_summary(pack),
    }, None, None)


def scan_workspace(root, selected_categories=None):
    """扫描一级商品目录及“类别/商品”两级目录。"""
    folder = Path(root).expanduser().resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f"工作空间不存在或不是目录: {folder}")
    selected_set = None if selected_categories is None else {
        str(item).strip() for item in selected_categories if str(item).strip()
    }
    registry = set(template_registry().get("attributes") or [])
    found = []
    skipped = []
    errors = []
    categories = []
    for child in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith("."):
            skipped.append({"folder": name, "category": "", "reason": "隐藏目录"})
            continue
        files = [path for path in child.iterdir() if path.is_file()]
        images = [path for path in files if path.suffix.lower() in IMAGE_EXTS]
        if images:
            item, skip, error = _scan_pack(folder, child)
            if item:
                found.append(item)
            if skip:
                skipped.append(skip)
            if error:
                errors.append(error)
            continue
        product_dirs = [
            path for path in sorted(child.iterdir(), key=lambda item: item.name.lower())
            if path.is_dir() and not path.name.startswith(".")
        ]
        if not product_dirs:
            if not files:
                skipped.append({"folder": name, "category": "", "reason": "空目录"})
            else:
                errors.append({"folder": name, "category": "", "error": "没有可识别图片"})
            continue
        selected = selected_set is None or name in selected_set
        category_errors = 0
        product_count = 0
        template_found = name in registry
        for product_dir in product_dirs:
            item, skip, error = _scan_pack(folder, product_dir, name, selected)
            if item:
                found.append(item)
                product_count += 1
            if skip:
                skipped.append(skip)
            if error:
                errors.append(error)
                category_errors += 1
        if not template_found:
            errors.append({"folder": name, "category": name, "error": "未配置同名商品属性模板"})
            category_errors += 1
        categories.append({
            "name": name,
            "path": str(child),
            "relative": _relative_folder(folder, child),
            "selected": selected,
            "product_count": product_count,
            "error_count": category_errors,
            "template_found": template_found,
            "notice": "" if template_found else "未配置同名商品属性模板",
        })
    seen = set()
    unique = []
    for item in found:
        product_id = item["product_id"]
        if product_id in seen:
            errors.append({
                "folder": item["name"],
                "category": item["category"],
                "error": f"商品标识冲突: {product_id}",
            })
            continue
        seen.add(product_id)
        unique.append(item)
    return {
        "root": str(folder),
        "folders": unique,
        "categories": categories,
        "skipped": skipped,
        "errors": errors,
    }


def _read_sheet_dicts(ws, headers_wanted=None):
    rows = ws.iter_rows(values_only=True)
    headers = [str(cell or "").strip() for cell in next(rows, ())]
    items = []
    for values in rows:
        data = dict(zip(headers, values))
        if headers_wanted:
            if not any(_present(data.get(key)) for key in headers_wanted):
                continue
        elif not any(_present(value) for value in data.values()):
            continue
        items.append(data)
    return headers, items


def _read_existing(path):
    from openpyxl import load_workbook

    seller = _seller()
    wb = load_workbook(path)
    try:
        sheet = wb["商品清单"] if "商品清单" in wb.sheetnames else wb.worksheets[0]
        _, products = _read_sheet_dicts(sheet)
        sku_rows = []
        if "SKU规格" in wb.sheetnames:
            _, sku_rows = _read_sheet_dicts(wb["SKU规格"], seller.SKU_HEADERS)
        log_rows = []
        if "处理日志" in wb.sheetnames:
            log = wb["处理日志"]
            for row in log.iter_rows(min_row=2, values_only=True):
                if any(_present(value) for value in row):
                    log_rows.append(list(row))
        return products, sku_rows, log_rows
    finally:
        wb.close()


def _as_template_row(data):
    seller = _seller()
    row = {field: data.get(field, "") for field in seller.TEMPLATE_HEADERS}
    if not _present(row.get("品牌*")) and _present(data.get("品牌")):
        row["品牌*"] = data.get("品牌")
    return row


def _new_product_row(folder, defaults):
    seller = _seller()
    name = folder["product_id"]
    brand = str(defaults.get("品牌") or "").strip()
    folder_name = folder.get("name") or name
    title = clip_title(folder_name)
    # 两级目录中的上级文件夹只是商品分组，不一定是可用的商品属性模板。
    # 只有注册表中存在同名模板时才使用它，否则回退到批次默认模板，
    # 避免在后续校验阶段因“未知商品属性模板”阻断整次扫描。
    category = str(folder.get("category") or "").strip()
    valid_attributes = set(template_registry().get("attributes") or [])
    attribute_template = category if category in valid_attributes else str(
        defaults.get("商品属性模板") or "中性笔"
    ).strip()
    row = {field: "" for field in seller.TEMPLATE_HEADERS}
    row.update({
        "商品标识*": name,
        "商品标题*": title,
        "品牌*": brand,
        "型号": "",
        "图片包路径*": folder["relative"],
        "商品属性模板*": attribute_template,
        "物流模板*": defaults.get("物流模板") or "48小时",
        "销售模板*": defaults.get("销售模板") or "仓库多规格",
        "价格*": defaults.get("价格"),
        "库存*": defaults.get("库存"),
        "处理状态": "待处理",
        "错误信息": "",
    })
    return row


def _clear_missing(row):
    if str(row.get("处理状态") or "").strip() == MISSING_STATUS:
        row["处理状态"] = "待处理"
        notice = str(row.get("错误信息") or "")
        if MISSING_NOTICE in notice or "图片夹" in notice:
            row["错误信息"] = ""
    return row


def _pack_outside_root(root, pack_value):
    """判断图片包路径是否指向工作空间之外（手工维护的外部包）。"""
    value = str(pack_value or "").strip()
    if not value:
        return False
    path = Path(value)
    if not path.is_absolute():
        path = Path(root) / path
    try:
        rel = os.path.relpath(os.path.normpath(str(path)), str(Path(root).expanduser().resolve()))
    except ValueError:
        return True
    return rel == ".." or rel.startswith(".." + os.sep) or rel.startswith("../")


def _sku_key(row):
    return (str(row.get("商品标识") or "").strip(), str(row.get("色号") or "").strip())


def _merge_rows(existing_products, existing_skus, scan, defaults, root=None):
    """清单以工作空间文件夹为镜像：文件夹消失的行直接移除并计入 removed，
    仅保留图片包指向工作空间之外的手工维护行。"""
    seller = _seller()
    registry = template_registry()
    all_folders = scan.get("folders") or []
    folder_by_id = {item["product_id"]: item for item in all_folders if item.get("selected", True)}
    unselected_ids = {item["product_id"] for item in all_folders if not item.get("selected", True)}
    products = []
    seen = set()
    removed = []
    for raw in existing_products or []:
        row = _as_template_row(raw)
        # 旧版两级目录曾把分组名写入模板列。无效模板无法被校验器加载，
        # 会导致整个工作空间导入失败；仅对非空且未注册的值回退到批次默认。
        for field, default_key, kind in (
            ("商品属性模板*", "商品属性模板", "attributes"),
            ("物流模板*", "物流模板", "logistics"),
            ("销售模板*", "销售模板", "sales"),
        ):
            value = str(row.get(field) or "").strip()
            allowed = set(registry.get(kind) or [])
            if value and value not in allowed:
                fallback = str(defaults.get(default_key) or "").strip()
                if fallback in allowed:
                    row[field] = fallback
        product_id = str(row.get("商品标识*") or "").strip()
        if not product_id:
            continue
        if product_id in unselected_ids:
            continue
        folder = folder_by_id.get(product_id)
        if folder:
            seen.add(product_id)
            row["图片包路径*"] = folder["relative"]
            _clear_missing(row)
            products.append(row)
            continue
        if root is not None and _pack_outside_root(root, row.get("图片包路径*")):
            pack = Path(str(row.get("图片包路径*") or "").strip())
            if not pack.is_absolute():
                pack = Path(root) / pack
            if pack.is_dir():
                _clear_missing(row)
            seen.add(product_id)
            products.append(row)
            continue
        removed.append(product_id)
    added = []
    for folder in folder_by_id.values():
        if folder["product_id"] in seen:
            continue
        products.append(_new_product_row(folder, defaults))
        added.append(folder["product_id"])
    sku_rows = []
    emitted = set()
    kept_product_ids = {str(row.get("商品标识*") or "").strip() for row in products}
    for raw in existing_skus or []:
        item = {field: raw.get(field, "") for field in seller.SKU_HEADERS}
        key = _sku_key(item)
        if key[0] not in kept_product_ids or not key[1] or key in emitted:
            continue
        sku_rows.append(item)
        emitted.add(key)
    for folder in folder_by_id.values():
        for sku in folder.get("skus") or []:
            key = (folder["product_id"], sku["slot"])
            if not key[1] or key in emitted:
                continue
            sku_rows.append({
                "商品标识": folder["product_id"],
                "色号": sku["slot"],
                "规格名称": "",
                "价格": "",
                "库存": "",
            })
            emitted.add(key)
    return products, sku_rows, added, removed


def sync_workbook(root, defaults=None, selected_categories=None):
    """以工作空间文件夹为镜像生成/同步 商品清单.xlsx，返回路径和扫描摘要。"""
    folder = Path(root).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    current = load_defaults(folder)
    discovered_scan = scan_workspace(folder)
    discovered = {item["name"] for item in discovered_scan.get("categories") or []}
    known = set(current.get(KNOWN_CATEGORIES_KEY) or [])
    if selected_categories is None:
        if SELECTED_CATEGORIES_KEY in current:
            selected = (set(current.get(SELECTED_CATEGORIES_KEY) or []) & discovered) | (discovered - known)
        else:
            selected = set(discovered)
    else:
        selected = {str(item).strip() for item in selected_categories if str(item).strip()} & discovered
    settings = dict(defaults if defaults is not None else current)
    settings[SELECTED_CATEGORIES_KEY] = sorted(selected)
    settings[KNOWN_CATEGORIES_KEY] = sorted(discovered)
    saved_defaults = save_defaults(folder, settings)
    scan = scan_workspace(folder, selected)
    target = workbook_path(folder)
    existing_products, existing_skus, log_rows = [], [], []
    created = not target.is_file()
    if target.is_file():
        try:
            existing_products, existing_skus, log_rows = _read_existing(target)
        except Exception:
            existing_products, existing_skus, log_rows = [], [], []
            created = True
    products, sku_rows, added, removed = _merge_rows(
        existing_products, existing_skus, scan, saved_defaults, root=folder
    )
    seller = _seller()
    seller.write_listing_workbook(target, products, sku_rows, log_rows)
    return {
        "path": str(target),
        "root": str(folder),
        "created": created,
        "added": added,
        "removed": removed,
        "defaults": saved_defaults,
        "scan": scan,
        "count": len(products),
    }
