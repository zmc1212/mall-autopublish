"""Build a per-product SKU import file from the seller's category template."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4
import warnings

from openpyxl import load_workbook


# 千牛按类目导出的 SKU 批量导入模板互不通用：表头列、规格列名、预置示例行
# 都由类目销售属性决定，这里按类目 ID 注册各自的模板与写行规则。
CATEGORY_CONFIGS = {
    # 中性笔：规格列叫“商品规格”，页面还有 SKU分类/书写粗细 需要脚本补填。
    "50012720": {
        "template": "sku_import_50012720.xls",
        "headers": ("颜色分类", "书写粗细", "支数", "商品规格", "价格", "数量", "商家编码", "商品条形码"),
        "spec_name": "商品规格",
        "fixed": {},
        "sku_category": "单品",
    },
    # 潮玩盲盒：规格列叫“款式描述”（p-1627207 在该类目的名称），模板自带
    # “大小”维度与 5 行示例数据；导入后页面上没有 SKU分类/书写粗细 列。
    # “大小”取卖家模板示例值“正版发售”，保证多维度组合每行唯一。
    "122692006": {
        "template": "sku_import_122692006.xls",
        "headers": ("款式描述", "大小", "SKU搜索主图", "价格", "数量", "商家编码", "SKU搜索标题", "是否上架", "款式特点", "商品状态"),
        "spec_name": "款式描述",
        "fixed": {"大小": "正版发售", "是否上架": 1},
        "sku_category": None,
    },
}

# 兼容旧引用：中性笔表头。
HEADERS = CATEGORY_CONFIGS["50012720"]["headers"]

# 列名 -> SKU 字段。其余列只能来自 fixed 常量。
COLUMN_FIELDS = {
    "价格": "price",
    "数量": "stock",
    "商家编码": "merchant_code",
    "商品条形码": "barcode",
}


def config_for(payload: dict) -> dict | None:
    config = CATEGORY_CONFIGS.get(str(payload.get("category_id") or ""))
    if not config:
        return None
    spec_name = str(payload.get("spec_name") or config["spec_name"]).strip() or config["spec_name"]
    if spec_name != config["spec_name"]:
        return None
    return config


def supports_product(payload: dict) -> bool:
    return bool(payload.get("skus")) and config_for(payload) is not None


def needs_sku_category(payload: dict) -> bool:
    config = config_for(payload)
    return bool(config and config.get("sku_category"))


def template_name(payload: dict) -> str:
    config = config_for(payload)
    return (config or CATEGORY_CONFIGS["50012720"])["template"]


def _find_header_row(sheet, headers: tuple) -> int:
    """表头行定位：中性笔在第 1 行，潮玩盲盒前两行是平台说明文字。"""
    for row in range(1, min(sheet.max_row, 10) + 1):
        cells = tuple(sheet.cell(row, col).value for col in range(1, len(headers) + 1))
        stripped = tuple(str(cell).strip() for cell in cells if cell not in (None, ""))
        if stripped == headers:
            return row
    return 0


def build_import_file(payload: dict, template: Path, directory: Path) -> Path:
    """Keep the original OOXML structure, including its hidden worksheet and .xls suffix."""
    config = config_for(payload)
    if not config or not supports_product(payload):
        raise ValueError("当前商品类目或规格列与 SKU 导入模板不匹配")
    if not template.is_file():
        raise FileNotFoundError(f"缺少千牛 SKU 导入模板: {template}")
    # The file supplied by Qianniu is OOXML despite its .xls name. Loading bytes
    # avoids openpyxl's extension guard while retaining the seller's file suffix.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        workbook = load_workbook(BytesIO(template.read_bytes()))
    sheet = workbook.worksheets[0]
    headers = config["headers"]
    header_row = _find_header_row(sheet, headers)
    if not header_row:
        actual = tuple(sheet.cell(1, index).value for index in range(1, len(headers) + 1))
        raise ValueError(f"千牛 SKU 模板表头已变化: {actual}")
    # 卖家导出的模板可能自带示例数据行（潮玩盲盒模板预置 5 行），
    # 先清空再写入，避免示例行被导入成真实规格。
    if sheet.max_row > header_row:
        sheet.delete_rows(header_row + 1, sheet.max_row - header_row)
    fixed = config["fixed"]
    for index, sku in enumerate(payload["skus"], 1):
        name = str(sku.get("name") or "").strip()
        if not name:
            raise ValueError(f"第 {index} 个 SKU 缺少{config['spec_name']}")
        price = sku.get("price")
        stock = sku.get("stock")
        if price in (None, "") or stock in (None, ""):
            raise ValueError(f"SKU {name} 缺少价格或数量")
        # 书写粗细等非必填列：留空，不进模板也不在页面上点选，
        # 避免触发滑块认证与多维度识别的"在当前规格后添加"卡顿。
        for column, header in enumerate(headers, 1):
            if header == config["spec_name"]:
                value = name
            elif header in COLUMN_FIELDS:
                raw = sku.get(COLUMN_FIELDS[header])
                value = None if raw in (None, "") else raw
            else:
                value = fixed.get(header)
            sheet.cell(header_row + index, column, value)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"SKU导入_{uuid4().hex}.xls"
    workbook.save(destination)
    return destination
