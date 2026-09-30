"""Warehouse creation followed by the official SKU search-image importer.

开发调试 CLI：python -m web_fill.material_flow --product product.json --execute
正式任务请使用桌面「入库」按钮，由 web_fill.pipeline 调用 web_fill.material_import；
本文件只保留独立调试验证能力，不复刻另一套正式状态机。
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time

from . import pipeline
from .material_import import (
    STAGE_COMPLETE,
    SKU_URL,
    build_material_folder as build_folder,
    check_rows,
    fingerprint,
    item_id_from_result,
    material_root,
    normalize_stage,
    validate_materials as validate,
)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def lock(path):
    """OS lock is released on crash; all runs also share a browser lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("已有素材导入任务运行，请等待完成") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def normalize(product, base):
    product = json.loads(json.dumps(product))
    images = product.get("images") or {}
    for field, legacy in (("main_images", "main_1_1"), ("portrait_images", "main_3_4"), ("detail_images", "detail")):
        product[field] = [str((base / p).resolve()) for p in product.get(field, images.get(legacy, []))]
    for sku in product.get("skus", []):
        if sku.get("image"):
            sku["image"] = str((base / sku["image"]).resolve())
    return product


def run(product, state_path, *, execute=False, item_id="", session=None, timeout=180):
    key = fingerprint(product)
    state_path = Path(state_path).resolve()
    if not execute:
        return {"stage": "preflight", "sku_count": len(product["skus"]), "state": str(state_path), "notice": "预检通过；加 --execute 执行入库和素材导入"}
    with lock(pipeline.get_output() / "material_flow.lock"), lock(state_path.with_suffix(".lock")):
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"version": 1, "fingerprint": key, "stage": "new"}
        if state.get("fingerprint") != key:
            raise ValueError("商品或图片已改变，与进度文件不符；请核对原任务，勿删除进度后盲目重建")
        stage = normalize_stage(state.get("stage"))
        state["stage"] = stage
        if item_id:
            if not str(item_id).isdigit() or len(str(item_id)) < 8:
                raise ValueError("商品 ID 无效")
            if state.get("item_id") and state["item_id"] != item_id:
                raise ValueError("商品 ID 与进度文件不一致")
            state["item_id"] = item_id
            if stage in {"filled", "submit_pending"}:
                stage = state["stage"] = "created"
        if stage == "complete":
            return state
        save(state_path, state)
        web = pipeline._load_web()
        own = session is None
        session = session or web.CliSession()

        def stage_save(name, **values):
            nonlocal stage
            state.update(values, stage=name)
            stage = name
            state.pop("error", None)
            save(state_path, state)
            print(f"[素材流程] {name}", flush=True)

        def script(phase, **extra):
            return pipeline.run_script(session, "material_import.js", {
                "phase": phase, "item_id": state["item_id"], "title": product["title"],
                "baseline": state.get("baseline", []), "preview": state.get("preview", []), **extra,
            }, timeout=50)

        try:
            session.attach()
            web.assert_logged_in(session.href(), session.snapshot())
            if stage == "submit_pending":
                # Never resubmit when a crash may have happened after the click.
                raise RuntimeError("PAUSE:上次提交结果不明确；核对仓库后用 --item-id 指定商品 ID 继续，禁止自动重复建品")
            if not state.get("item_id"):
                result = pipeline.fill_new_product(session, product, confirm_submit=False, web=web, skip_spec_images=True)
                if result.get("execution") != "已填写未提交":
                    raise RuntimeError("PAUSE:" + str(result.get("notice") or "商品填写未完成"))
                stage_save("filled", publish_url=result.get("url"))
                # Persist BEFORE any possible submit; uncertainty requires ID recovery.
                stage_save("submit_pending")
                result = pipeline._finish_publish(session, pipeline.product_to_payload(product), True, web, [])
                created = item_id_from_result(result)
                if not created:
                    raise RuntimeError("PAUSE:未取得已提交商品 ID，请核对仓库后用 --item-id 继续")
                stage_save("created", item_id=created, success_url=result.get("url"), creation=result)
            # Preserve an in-progress drawer on resume; otherwise create a dedicated tab.
            tabs = pipeline.parse_tabs(session.tab_list())
            prefix = SKU_URL.split("?")[0]
            found = next((i for i, url in tabs if url.startswith(prefix)), None)
            if found is None:
                session.tab_new(SKU_URL)
            else:
                session.tab_select(found)
            if stage == "created":
                baseline = script("baseline")
                check_rows(baseline["rows"], product)
                by_name = {sku["name"]: sku for sku in product["skus"]}
                ordered = {**product, "skus": [by_name[row["name"]] for row in baseline["rows"]]}
                folder = build_folder(ordered, state["item_id"], state_path.parent / (state_path.stem + "_materials"))
                stage_save("material_prepared", baseline=baseline["rows"], folder=str(folder))
            if stage == "material_prepared":
                stage_save("material_upload_pending")
                script("upload", folder=state["folder"])
            if stage in {"material_upload_pending", "material_recognizing"}:
                stage_save("material_recognizing")
                deadline = time.monotonic() + timeout
                while True:
                    pipeline._check_cancel(session)
                    preview = script("preview")
                    if preview.get("ready"):
                        check_rows(preview["rows"], product, state["baseline"], images=True)
                        stage_save("material_reviewed", preview=preview["rows"])
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError("PAUSE:素材识别未完成；保留页面和进度，再运行原命令继续等待")
                    time.sleep(3)
            if stage == "material_reviewed":
                # Re-read immediately before adoption: never trust stale AI results.
                preview = script("preview")
                if not preview.get("ready") or preview["rows"] != state["preview"]:
                    raise RuntimeError("PAUSE:素材确认页面已变化，请核对")
                stage_save("material_adopt_pending")
                script("adopt")
            if stage in {"material_adopt_pending", "material_verifying"}:
                stage_save("material_verifying")
                verified = script("verify")
                check_rows(verified["rows"], product, state["baseline"], images=True)
                stage_save("complete", verified=verified["rows"], notice="SKU 搜索主图已采纳并复核")
            return state
        except Exception as exc:
            state["error"] = str(exc)
            save(state_path, state)
            raise
        finally:
            if own:
                session.detach()


def main(argv=None):
    parser = argparse.ArgumentParser(description="瘦身入库 → 商品 ID → 图片文件夹 → 官方 SKU 搜索主图导入；同一进度文件可续跑")
    parser.add_argument("--product", required=True, type=Path, help="单个商品 JSON")
    parser.add_argument("--base-dir", type=Path, default=pipeline.ROOT, help="JSON 图片相对路径的根目录，默认项目目录")
    parser.add_argument("--state", type=Path, help="进度 JSON，默认 output/playwright/material_flow/<输入文件名>.json")
    parser.add_argument("--item-id", default="", help="已有商品 ID：只补图，或恢复结果不明确的提交")
    parser.add_argument("--execute", action="store_true", help="执行真实入库和采纳；不加时仅本地预检")
    args = parser.parse_args(argv)
    try:
        product = normalize(json.loads(args.product.read_text(encoding="utf-8-sig")), args.base_dir.resolve())
        state = args.state or pipeline.get_output() / "material_flow" / (args.product.stem + ".json")
        result = run(product, state, execute=args.execute, item_id=args.item_id)
        print(json.dumps({k: result[k] for k in ("stage", "item_id", "folder", "notice", "state") if k in result}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
