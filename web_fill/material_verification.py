"""Offline evidence audit for the official importer; never opens a browser.

python -m web_fill.material_verification --evidence evidence.json --report report.json
Missing observations are inconclusive, never evidence of synchronization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .material_import import validate_materials

FIELDS = ("name", "price", "stock", "attributes", "search_title", "merchant_code")


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{8,20}", value):
        raise ValueError("商品ID和skuId必须是8至20位数字文本")
    return value


def _rows(snapshot, item_id):
    if not isinstance(snapshot, dict):
        raise ValueError("快照必须是对象")
    if _id(snapshot.get("item_id")) != item_id:
        raise ValueError("快照商品ID不符")
    if not snapshot.get("evidence_ref"):
        raise ValueError("缺少页面证据引用")
    rows = snapshot.get("rows", [])
    if not rows:
        raise ValueError("快照没有SKU")
    result, names = {}, set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("SKU行必须是对象")
        key = _id(row.get("sku_id"))
        if key in result or row.get("name") in names:
            raise ValueError("SKU ID或名称重复")
        for field in (*FIELDS, "search_image", "spec_image"):
            if field not in row or row[field] is None:
                raise ValueError(f"SKU {key} 缺少明确字段: {field}")
        if not isinstance(row["attributes"], dict):
            raise ValueError("规格属性必须是完整字段字典")
        if any(not isinstance(row[field], str) for field in
               ("name", "search_title", "merchant_code", "search_image", "spec_image")):
            raise ValueError("名称、标题、编码和图片地址必须是文本")
        for field in ("price", "stock"):
            number = Decimal(str(row[field]))
            if not number.is_finite() or number < 0 or (field == "stock" and number != int(number)):
                raise ValueError(f"SKU {key} 的{field}无效")
        names.add(row["name"])
        result[key] = row
    return result


def differences(before, after):
    diffs = []
    if set(before) != set(after):
        diffs.append({"field": "sku_ids", "before": sorted(before), "after": sorted(after)})
    for key in sorted(set(before) & set(after)):
        for field in FIELDS:
            a, b = before[key][field], after[key][field]
            equal = Decimal(str(a)) == Decimal(str(b)) if field in {"price", "stock"} else a == b
            if not equal:
                diffs.append({"sku_id": key, "field": field, "before": a, "after": b})
    return diffs


def _matched(snapshot, row, kind, expected_hash):
    """Require content evidence bound to this exact image, SKU and source file.

    Evidence is supplied by an observer, not inferred from a nonempty URL.
    The report makes no claim to have independently performed that observation.
    """
    proof = row.get(kind + "_match", {})
    return bool(row[kind + "_image"] and isinstance(proof, dict)
                and proof.get("matched") is True
                and proof.get("sku_id") == row["sku_id"]
                and proof.get("image") == row[kind + "_image"]
                and proof.get("source_sha256") == expected_hash
                and proof.get("method") in {"visual", "decoded_pixels"}
                and proof.get("evidence_ref")
                and snapshot.get("evidence_ref"))


def evaluate(evidence):
    result = {"conclusion": "inconclusive", "search_images": "unverified",
              "spec_images": "unverified", "non_image_differences": [],
              "reason": "", "source": "supplied_observations", "default_strategy_changed": False}
    try:
        if not isinstance(evidence, dict):
            raise ValueError("证据必须是对象")
        item_id = _id(evidence.get("item_id"))
        result["item_id"] = item_id
        product = evidence.get("product", {})
        if str(product.get("category_id")) != "50012720":
            raise ValueError("本次验证仅支持中性笔类目50012720")
        validate_materials(product)
        before = _rows(evidence.get("before", {}), item_id)
        local = {sku["name"]: sku for sku in product["skus"]}
        if set(local) != {r["name"] for r in before.values()}:
            raise ValueError("本地图片与后台SKU名称不一一对应")
        hashes = {key: hashlib.sha256(Path(local[row["name"]]["image"]).read_bytes()).hexdigest()
                  for key, row in before.items()}
        missing = [key for key, row in before.items() if row["spec_image"] == ""]
        result["originally_missing_spec_ids"] = missing
        if not missing:
            raise ValueError("上传前没有销售规格图缺失的SKU，不能证明同步")
        rule = evidence.get("template_rule", {})
        if rule.get("confirmed") is not True or not rule.get("evidence_ref") or not rule.get("description"):
            raise ValueError("尚未确认官方模板图片列填写规则")
        preview_snapshot = evidence.get("preview", {})
        preview = _rows(preview_snapshot, item_id)
        diffs = differences(before, preview)
        result["non_image_differences"] = [{"phase": "preview", **d} for d in diffs]
        if diffs:
            raise ValueError("识别预览修改了非图片字段或SKU集合，禁止采纳")
        if not all(_matched(preview_snapshot, r, "search", hashes[k]) for k, r in preview.items()):
            raise ValueError("预览图片缺少逐SKU内容匹配证据，禁止采纳")
        after_snapshot = evidence.get("after", {})
        if after_snapshot.get("reloaded_search") is not True or after_snapshot.get("reopened_editor") is not True:
            raise ValueError("缺少采纳后重新加载两类页面的证据")
        if after_snapshot.get("processing_complete") is not True:
            raise ValueError("平台尚未明确处理完成")
        after = _rows(after_snapshot, item_id)
        diffs = differences(before, after)
        result["non_image_differences"].extend({"phase": "after", **d} for d in diffs)
        if diffs:
            raise ValueError("采纳后非图片字段或SKU集合发生变化")
        if not all(_matched(after_snapshot, r, "search", hashes[k]) for k, r in after.items()):
            raise ValueError("搜索主图持久化或内容对应关系尚未验证")
        result["search_images"] = "verified"
        if all(_matched(after_snapshot, r, "spec", hashes[k]) for k, r in after.items()):
            result.update(conclusion="candidate", spec_images="verified",
                          reason="本商品符合替代候选条件；仍需另一款中性笔复验，默认策略不变")
        elif all(after[k]["spec_image"] == "" for k in missing) and all(
                after[k]["spec_image"] == r["spec_image"] for k, r in before.items()):
            result.update(conclusion="not_replacement", spec_images="unchanged",
                          reason="搜索主图已更新，销售规格图保持原状，本商品不能替代")
        else:
            result["reason"] = "销售规格图部分变化或缺少内容匹配证据，无法判断"
    except (ValueError, TypeError, KeyError, AttributeError, OSError, InvalidOperation) as exc:
        result["reason"] = str(exc)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线核对素材导入前后证据；不连接浏览器、不上传")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    evidence = json.loads(args.evidence.read_text(encoding="utf-8-sig"))
    # Paths are relative to the evidence file, not the caller's working directory.
    product = evidence.get("product", {})
    for sku in product.get("skus", []):
        if sku.get("image"):
            sku["image"] = str((args.evidence.parent / sku["image"]).resolve())
    for key in ("main_images", "portrait_images", "detail_images"):
        product[key] = [str((args.evidence.parent / p).resolve()) for p in product.get(key, [])]
    if args.evidence.resolve() == args.report.resolve():
        parser.error("报告不能覆盖输入证据")
    result = evaluate(evidence)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report.with_suffix(args.report.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.report)
    print(result["conclusion"] + ": " + result["reason"])
    return 2 if result["conclusion"] == "inconclusive" else 0


if __name__ == "__main__":
    raise SystemExit(main())
