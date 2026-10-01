"""按已核验剧本填写新建发布页。不覆盖当前得力页，默认不点提交。"""

import importlib
import importlib.util
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from pathlib import Path

from . import sku_import

ROOT = Path(__file__).resolve().parent.parent
CATEGORY_ENTRY = "https://item.upload.taobao.com/sell/ai/category.htm"


def get_scripts():
    raw = os.environ.get("QIANNIU_SCRIPTS_DIR")
    return Path(raw) if raw else Path(__file__).resolve().parent / "scripts"


def get_output():
    raw = os.environ.get("QIANNIU_OUTPUT_DIR")
    return Path(raw) if raw else ROOT / "output" / "playwright"


def get_helpers():
    return (get_scripts() / "_helpers.inc.js").read_text(encoding="utf-8")


def reload_paths():
    global SCRIPTS, OUTPUT, HELPERS
    SCRIPTS = get_scripts()
    OUTPUT = get_output()
    HELPERS = get_helpers()


SCRIPTS = get_scripts()
OUTPUT = get_output()
HELPERS = get_helpers() if (get_scripts() / "_helpers.inc.js").is_file() else ""


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[@-Z\\-_]")


def strip_cli_text(text):
    return ANSI_ESCAPE.sub("", str(text or ""))


def _web_candidates():
    paths = []
    root_env = os.environ.get("QIANNIU_ROOT")
    if root_env:
        paths.append(Path(root_env) / "千牛网页执行.py")
    paths.append(ROOT / "千牛网页执行.py")
    exe_dir = Path(sys.executable).resolve().parent
    paths.append(exe_dir / "千牛网页执行.py")
    seen = set()
    unique = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _load_web():
    existing = sys.modules.get("千牛网页执行") or sys.modules.get("qianniu_web")
    if existing is not None:
        return existing
    for path in _web_candidates():
        if path.is_file():
            spec = importlib.util.spec_from_file_location("千牛网页执行", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules["千牛网页执行"] = module
            spec.loader.exec_module(module)
            return module
    return importlib.import_module("千牛网页执行")


def _prune_tabs(web=None, **kwargs):
    web = web or _load_web()
    fn = getattr(web, "prune_automation_tabs", None)
    if not callable(fn):
        return None
    try:
        return fn(**kwargs)
    except Exception:
        return None


def _abs(path):
    if path in (None, ""):
        return ""
    return Path(path).resolve().as_posix()


def product_to_payload(product):
    skus = []
    for item in product.get("skus") or []:
        image = item.get("image") or ""
        name = str(item.get("name") or "").strip()
        skus.append({
            "slot": str(item.get("slot") or "").strip(),
            "name": name,
            "image": _abs(image),
            "file": Path(image).name if image else "",
            "price": item.get("price", item.get("价格")),
            "stock": item.get("stock", item.get("库存")),
            "merchant_code": item.get("商家编码", item.get("merchant_code", "")),
            "barcode": item.get("商品条形码", item.get("barcode", "")),
        })
    mains = [_abs(p) for p in (product.get("main_images") or []) if p]
    # 页面主图位最多5张。图片包可能同时带“宝贝主图”“方图主图”两组备选，
    # scan_image_pack 已按组排序，这里截取前5张，通常是完整的一组。
    mains = mains[:5]
    portraits = [_abs(p) for p in (product.get("portrait_images") or []) if p]
    details = [_abs(p) for p in (product.get("detail_images") or []) if p]
    category = str(product.get("category") or "")
    leaf = category.replace(">>", ">").split(">")[-1].strip() if category else "中性笔"
    attrs = dict(product.get("attributes") or {})
    if not str(attrs.get("IP联名") or "").strip() and "火影" in str(product.get("title") or ""):
        attrs["IP联名"] = "火影忍者"
    return {
        "title": str(product.get("title") or "").strip(),
        "guide_title": str(product.get("guide_title") or "").strip(),
        "brand": str(product.get("brand") or "").strip(),
        "model": str(product.get("model") or "").strip(),
        "leaf": leaf,
        "category_id": str(product.get("category_id") or "").strip(),
        "spec_name": str(product.get("spec_name") or "商品规格").strip(),
        "attributes": attrs,
        "skus": skus,
        "thickness": str(product.get("thickness") or "0.05mm").strip() or "0.05mm",
        "sku_category": str(product.get("sku_category") or "单品").strip() or "单品",
        "ship_time": str(product.get("ship_time") or "").strip(),
        "ship_from": str(product.get("ship_from") or "").strip(),
        "freight": str(product.get("freight") or "").strip(),
        "stock_deduction": str(product.get("stock_deduction") or "拍下减库存").strip(),
        "main_images": mains,
        "portrait_images": portraits,
        "detail_images": details,
        "main_video": _abs(product.get("main_video")),
    }


def render_script(name, payload):
    src = (get_scripts() / name).read_text(encoding="utf-8")
    blob = json.dumps(payload, ensure_ascii=False)
    rendered = src.replace("/*PAYLOAD*/", blob, 1).replace("/*HELPERS*/", get_helpers(), 1)
    out = get_output()
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"web_fill_{Path(name).stem}.js"
    target.write_text(rendered, encoding="utf-8")
    return target


class FileChooserNeeded(RuntimeError):
    pass


def extract_result(out):
    marker = "### Result"
    ran = "### Ran Playwright code"
    chunk = out
    if marker in out and ran in out:
        chunk = out.split(marker, 1)[1].split(ran, 1)[0].strip()
    if not chunk:
        return {}
    if chunk.startswith('"') or chunk.startswith("'"):
        chunk = json.loads(chunk)
    if isinstance(chunk, (dict, list)):
        return chunk
    try:
        return json.loads(chunk)
    except json.JSONDecodeError:
        return {"raw": str(chunk)[:4000]}


def _looks_like_filechooser(text):
    return "File chooser" in str(text or "") or "does not handle the modal" in str(text or "")


def _is_user_pause(exc):
    text = str(exc or "")
    if _looks_like_filechooser(text):
        return False
    if re.search(r"(?:^|\n)\s*(?:Error:\s*)?PAUSE:", text):
        return True
    head = text.split("### Ran Playwright code", 1)[0]
    return "REFUSE" in head


def _save_upload_security_diagnostic(text, name):
    marker = "UPLOAD_SECURITY_DIAGNOSTIC:"
    if marker not in text:
        return text
    message, detail = text.split(marker, 1)
    try:
        diagnostic, _ = json.JSONDecoder().raw_decode(detail.lstrip())
        diagnostic["script"] = name
        (get_output() / "web_fill_upload_security.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    except (ValueError, TypeError, OSError):
        pass  # The complete evidence remains in the raw CLI log.
    return message.rstrip()


def run_script(session, name, payload, timeout=120):
    if name != "checkpoint.js":
        _check_cancel(session)
    path = render_script(name, payload)
    try:
        out = session.cmd("run-code", f"--filename={path}", raw=False, timeout=timeout)
    except RuntimeError as exc:
        text = str(exc)
        out = get_output()
        raw_path = out / f"web_fill_{Path(name).stem}.raw.txt"
        out.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(text, encoding="utf-8", errors="replace")
        text = _save_upload_security_diagnostic(text, name)
        if _looks_like_filechooser(text):
            raise FileChooserNeeded(strip_cli_text(text)) from exc
        raise RuntimeError(strip_cli_text(text)) from exc
    raw_path = get_output() / f"web_fill_{Path(name).stem}.raw.txt"
    raw_path.write_text(out, encoding="utf-8", errors="replace")
    result = extract_result(out)
    if _looks_like_filechooser(out):
        if isinstance(result, dict) and (result.get("uploaded") is True or _upload_dispatched(result)):
            # A completed upload result wins over a stale modal notice. Never
            # turn an accepted/uncertain submission into another CLI upload.
            _dismiss_filechooser(session)
        else:
            raise FileChooserNeeded(strip_cli_text(out))
    if "### Error" in out and "### Result" not in out:
        error = _save_upload_security_diagnostic(out.split("### Error", 1)[-1].strip(), name)
        raise RuntimeError(strip_cli_text(error)[:800])
    (get_output() / f"web_fill_{Path(name).stem}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if isinstance(result, dict) and result.get("error") and str(result["error"]).startswith("PAUSE"):
        raise RuntimeError(result["error"])
    return result


def parse_tabs(text):
    tabs = []
    for line in str(text or "").splitlines():
        match = re.search(r"(https?://\S+)", line)
        if not match:
            continue
        index_match = re.search(r"(\d+)", line)
        tabs.append((int(index_match.group(1)) if index_match else len(tabs), match.group(1).rstrip("],)")))
    return tabs


def _is_category_url(url):
    return "category.htm" in str(url or "").lower()


def _is_reusable_publish(url, web):
    href = str(url or "")
    if not web.is_publish_page(href):
        return False
    low = href.lower()
    return "itemid=" not in low and "edit.htm" not in low and "item_num_id=" not in low


def _select_reusable_publish(session, web):
    try:
        listed = parse_tabs(session.tab_list())
    except Exception:
        return None
    candidates = [(index, url) for index, url in listed if _is_reusable_publish(url, web)]
    if not candidates:
        return None
    index, url = candidates[-1]
    try:
        session.tab_select(index)
        time.sleep(0.4)
    except Exception:
        return url
    current = (session.href() or url or "").strip()
    if _is_reusable_publish(current, web):
        return current
    return url if _is_reusable_publish(url, web) else None


def ensure_fill_tab(session, web=None, force_new=False):
    """优先接着已打开的新建发布页填，避免每次新开标签从头来。"""
    web = web or _load_web()
    session.attach()
    if force_new:
        # 上一条入库成功后，活动标签通常会停在它的 publish.htm?itemId=…
        # 编辑页，这是提交成功的正常形态；force_new 本来就要新开类目页，
        # 不复用也不检查这条旧标签。
        return ensure_new_category_tab(session, web), "new-category"
    href = (session.href() or "").strip()
    if _is_reusable_publish(href, web):
        return href, "reuse-publish"
    found = _select_reusable_publish(session, web)
    if found:
        return found, "reuse-publish"
    href = (session.href() or "").strip()
    if _is_category_url(href):
        web.assert_logged_in(href)
        return href, "reuse-category"
    try:
        listed = parse_tabs(session.tab_list())
    except Exception:
        listed = []
    for index, url in listed:
        if _is_category_url(url):
            session.tab_select(index)
            time.sleep(0.3)
            current = (session.href() or url or "").strip()
            if _is_category_url(current) or _is_category_url(url):
                web.assert_logged_in(current or url)
                return current or url, "reuse-category"
    return ensure_new_category_tab(session, web), "new-category"


def ensure_new_category_tab(session, web=None):
    web = web or _load_web()
    session.attach()
    # 当前活动标签可能是上一条成功商品残留的编辑页；本函数只新开类目标签、
    # 不在旧页上执行任何操作，因此不做 assert_safe_url（旧页含 itemId 属正常状态）。
    before = []
    try:
        before = parse_tabs(session.tab_list())
    except Exception:
        before = []
    before_indexes = {index for index, _ in before}
    session.tab_new(CATEGORY_ENTRY)
    listed = before
    for _ in range(15):
        time.sleep(0.4)
        try:
            listed = parse_tabs(session.tab_list())
        except Exception:
            listed = before
        new_cats = [(index, url) for index, url in listed if "category.htm" in url.lower() and index not in before_indexes]
        if not new_cats:
            new_cats = [(index, url) for index, url in listed if "category.htm" in url.lower()]
        if not new_cats:
            continue
        index, url = new_cats[-1]
        session.tab_select(index)
        current = (session.href() or url or "").strip()
        if "category.htm" not in current.lower():
            current = url
        if "category.htm" in current.lower():
            web.assert_safe_url(current)
            try:
                web.assert_logged_in(current, session.body_text(800))
            except Exception:
                web.assert_logged_in(current)
            return current
    raise RuntimeError("未能打开新的类目页标签，已停止以免覆盖当前发布页")


def _write_progress(steps):
    out = get_output()
    out.mkdir(parents=True, exist_ok=True)
    (out / "web_fill_progress.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def short_fail_notice(text):
    blob = " ".join(str(text or "").split())
    blob = re.sub(r"^(?:Error:\s*)+", "", blob)
    if "规格未写入" in blob or "无法新增规格行" in blob:
        hit = re.search(r"(规格未写入|无法新增规格行)\s*[^\"{]{0,40}", blob)
        return (hit.group(0) if hit else "规格未写入").strip()[:80]
    if "规格图未保存到SKU表格" in blob:
        return "规格图未保存到SKU表格"
    if "规格图未绑定" in blob:
        hit = re.search(r"规格图未绑定到SKU(?:\s+\d+/\d+)?", blob)
        return (hit.group(0) if hit else "规格图未绑定到SKU").strip()[:80]
    if re.search(r"timed out after \d+ seconds", blob, re.I) or "TimeoutExpired" in blob or (
        blob.startswith("Command") and "run-code" in blob
    ):
        if "attributes" in blob:
            return "填写属性超时，请重试"
        if "category" in blob:
            return "选择类目超时，请重试"
        if "warehouse" in blob:
            return "放入仓库超时，请重试"
        return "页面操作超时，请重试"
    blob = re.sub(r"上架时间\s*请根据实际需要[^\s。；;]{0,24}", " ", blob)
    blob = re.sub(r"请根据实际需要，?选择上架时间。?", " ", blob)
    parts = []
    for pattern in (
        r"错误\s*\(\d+\)",
        r"\d+\s*商品属性必填项未填",
        r"必填项未填",
        r"上架时间未选择",
        r"放入仓库未选中",
        r"[^\s；;]{1,40}未填",
        r"不能为空",
        r"PAUSE:[^\n]{1,80}",
    ):
        match = re.search(pattern, blob)
        if not match:
            continue
        piece = match.group(0).strip()
        if piece.startswith("PAUSE:"):
            piece = piece[6:].strip()
        if piece and piece not in parts:
            parts.append(piece)
    if parts:
        return "；".join(parts)[:200]
    if "帮助" in blob or "反馈" in blob:
        blob = re.sub(r"帮助|反馈", " ", blob)
        blob = " ".join(blob.split())
    return blob[:120]


def required_blockers(probe):
    if not isinstance(probe, dict):
        return []
    parts = []
    banners = [str(item) for item in (probe.get("banners") or [])]
    blob = " ".join(banners)
    match = re.search(r"错误\s*\([1-9]\d*\)", blob)
    if match:
        parts.append(match.group(0))
    attr = re.search(r"\d+\s*商品属性必填项未填", blob)
    if attr:
        parts.append(attr.group(0))
    elif "必填项未填" in blob:
        parts.append("必填项未填")
    empty = []
    for item in probe.get("empty") or []:
        name = str(item or "").strip()
        if name and name not in empty:
            empty.append(name)
    if empty:
        parts.append("、".join(empty) + "未填")
    if probe.get("warehouseOn") is False:
        parts.append("上架时间未选择")
    return parts


def _warehouse_on(ware, session, web):
    if isinstance(ware, dict) and "warehouseOn" in ware:
        return bool(ware.get("warehouseOn")) and not ware.get("instantOn")
    try:
        return web.warehouse_selected(session.snapshot())
    except Exception:
        return False


def _prepare_submit(session, payload, web, steps):
    ware = run_script(session, "warehouse.js", {}, timeout=40)
    steps.append({"step": "warehouse", "result": ware})
    _write_progress(steps)
    if not _warehouse_on(ware, session, web):
        ware = run_script(session, "warehouse.js", {}, timeout=40)
        steps.append({"step": "warehouse", "result": ware})
        _write_progress(steps)
    if not _warehouse_on(ware, session, web):
        return False, "放入仓库未选中，已停止以免立刻上架"
    probe = {}
    try:
        probe = run_script(session, "probe_errors.js", payload or {}, timeout=40)
    except Exception:
        probe = {}
    blockers = required_blockers(probe)
    if blockers:
        try:
            refill = run_script(session, "attributes.js", payload or {}, timeout=150)
            steps.append({"step": "attributes", "result": {"refill": True, "result": refill}})
            _write_progress(steps)
        except Exception as exc:
            steps.append({"step": "attributes", "result": {"refill": True, "error": str(exc)[:200]}})
        try:
            ware = run_script(session, "warehouse.js", {}, timeout=40)
            steps.append({"step": "warehouse", "result": ware})
        except Exception:
            pass
        try:
            probe = run_script(session, "probe_errors.js", payload or {}, timeout=40)
        except Exception:
            probe = {}
        blockers = required_blockers(probe)
        if blockers:
            return False, "；".join(blockers)[:200]
    if not _warehouse_on(ware, session, web) and probe.get("warehouseOn") is False:
        return False, "放入仓库未选中，已停止以免立刻上架"
    if probe.get("warehouseOn") is False:
        return False, "上架时间未选择"
    return True, ""


def _finish_publish(session, payload, confirm_submit, web, steps):
    snap = session.snapshot()
    ware = None
    if not web.warehouse_selected(snap):
        ware = run_script(session, "warehouse.js", {}, timeout=40)
        steps.append({"step": "warehouse", "result": ware})
        _write_progress(steps)
        snap = session.snapshot()
    if not _warehouse_on(ware, session, web) and not web.warehouse_selected(snap):
        raise RuntimeError("放入仓库未选中，已停止以免立刻上架")
    links = _empty_action_links()
    if confirm_submit:
        ready, reason = _prepare_submit(session, payload, web, steps)
        if not ready:
            return {
                "execution": "提交失败",
                "notice": reason,
                "errors": [reason],
                "steps": steps,
                "url": session.href(),
                **links,
            }
        _audit_spec_rows_before_submit(session, payload, steps)
        submitted = run_script(session, "submit.js", payload, timeout=60)
        steps.append({"step": "submit", "result": submitted})
        _write_progress(steps)
        execution, notice, links = _submit_outcome(session, submitted)
    else:
        execution = web.maybe_submit(session, False, snap)
        notice = "已选择放入仓库"
    result = {
        "execution": execution,
        "notice": notice,
        "errors": [],
        "steps": steps,
        "url": session.href(),
    }
    result.update(links)
    return result


def page_looks_in_progress(state, payload):
    if not isinstance(state, dict):
        return False
    title = str(state.get("title") or "")
    want = str((payload or {}).get("title") or "")
    if want and title and (want[:10] in title or title[:10] in want):
        return True
    if int(state.get("skuRows") or 0) > 0:
        return True
    if int(state.get("mainImgs") or 0) > 0:
        return True
    if int(state.get("p34Imgs") or 0) > 0:
        return True
    if int(state.get("detailImgs") or 0) > 0:
        return True
    if int(state.get("videos") or 0) > 0:
        return True
    if int(state.get("specImgs") or 0) > 0:
        return True
    return False


def _remember_item(product, item, status=None):
    try:
        import job_session
        flow = {
            key: item.get(key)
            for key in (
                "flow_version", "sku_image_strategy", "flow_stage", "spec_image_stage", "run_status",
                "sku_material_manifest", "material_result", "material_preview", "material_folder", "last_error",
            )
            if item.get(key) not in (None, "")
        }
        job_session.patch_execution(
            item.get("row", product.get("row")),
            item.get("product_id") or product.get("product_id"),
            item.get("execution") or "",
            notice=item.get("notice") or "",
            errors=item.get("errors"),
            status=status,
            extra={
                "taobao_item_id": item.get("taobao_item_id") or "",
                "view_url": item.get("view_url") or "",
                "edit_url": item.get("edit_url") or "",
                **flow,
            },
        )
    except Exception:
        pass


def _empty_action_links():
    return {"taobao_item_id": "", "view_url": "", "edit_url": ""}


def _submit_outcome(session, submitted):
    submitted = submitted or {}
    raw = submitted.get("notice") or submitted.get("text") or ""
    if submitted.get("hasSuccess") or not submitted.get("hasFail"):
        execution = "结果待核实"
        notice = short_fail_notice(raw) if submitted.get("hasFail") else (short_fail_notice(raw) or "已提交")
        item_id = re.search(r"商品ID[:：]\s*(\d{8,})", str(raw))
        if item_id and "商品ID" not in notice:
            notice = ("提交成功 商品ID: " + item_id.group(1) + (" " + notice if notice and notice != "已提交" else "")).strip()
    else:
        execution = "提交失败"
        notice = short_fail_notice(raw) or "提交失败"
    href = str(submitted.get("href") or "")
    try:
        if session:
            href = session.href() or href
    except Exception:
        pass
    links = dict(_empty_action_links())
    try:
        import job_session
        links = job_session.product_action_links(submitted=submitted, notice=notice, href=href)
    except Exception:
        pass
    return execution, notice, links


DONE_EXECUTIONS = frozenset({"已填写未提交", "结果待核实"})
KAYOU_ITEM_ID = "1085558349142"


def resolve_sku_strategy(product, explicit=""):
    """默认导入搜索主图；可单选规格图或顺序执行两类图片。"""
    strategy = explicit or product.get("sku_image_strategy") or "slim_material"
    if strategy not in {"slim_material", "publish_page", "both"}:
        raise ValueError("未知 SKU 图片处理方式")
    return strategy


SPEC_COLUMN_FLOW_VERSION = "spec-column-v1"
BOTH_IMAGE_FLOW_VERSION = "both-images-v1"
# 规格图分批补传的中间态：批次已保存但还有后续批次；既不是 submit_pending
# （会触发禁止重提守卫），也不是 complete（流程未结束）。
SPEC_STAGE_UPLOADING = "uploading"


def _as_state(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


class UserStopped(RuntimeError):
    pass


class SpecRowsMismatch(RuntimeError):
    """提交前规格行审计失败：页面规格行与输入不一致，禁止建品。

    fill_new_product 捕获该异常时会丢弃 skus/spec_images 断点标记，使条目级
    重试重新执行 SKU 步骤（导入 open 阶段识别"规格行已齐全"不会重复导入）。
    """


def _check_cancel(session):
    event = getattr(session, "cancel_event", None)
    if event is not None and event.is_set():
        raise UserStopped("PAUSE:用户已暂停；保留当前发布页，点击继续可接着填写")


def resume_key(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def display_title(title):
    result, size = [], 0
    for char in str(title or "").strip():
        width = 2 if ord(char) > 127 else 1
        if size + width > 60:
            break
        result.append(char)
        size += width
    return "".join(result)


def page_conflicts(state, payload):
    """True when the open publish page already holds a different product."""
    if not isinstance(state, dict):
        return False
    title = str(state.get("title") or "").strip()
    want = str((payload or {}).get("title") or "").strip()
    has_content = any(int(state.get(key) or 0) > 0 for key in ("skuRows", "specImgs", "mainImgs", "detailImgs", "p34Imgs"))
    if not title and not has_content:
        return False
    checkpoint = state.get("checkpoint") or {}
    if checkpoint.get("key"):
        if checkpoint["key"] != resume_key(payload):
            return True
        return bool(title and title not in {want, display_title(want)})
    if want and title:
        if title == want:
            return False
        # Legacy pages have no marker: truncated titles require matching SKU names,
        # so two products sharing the same title prefix are not silently mixed.
        expected = [str(s.get("name") or "").strip() for s in payload.get("skus", [])]
        return not (title == display_title(want) and expected
                    and expected == state.get("skuNames"))
    return bool(want and has_content)


def decide_skips(state, payload):
    """Already-filled sections on the current publish page. Conservative."""
    skips = set()
    if page_conflicts(state, payload):
        return skips
    if not page_looks_in_progress(state, payload):
        return skips
    want_skus = len((payload or {}).get("skus") or [])
    want_mains = len((payload or {}).get("main_images") or [])
    want_portraits = len((payload or {}).get("portrait_images") or [])
    want_details = len((payload or {}).get("detail_images") or [])
    want_video = bool((payload or {}).get("main_video"))
    sku_rows = int(state.get("skuRows") or 0)
    spec_imgs = int(state.get("specImgs") or 0)
    main_imgs = int(state.get("mainImgs") or 0)
    p34_imgs = int(state.get("p34Imgs") or 0)
    detail_imgs = int(state.get("detailImgs") or 0)
    videos = int(state.get("videos") or 0)
    spec_dialog = bool(state.get("specDialog"))
    popup = bool(state.get("popup"))
    checkpoint = state.get("checkpoint") or {}
    same_checkpoint = checkpoint.get("key") == resume_key(payload)
    title = str(state.get("title") or "").strip()
    want_title = str((payload or {}).get("title") or "").strip()
    title_present = bool(title and title in {want_title, display_title(want_title)})
    # A newly opened form can contain a default SKU row. With a media-first
    # checkpoint, that row is not evidence that attributes/SKUs were filled.
    sku_started = not same_checkpoint or bool(
        {"attributes", "skus"}.intersection(checkpoint.get("completed", [])))
    if same_checkpoint and not title_present:
        expected_names = [str(s.get("name") or "").strip() for s in payload.get("skus", [])]
        sku_started = bool(expected_names and expected_names == state.get("skuNames"))
    spec_incomplete = bool(want_skus) and spec_imgs < want_skus
    # A media-first upload popup does not mean attributes or SKUs are filled.
    if sku_started and (spec_dialog or popup) and spec_incomplete and sku_rows >= want_skus:
        skips.add("skus")
        if title_present:
            skips.add("attributes")
    if sku_started and want_skus and sku_rows >= want_skus:
        skips.add("skus")
    if sku_started and 0 < want_skus < 13 and spec_imgs >= want_skus:
        skips.add("spec_images")
    if want_mains and main_imgs >= want_mains:
        skips.add("main_images")
    if want_portraits and p34_imgs >= want_portraits:
        skips.add("portraits")
    if want_details and detail_imgs >= want_details:
        skips.add("details")
    # 只有我们自己的 checkpoint 记过 video 才按计数跳过；页面若自带视频
    # （无 checkpoint），交给 main_video.js 的 already 探测兜底，避免误跳过。
    if want_video and videos >= 1 and "video" in checkpoint.get("completed", []):
        skips.add("video")
    # Title is written by attributes.js. A checkpoint cannot override a cleared
    # title/form, including a refreshed page retaining old sessionStorage.
    if same_checkpoint and title_present and "attributes" in checkpoint.get("completed", []):
        skips.add("attributes")
    return skips


def _probe_fill_state(session, payload):
    try:
        return _as_state(run_script(session, "probe_state.js", payload, timeout=40))
    except UserStopped:
        raise
    except Exception:
        return {}


def _save_checkpoint(session, payload, completed):
    # Page-local storage survives restarting the assistant and refreshing this tab;
    # counts in probe_state remain authoritative if the user removes any content.
    return run_script(session, "checkpoint.js", {"key": resume_key(payload), "completed": sorted(completed)}, timeout=15)


def _audit_spec_rows_before_submit(session, payload, steps):
    """提交前审计：页面实际规格行必须与输入一致，防止带着缺失/多余规格建品。

    页面规格表是虚拟滚动表格，可视行数恒约一屏（37 行实测显示 17 行），必须
    用 sku_import.js 的 audit 阶段逐屏深扫描取全量。不一致时抛
    SpecRowsMismatch：fill_new_product 会丢弃 skus/spec_images 断点标记，
    条目级重试重新执行 SKU 步骤。审计本身不可用（脚本失败/页面结构变化）
    时不阻断提交，仍由建品后核验兜底。
    2026-10-01 事故：37 行输入建出 17 行规格的商品，提交前无任何校验。
    """
    skus = payload.get("skus") or []
    if not skus:
        return
    try:
        audit = run_script(session, "sku_import.js", {"phase": "audit", "skus": skus}, timeout=120)
    except Exception as exc:
        steps.append({"step": "sku_audit", "error": str(exc)[:200]})
        _write_progress(steps)
        return
    steps.append({"step": "sku_audit", "result": audit})
    _write_progress(steps)
    if not isinstance(audit, dict) or not audit.get("audit"):
        return
    total = int(audit.get("count") or 0)
    missing = [str(name) for name in (audit.get("missing") or [])]
    extra = [str(name) for name in (audit.get("extra") or [])]
    if total == len(skus) and not missing and not extra:
        return
    detail = f"页面 {total} 行 / 输入 {len(skus)} 行"
    if missing:
        detail += f"；缺失 {'、'.join(missing[:3])}" + ("等" if len(missing) > 3 else "")
    if extra:
        detail += f"；多出 {'、'.join(extra[:3])}" + ("等" if len(extra) > 3 else "")
    raise SpecRowsMismatch(
        f"PAUSE:提交前页面规格行与输入不符（{detail}）；已重置 SKU 步骤断点，"
        "重试将重新处理 SKU，不带着缺失规格建品")


def _maybe_close_overlays(session):
    try:
        run_script(session, "close_overlays.js", {}, timeout=40)
    except Exception:
        pass


def select_kayou_tab(session, allow_item_id=KAYOU_ITEM_ID):
    tabs = session.tab_list()
    ranked = []
    for index, url in parse_tabs(tabs):
        low = url.lower()
        if "deli" in low or "%E5%BE%97%E5%8A%9B" in url or "s11" in low:
            continue
        if allow_item_id and allow_item_id in url:
            if "publish.htm" in low:
                ranked.append((0, index, url))
            elif "success.htm" in low:
                ranked.append((2, index, url))
            else:
                ranked.append((1, index, url))
        elif "publish.htm" in url and "%E5%8D%A1%E6%B8%B8" in url:
            if "itemid=" in low and (not allow_item_id or allow_item_id not in url):
                continue
            ranked.append((3, index, url))
    if not ranked:
        raise RuntimeError("未找到卡游页标签（成功页/编辑页/发布页）")
    ranked.sort()
    _, index, url = ranked[0]
    session.tab_select(index)
    time.sleep(0.5)
    return url


def _dismiss_filechooser(session):
    # Escape does not clear Playwright CLI's tracked fileChooser modal state.
    # `upload` without paths cancels it without setting any files. Drain old
    # duplicate notices with a bounded loop, then leave normal UI keys alone.
    for _ in range(4):
        try:
            result = session.cmd("upload", raw=False, timeout=20)
            if not _looks_like_filechooser(result):
                return
        except Exception:
            break
    try:
        session.press("Escape")
        time.sleep(0.3)
    except Exception:
        pass


UPLOAD_RETRY_LIMIT = 2
SPEC_UPLOAD_BATCH_SIZE = 1
SPEC_UPLOAD_BATCH_DELAY_MIN_MS = 5000
SPEC_UPLOAD_BATCH_DELAY_MAX_MS = 10000
# 串行上传并等待回执；跨阶段的共享限速由上传助手执行。
MAIN_UPLOAD_BATCH_SIZE = 1
MAIN_UPLOAD_BATCH_DELAY_MIN_MS = 4000
MAIN_UPLOAD_BATCH_DELAY_MAX_MS = 9000
RETRYABLE_UPLOAD_RE = re.compile(
    r"网络错误|请稍后重试|请尝试禁止浏览器插件|换浏览器或者换电脑重试"
)


def _human_upload_policy():
    return {
        "uploadPacing": True,
        "contentAddressedMedia": True,
        "uploadBatchSize": MAIN_UPLOAD_BATCH_SIZE,
        "uploadBatchDelayMinMs": MAIN_UPLOAD_BATCH_DELAY_MIN_MS,
        "uploadBatchDelayMaxMs": MAIN_UPLOAD_BATCH_DELAY_MAX_MS,
    }


def _paced_upload_timeout(file_count, options=None):
    """Budget for cooldown plus the slowest recovery rate, in seconds."""
    custom = (options or {}).get("uploadPacingOptions") or {}

    def number(key, fallback, low, high):
        try:
            value = float(custom.get(key, fallback))
            if not math.isfinite(value):
                value = fallback
        except (TypeError, ValueError):
            value = fallback
        return max(low, min(high, value))

    base = number("backoffBaseMs", 120000, 1000, 900000)
    cooldown = max(base, number("backoffMaxMs", 900000, 1000, 3600000))
    initial = number("initialDelayMs", 12000, 0, 120000)
    gap = max(number("minGapMs", 12000, 0, 120000),
              number("maxGapMs", 18000, 0, 120000))
    # JS limits recovery to 8x / 120s, and to one file per rolling window.
    recovery_wait = max(min(120000, gap * 8), number("windowMs", 60000, 1000, 300000))
    # Each file additionally needs receipt verification and picker work.
    return math.ceil(60 + (cooldown + initial) / 1000
                     + max(0, file_count) * (recovery_wait / 1000 + 90))


def _upload_status(result):
    if not isinstance(result, dict):
        return {}
    status = result.get("status")
    return status if isinstance(status, dict) else result


def _upload_dispatched(result):
    if not isinstance(result, dict):
        return False
    return bool(result.get("dispatched") or result.get("dispatchUncertain")
                or result.get("setFiles") == "OK"
                or _upload_dispatched(result.get("uploadStatus")))


def _status_text(result):
    data = result if isinstance(result, dict) else {}
    status = _upload_status(data)
    parts = []
    for blob in (data, status):
        if not isinstance(blob, dict):
            continue
        parts.extend(str(x) for x in (blob.get("snippet") or []) if x)
        parts.extend(str(x) for x in (blob.get("failedNames") or []) if x)
        for key in ("error", "after_err", "msg"):
            if blob.get(key):
                parts.append(str(blob[key]))
    return " ".join(parts)


def retryable_upload_failure(result):
    data = result if isinstance(result, dict) else {}
    status = _upload_status(data)
    if any(data.get(key) or status.get(key) for key in ("retryable", "networkError")):
        return True
    return bool(RETRYABLE_UPLOAD_RE.search(_status_text(data)))


def failed_upload_names(result):
    data = result if isinstance(result, dict) else {}
    status = _upload_status(data)
    failed = [str(name) for name in (data.get("failedNames") or status.get("failedNames") or []) if name]
    if failed:
        return failed
    missing = [str(name) for name in (data.get("missing") or []) if name]
    if missing and (retryable_upload_failure(data) or data.get("uploaded") is False or status.get("fail")):
        return missing
    return []


def _files_named(files, names):
    want = {str(name) for name in (names or [])}
    return [path for path in (files or []) if Path(path).name in want]


def _retry_failed_image_uploads(session, script, payload, files, opened, uploaded, attempts=UPLOAD_RETRY_LIMIT):
    _check_cancel(session)
    current = uploaded
    log = []
    # Main/detail uploads are single-dispatch: a missing receipt is not proof
    # that the server rejected the file. Leave uncertain uploads for review.
    if script in {"main_images.js", "details.js"}:
        return current, log
    seen_retryable = retryable_upload_failure(opened) or retryable_upload_failure(uploaded)
    for attempt in range(1, max(1, attempts) + 1):
        if isinstance(current, dict) and (current.get("uploaded") is True
                                         or _upload_status(current).get("uploading")):
            break
        failed = failed_upload_names(current) or (failed_upload_names(opened) if attempt == 1 else [])
        if not failed:
            break
        # A closed/absent upload popup can hide a partial batch. A library
        # search that names the missing files is enough to retry only those.
        if not (retryable_upload_failure(current) or seen_retryable
                or (isinstance(current, dict) and current.get("uploaded") is False
                    and current.get("missing"))):
            break
        seen_retryable = True
        retry_files = _files_named(files, failed) or list(files or [])
        if not retry_files:
            break
        entry = {"attempt": attempt, "files": [Path(path).name for path in retry_files]}
        time.sleep(1.2 + (attempt - 1))
        try:
            entry["rest"] = _upload_one_by_one(session, retry_files, payload if script == "spec_images.js" else None)
        except FileChooserNeeded:
            try:
                session.upload_files(*retry_files[:1], timeout=90)
                entry["via"] = "chooser"
            except Exception as exc:
                entry["err"] = str(exc)[:160]
                log.append(entry)
                break
        except RuntimeError as exc:
            if _is_user_pause(exc):
                raise
            if script != "spec_images.js" or "未确认" not in str(exc):
                entry["err"] = str(exc)[:160]
                log.append(entry)
                break
            # The picker often closes its result panel before the CLI sees it.
            # Check the material library after the attempted upload.
            entry["unconfirmed"] = str(exc)[:160]
        except Exception as exc:
            if _is_user_pause(exc):
                raise
            entry["err"] = str(exc)[:160]
            log.append(entry)
            break
        try:
            current = run_script(session, script, {**payload, "phase": "after_upload", "files": retry_files}, timeout=180)
        except FileChooserNeeded:
            _dismiss_filechooser(session)
            entry["after"] = "filechooser"
            log.append(entry)
            break
        except Exception as exc:
            if _is_user_pause(exc):
                raise
            current = {"after_err": str(exc)[:200]}
            entry["after_err"] = str(exc)[:160]
            log.append(entry)
            break
        log.append(entry)
    if log and isinstance(current, dict):
        current = {**current, "cli_retries": log}
    return current, log


def _try_cli_upload(session, files, timeout=90, spec_upload=False):
    _check_cancel(session)
    files = [path for path in (files or []) if path]
    if not files:
        return {"via": "skip"}
    try:
        session.upload_files(*files[:1], timeout=timeout)
        time.sleep(random.uniform(SPEC_UPLOAD_BATCH_DELAY_MIN_MS, SPEC_UPLOAD_BATCH_DELAY_MAX_MS) / 1000
                   if spec_upload else 0.6)
        return {"via": "cli_modal", "first": Path(files[0]).name}
    except Exception as exc:
        if _is_user_pause(exc):
            raise
        _dismiss_filechooser(session)
        return {"via": "cli_fail", "error": str(exc)[:200]}


def _clear_filechooser(session, files):
    if files:
        session.upload_files(*files, timeout=180)
        time.sleep(1.0)
        return {"via": "cli_modal"}
    _dismiss_filechooser(session)
    return {"via": "escape"}


def _upload_or_set(session, open_result, files, after_script, extra):
    if open_result.get("need_cli_upload") or open_result.get("error") == "NO_INPUT":
        session.upload_files(*files, timeout=180)
        return run_script(session, after_script, {**extra, "phase": "after_upload", "files": files}, timeout=120)
    if open_result.get("uploaded"):
        try:
            closed = run_script(session, after_script, {**extra, "phase": "after_upload", "files": files}, timeout=120)
            return {**open_result, "after": closed}
        except Exception as exc:
            return {**open_result, "after_err": str(exc)[:200]}
    if open_result.get("error"):
        raise RuntimeError(open_result["error"])
    return open_result


def _upload_one_by_one(session, files, upload_options=None):
    _check_cancel(session)
    # Keep the entry point, but let JS pace single-dispatch uploads through the
    # initialized input. Never race that script with a native chooser upload.
    remaining = list(files)
    log = []
    while remaining:
        try:
            options = {key: upload_options[key] for key in (
                "uploadBatchSize", "uploadBatchDelayMinMs", "uploadBatchDelayMaxMs",
                "uploadPacing", "uploadPacingOptions",
            ) if isinstance(upload_options, dict) and key in upload_options}
            options.setdefault("uploadBatchSize", 1)
            options.setdefault("uploadPacing", True)
            batch_size = max(1, int(options["uploadBatchSize"]))
            batch_count = (len(remaining) + batch_size - 1) // batch_size
            timeout = min(900, max(90, 60 + 30 * batch_count + 10 * max(0, batch_count - 1)))
            if options["uploadPacing"]:
                timeout = max(timeout, _paced_upload_timeout(len(remaining), options))
            result = run_script(session, "upload_files.js", {"files": list(remaining), **options}, timeout=timeout)
        except FileChooserNeeded as exc:
            _dismiss_filechooser(session)
            raise RuntimeError(
                "PAUSE:图片上传出现残留文件选择器，上传结果不明确，已停止重复提交；请确认图片状态后继续"
            ) from exc
        if result.get("uploaded") is not True:
            detail = []
            status = _upload_status(result)
            detail.append(f"dispatched={result.get('dispatched')}")
            if status.get("uploading"):
                detail.append("上传中")
            if status.get("fail"):
                detail.append("失败标记")
            if status.get("successCount") is not None:
                detail.append(f"成功 {status.get('successCount')}/{len(remaining)}")
            if result.get("failedNames"):
                detail.append(f"失败文件: {result['failedNames']}")
            if result.get("missing"):
                detail.append(f"素材库未找到: {result['missing']}")
            if result.get("batches"):
                for batch in result["batches"][-3:]:
                    detail.append(f"批次{batch.get('index')}: uploaded={batch.get('uploaded')}, verifiedBy={batch.get('verifiedBy')}, error={batch.get('error')}")
            if result.get("verifiedBy"):
                detail.append(f"验证方式: {result['verifiedBy']}")
            reason = "; ".join(detail) or "无状态信息"
            raise RuntimeError(f"图片上传失败：批量上传未确认成功，已停止后续图片 [{reason}]")
        log.append({"via": "batch", "count": len(remaining), "result": result})
        return log
    return log


def pick_from_library(session, script, payload):
    opened = {}
    try:
        opened = run_script(session, script, {**payload, "phase": "open_library"}, timeout=90)
    except FileChooserNeeded:
        files = payload.get("files") or [s.get("image") for s in (payload.get("skus") or []) if s.get("image")]
        if files:
            session.upload_files(files[0], timeout=90)
            time.sleep(0.8)
        opened = {"via": "cli_modal"}
    phase = "bind" if script == "spec_images.js" else "select"
    try:
        picked = run_script(session, script, {**payload, "phase": phase, "files": payload.get("files") or []}, timeout=180)
    except FileChooserNeeded:
        try:
            session.press("Escape")
        except Exception:
            pass
        picked = run_script(session, script, {**payload, "phase": phase}, timeout=180)
    return {"open": opened, "pick": picked}


def _scoped_skus(payload, only_rows):
    """only_rows 为 0 基行号；None 表示全量。"""
    skus = list((payload or {}).get("skus") or [])
    if only_rows is None:
        return skus
    return [skus[int(i)] for i in sorted({int(i) for i in only_rows if 0 <= int(i) < len(skus)})]


def spec_images_unbound(step, payload, only_rows=None):
    need = len([item for item in _scoped_skus(payload, only_rows) if item.get("image")])
    if not need or not isinstance(step, dict):
        return False
    bound = step.get("bind") if isinstance(step.get("bind"), dict) else step
    if not isinstance(bound, dict):
        return False
    # The picker can report every card selected even when the drawer did not persist images.
    # Treat the explicit persistence result as authoritative before falling back to legacy bind logs.
    if bound.get("saved") is False:
        return True
    if bound.get("saved") is True:
        return False
    filled = bound.get("filledCount")
    if filled is not None:
        try:
            return int(filled) < need
        except (TypeError, ValueError):
            return False
    log = bound.get("bindLog")
    if not isinstance(log, list) or not log:
        return False
    ok = 0
    miss = 0
    for item in log:
        pic = item.get("picClick") or item.get("pic") or {}
        click = item.get("skuClick")
        if isinstance(click, dict):
            click = str(click.get("how") or "")
        else:
            click = str(click or "")
        if pic.get("ok") or click == "HAS_IMG":
            ok += 1
        elif click.startswith("NO_") or click in {"NO_DIALOG", "NO_ROW", "NO_EMPTY"}:
            miss += 1
    return ok == 0 and miss == len(log)


GATE_RETRY_LIMIT = 5
HARD_PAUSE_WORDS = ("登录", "验证码", "滑块")

# 结构化暂停码：PAUSE:<code>:<文案>。code 供跨层分类（jobs/桌面端），
# 文案可随意调整；没有显式 code 时按 HARD_PAUSE_WORDS 关键词兜底归类。
PAUSE_CODE_LOGIN = "login"
PAUSE_CODE_CAPTCHA = "captcha"
PAUSE_CODE_SLIDER = "slider"
PAUSE_REASON_LABELS = {
    PAUSE_CODE_LOGIN: "登录",
    PAUSE_CODE_CAPTCHA: "验证码",
    PAUSE_CODE_SLIDER: "滑块",
}
PAUSE_CODE_PATTERN = re.compile(r"PAUSE[:：]\s*(login|captcha|slider)\b", re.IGNORECASE)


def hard_pause_reason(text):
    blob = str(text or "")
    for word in HARD_PAUSE_WORDS:
        if word in blob:
            return word
    return ""


def pause_reason_code(text):
    """安全验证类硬暂停的原因码：login/captcha/slider；非硬暂停返回空串。"""
    blob = str(text or "")
    match = PAUSE_CODE_PATTERN.search(blob)
    if match:
        return match.group(1).lower()
    word = hard_pause_reason(blob)
    for code, label in PAUSE_REASON_LABELS.items():
        if word and word == label:
            return code
    return ""


def gate_error_retryable(exc):
    text = str(exc or "")
    if "素材卡片点击后规格行仍为空" in text or "图片空间仍在上传" in text:
        return False
    if hard_pause_reason(text) or pause_reason_code(text):
        return False
    notice = short_fail_notice(text) or text
    blob = text + " " + notice
    needles = (
        "规格未写入",
        "无法新增规格行",
        "规格图未绑定",
        "规格图未保存到SKU表格",
        "图片上传结果弹窗未关闭",
        "未找到编辑规格",
        "规格抽屉",
        "书写粗细",
        "超时",
        "timed out",
        "TimeoutExpired",
        "未进入新建发布页",
        "类目页",
        "放入仓库未选中",
        "NO_FRAME",
        "PAUSE:",
        "File chooser",
    )
    return any(item in blob for item in needles)


# 条目级自动重试的黑名单：命中任一标记的失败不重试，直接标记后跳下一条。
# 只保留真正不该重试的两类：
# 1. 结果不明确类（上传/提交/保存结果无法确认）——按规则禁止自动重复执行；
# 2. 安全限制类（操作过于频繁）——立即重试会加重风控惩罚。
# 登录/验证码/滑块由 hard_pause_reason/pause_reason_code 单独判定。
# 注意："SKU 模板已上传但结果未核实"（导入 verify 脚本崩溃）不在黑名单——
# 重试重新执行 SKU 步骤是安全的：导入 open 阶段识别"规格行已齐全"（already）
# 不会重复导入，提交前还有规格行审计兜底，不会建出错误商品。
# 数据核对类失败（服务端商品与输入不符、SKU 行数不符、价格库存变化等）
# 同样允许重试：重试走只读核验/断点续跑路径，不会重复建品。
ITEM_NO_RETRY_MARKERS = (
    "残留文件选择器",
    "结果不明确",
    "结果待核实",
    "禁止自动重复",
    "操作过于频繁",
)


def item_retryable_notice(notice, errors=()):
    """条目级自动重试的准入判定：明确失败才重试。

    安全验证（登录/验证码/滑块）与结果不明确类一律不可重试，遵守
    "上传或采纳结果不明确时不得自动重复执行"；其余明确失败（超时、
    元素未找到、规格未写入等）允许按设置的重试次数自动重试。
    """
    blob = " ".join([str(notice or ""), *(str(e) for e in (errors or []) if e)])
    if not blob.strip():
        return False
    if hard_pause_reason(blob) or pause_reason_code(blob):
        return False
    return not any(marker in blob for marker in ITEM_NO_RETRY_MARKERS)


def _spec_unbound_error(specs, payload, only_rows=None):
    bound = specs.get("bind") if isinstance(specs.get("bind"), dict) else {}
    filled = bound.get("filledCount")
    need = len([item for item in _scoped_skus(payload, only_rows) if item.get("image")])
    if bound.get("saved") is False:
        return RuntimeError("规格图未保存到SKU表格")
    extra = (" " + str(filled) + "/" + str(need)) if filled is not None else ""
    return RuntimeError("规格图未绑定到SKU" + extra)


def _spec_frame_error(specs):
    bound = specs.get("bind") if isinstance(specs, dict) and isinstance(specs.get("bind"), dict) else {}
    diagnostics = bound.get("diagnostics") if isinstance(bound.get("diagnostics"), dict) else {}
    parts = []
    if diagnostics.get("url"):
        parts.append("页面=" + str(diagnostics["url"])[:180])
    if diagnostics.get("dialog") is not None:
        parts.append("弹窗=" + str(diagnostics.get("dialog")))
    frame_urls = diagnostics.get("frameUrls")
    if isinstance(frame_urls, list):
        parts.append("iframe=" + (" | ".join(str(url)[:120] for url in frame_urls[-4:]) or "无"))
    return RuntimeError("规格图素材库 iframe 未加载" + ("；" + "；".join(parts) if parts else ""))


def _clear_gate_overlays(session):
    try:
        run_script(session, "close_overlays.js", {}, timeout=20)
    except Exception:
        pass
    try:
        session.press("Escape")
    except Exception:
        pass


def run_gate(session, name, payload, steps, step, timeout=120, attempts=GATE_RETRY_LIMIT):
    last = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            result = run_script(session, name, payload, timeout=timeout)
            steps.append({"step": step, "result": result, "attempt": attempt})
            _write_progress(steps)
            return result
        except Exception as exc:
            last = exc
            steps.append({"step": step, "attempt": attempt, "error": short_fail_notice(str(exc)) or str(exc)[:160]})
            _write_progress(steps)
            if (not gate_error_retryable(exc)) or attempt >= attempts:
                raise
            _clear_gate_overlays(session)
            time.sleep(0.7 + (attempt - 1) * 0.5)
    raise last


def _spec_row_image_step(session, payload, on_bind_progress=None, only_indexes=None):
    """Bind large SKU sets through the image control beside each SKU name.

    only_indexes 为 0 基行号；分批补图时只绑定这些行，表格审计也只复核这些行，
    其余尚未补图的行留给后续批次。
    """
    specs = list(payload.get("skus") or [])
    total = len(specs)
    if only_indexes is None:
        indexes = list(range(total))
    else:
        indexes = sorted({int(i) for i in only_indexes if 0 <= int(i) < total})
    only_set = set(indexes)
    bind_log = []
    expected_sources = {}
    local_hashes = {}
    for index, spec in enumerate(specs, 1):
        image = spec.get("image")
        if image and Path(image).is_file():
            local_hashes[index] = hashlib.sha256(Path(image).read_bytes()).hexdigest()
    def bind_row(index, force_replace=False):
        image = specs[index].get("image")
        if not image:
            return {"index": index, "saved": True, "skipped": True}
        if Path(image).is_file():
            image = _prepare_media_uploads([image], compact=True)[0]
        args = {**_human_upload_policy(), "index": index, "image": image,
                "repairItemId": payload.get("repairItemId")}
        for attempt in range(1, 2):
            _check_cancel(session)
            try:
                args["forceReplace"] = force_replace or attempt > 1
                opened = run_script(session, "spec_row_images.js", {**args, "phase": "open"}, timeout=70)
                if opened.get("already"):
                    result = opened
                else:
                    time.sleep(1)
                    try:
                        result = run_script(session, "spec_row_images.js", {**args, "phase": "select"}, timeout=240)
                    except FileChooserNeeded:
                        session.upload_files(image, timeout=90)
                        result = run_script(session, "spec_row_images.js", {**args, "phase": "finish"}, timeout=240)
                    if result.get("needsFinish"):
                        result = run_script(session, "spec_row_images.js", {**args, "phase": "finish"}, timeout=240)
                if result.get("saved") is not True:
                    raise RuntimeError(f"第 {index + 1} 行规格图未写入SKU表格")
                if not result.get("imageSrc"):
                    raise RuntimeError(f"第 {index + 1} 行规格图缺少图片地址，无法复核")
                expected_sources[index + 1] = result["imageSrc"]
                return {"index": index, "attempt": attempt, **result}
            except Exception as exc:
                # Selecting or uploading may already have succeeded when the
                # response is lost. Preserve the page and let a later run read
                # the SKU cell before doing anything else.
                if isinstance(exc, UserStopped) or _is_user_pause(exc):
                    raise
                raise RuntimeError(f"PAUSE:第 {index + 1} 行规格图结果不明确；已保留页面，续跑先核验当前图片：{exc}") from exc

    for position, index in enumerate(indexes, 1):
        bind_log.append(bind_row(index))
        if on_bind_progress:
            on_bind_progress(position, len(indexes))

    # Taobao can repaint an earlier row after a later image is selected. Audit
    # the whole table and replace mismatched/ambiguous rows, not just empty ones.
    for audit in range(3):
        time.sleep(1.5)
        state = run_script(session, "spec_row_status.js", {}, timeout=40)
        missing = [int(row) - 1 for row in (state.get("missing") or [])]
        missing = [index for index in missing if index in only_set]
        actual_sources = {int(row["index"]): row.get("src") for row in (state.get("sources") or [])}
        wrong = [index - 1 for index, src in expected_sources.items()
                 if actual_sources.get(index) != src]
        repair = sorted(set(missing + wrong))
        if state.get("total") != total:
            raise RuntimeError(f"规格图表格行数不符：预期 {total} 行，页面 {state.get('total')} 行")
        source_rows = {}
        for index, src in actual_sources.items():
            if src:
                source_rows.setdefault(src, []).append(index)
        conflicting = [rows for rows in source_rows.values()
                       if len({local_hashes[index] for index in rows if index in local_hashes}) > 1]
        conflict_rows = {index - 1 for rows in conflicting for index in rows} & only_set
        repair = sorted(set(repair) | conflict_rows)
        if repair:
            diagnostic = get_output() / "spec_row_image_recovery.json"
            diagnostic.parent.mkdir(parents=True, exist_ok=True)
            diagnostic.write_text(json.dumps({
                "audit": audit + 1, "repairRows": [index + 1 for index in repair],
                "expectedSources": expected_sources, "state": state,
                "localHashes": local_hashes, "bindLog": bind_log,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        if not repair:
            return {
                "open": {"via": "individual-sku-images", "uploadBatchSize": 1,
                         "pickerReopenedPerRow": True},
                "upload": {"uploaded": True, "verifiedBy": "sku-table"},
                "bind": {"saved": True, "filledCount": len([src for src in actual_sources.values() if src]),
                         "verifiedBy": "sku-table",
                         "bindLog": bind_log, "auditPasses": audit + 1,
                         "distinctImages": len(set(actual_sources.values())),
                         "unverifiedExistingCount": sum(bool(x.get("already")) for x in bind_log)},
            }
        if audit < 2:
            for index in repair:
                bind_log.append({"auditRepair": True, **bind_row(index, force_replace=True)})
    raise RuntimeError("规格图最终复核仍有缺失或错配行：" + ", ".join(str(i + 1) for i in repair))


def spec_images_gate(session, payload, steps, attempts=1, only_rows=None,
                     progress_offset=0, progress_total=None, min_filled_count=0):
    """上传并绑定规格图。

    only_rows 为 0 基行号：分批补图时只处理这些行（上传文件、绑定、审计均限定
    在本批行内）；progress_offset/progress_total 让逐行进度按全局行号显示；
    min_filled_count 是本批结束时抽屉里应至少已填的行数（含之前批次）。
    """
    skus = list(payload.get("skus") or [])
    if only_rows is None:
        scoped_skus = skus
    else:
        only_rows = sorted({int(i) for i in only_rows if 0 <= int(i) < len(skus)})
        scoped_skus = [skus[i] for i in only_rows]
    spec_files = list(dict.fromkeys(item["image"] for item in scoped_skus if item.get("image")))
    last = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            def report_bind_progress(done, total):
                shown_total = len(skus) if progress_total is None else progress_total
                shown_done = done + progress_offset if only_rows is not None else done
                _write_progress(steps + [{"step": "spec_images",
                                          "progress": f"{shown_done}/{shown_total}",
                                          "attempt": attempt}])

            upload_payload = {
                **payload,
                "uploadPacing": True,
                "uploadBatchSize": SPEC_UPLOAD_BATCH_SIZE,
                "uploadBatchDelayMinMs": SPEC_UPLOAD_BATCH_DELAY_MIN_MS,
                "uploadBatchDelayMaxMs": SPEC_UPLOAD_BATCH_DELAY_MAX_MS,
            }
            if only_rows is not None:
                upload_payload["onlyRows"] = only_rows
                # JS 侧 open 阶段缺省按全部 SKU 图判断素材库缺失；分批时显式限定本批文件。
                upload_payload["files"] = spec_files
                if min_filled_count:
                    upload_payload["minFilledCount"] = int(min_filled_count)
            if len(skus) >= 13:
                specs = _spec_row_image_step(session, upload_payload,
                                             on_bind_progress=report_bind_progress,
                                             only_indexes=only_rows)
            else:
                specs = _image_step(session, "spec_images.js", upload_payload, spec_files,
                                    on_bind_progress=report_bind_progress)
            steps.append({"step": "spec_images", "attempt": attempt, **specs})
            _write_progress(steps)
            bound = specs.get("bind") if isinstance(specs, dict) else None
            if isinstance(bound, dict) and bound.get("hadFrame") is False:
                raise _spec_frame_error(specs)
            if spec_images_unbound(specs, payload, only_rows=only_rows):
                raise _spec_unbound_error(specs, payload, only_rows=only_rows)
            return specs
        except Exception as exc:
            last = exc
            if "spec_images" not in str((steps[-1] or {}).get("step") if steps else ""):
                steps.append({"step": "spec_images", "attempt": attempt, "error": short_fail_notice(str(exc)) or str(exc)[:160]})
                _write_progress(steps)
            if (not gate_error_retryable(exc)) or attempt >= attempts:
                raise
            _clear_gate_overlays(session)
            time.sleep(0.7 + (attempt - 1) * 0.5)
    raise last


def _verify_image_binding(script, payload, bound):
    if script not in {"main_images.js", "details.js"}:
        return
    names = payload.get("names") or [Path(path).name for path in payload.get("files") or []]
    group = "主图" if script == "main_images.js" else "详情图"
    if not isinstance(bound, dict):
        raise RuntimeError(f"{group}选图失败：未返回结果")
    if bound.get("error"):
        raise RuntimeError(f"{group}选图失败：{bound['error']}")
    items = bound.get("selected") if script == "main_images.js" else bound.get("picked")
    if not isinstance(items, list) or len(items) != len(names):
        raise RuntimeError(f"{group}选图数量不符：图片包 {len(names)} 张，选中 {len(items) if isinstance(items, list) else 0} 张")
    failed = [item.get("name") if isinstance(item, dict) else "未知图片" for item in items
              if not isinstance(item, dict) or not isinstance(item.get("pic", item), dict)
              or not item.get("pic", item).get("ok")]
    if failed:
        raise RuntimeError(f"{group}未选中：{', '.join(str(name) for name in failed)}")
    result = bound.get("slot") if script == "main_images.js" else bound.get("after")
    actual = result.get("imgs") if isinstance(result, dict) else None
    if actual != len(names):
        raise RuntimeError(f"{group}写入数量不符：图片包 {len(names)} 张，页面 {actual if actual is not None else '未知'} 张")
    if script == "details.js" and (bound.get("confirm") == "NO" or result.get("dialog")):
        raise RuntimeError("详情图选择窗口未确认关闭，图片可能未写入")


def _media_upload_name(path, content=None):
    source = Path(path)
    content = source.read_bytes() if content is None else content
    return "qn_" + hashlib.sha256(content).hexdigest()[:24] + "_" + source.name


def _prepare_media_uploads(files, compact=False):
    """Stage copies with content-addressed names; never rename source photos."""
    directory = get_output() / "media-upload-cache"
    directory.mkdir(parents=True, exist_ok=True)
    staged = []
    for path in files:
        source = Path(path)
        content = source.read_bytes()
        upload_name = ("qn_" + hashlib.sha256(content).hexdigest()[:24] + source.suffix.lower()
                       if compact else _media_upload_name(source, content))
        target = directory / upload_name
        if not target.is_file() or target.read_bytes() != content:
            target.write_bytes(content)
        staged.append(target.resolve().as_posix())
    return staged


def _image_step(session, script, payload, files, on_bind_progress=None):
    if script in {"main_images.js", "details.js"} and payload.get("contentAddressedMedia"):
        files = _prepare_media_uploads(files)
        payload = {**payload, "files": files, "names": [Path(path).name for path in files]}
    opened = {"skipped": True}
    pick_phase = "bind" if script == "spec_images.js" else "select"
    pending_files = files
    def upload_pending(paths):
        try:
            return _upload_one_by_one(session, paths, payload)
        except RuntimeError as exc:
            if _is_user_pause(exc):
                raise
            if script != "spec_images.js":
                raise
            # The result popup can disappear before CLI inspects it. Verify the
            # requested files in the material library during after_upload.
            return {"unconfirmed": str(exc)[:200]}
    try:
        batch_size = max(1, int(payload.get("uploadBatchSize") or len(files) or 1))
        batch_count = (len(files) + batch_size - 1) // batch_size
        open_timeout = min(900, max(180, 60 + batch_count * 45 + max(0, batch_count - 1) * 10))
        if payload.get("uploadPacing"):
            # Include cooldown and the slower post-failure recovery window.
            # Timing out a still-running script can create a second producer.
            open_timeout = max(open_timeout, _paced_upload_timeout(len(files), payload))
        opened = run_script(session, script, {**payload, "phase": "open"}, timeout=open_timeout)
    except FileChooserNeeded:
        # run-code can yield on a chooser while its script continues uploading.
        # Cancel only the chooser and verify the receipt/library; sending even
        # the first file here races with setInputFiles and duplicates the image.
        _dismiss_filechooser(session)
        opened = {"via": "filechooser-dismissed", "dispatchUncertain": True}
    else:
        if script == "spec_images.js" and opened.get("missing"):
            pending_files = _files_named(files, opened["missing"]) or files
        already = bool(
            opened.get("already")
            or opened.get("via") == "library"
            or opened.get("skipUpload")
        )
        if already:
            opened["uploaded"] = True
        elif (opened.get("need_cli_upload") and pending_files
              and not _upload_dispatched(opened)):
            opened["rest"] = upload_pending(pending_files)
        elif script == "spec_images.js" and (opened.get("hadFrame") is False or opened.get("error")):
            # 规格图必须先进入素材库选择器；这里走系统文件选择器会把每张图拖成 90 秒超时。
            opened["upload_blocked"] = "spec-picker-unavailable"
    rest = opened.get("rest") if isinstance(opened, dict) else None
    confirmed_batches = [entry for entry in rest if isinstance(entry, dict)
                         and entry.get("via") == "batch"
                         and isinstance(entry.get("result"), dict)
                         and entry["result"].get("uploaded") is True] if isinstance(rest, list) else []
    if confirmed_batches and sum(int(entry.get("count") or 0) for entry in confirmed_batches) >= len(pending_files):
        opened["uploaded"] = True
        opened["verifiedBy"] = confirmed_batches[-1]["result"].get("verifiedBy") or "upload-batch"
    uploaded = opened
    if not (script in {"spec_images.js", "main_images.js"} and opened.get("uploaded") is True):
        try:
            uploaded = run_script(session, script, {**payload, "phase": "after_upload", "files": pending_files,
                                                    "uploadNames": opened.get("missing") or []}, timeout=180)
        except FileChooserNeeded:
            # Verification must never turn a stale native dialog into another
            # submission of the first image. Close it, then verify once more.
            _dismiss_filechooser(session)
            try:
                uploaded = run_script(session, script, {**payload, "phase": "after_upload", "files": pending_files,
                                                        "uploadNames": opened.get("missing") or []}, timeout=180)
            except Exception as exc:
                if _is_user_pause(exc):
                    raise
                uploaded = {"uploaded": False, "after_err": str(exc)[:200]}
        except Exception as exc:
            if _is_user_pause(exc):
                raise
            uploaded = {"uploaded": False, "after_err": str(exc)[:200], "open": opened}
    _check_cancel(session)
    uploaded, retry_log = _retry_failed_image_uploads(session, script, payload, files, opened, uploaded)
    if retry_log and isinstance(opened, dict):
        opened = {**opened, "cli_retries": retry_log}
    if (isinstance(uploaded, dict) and uploaded.get("uploaded") is False
            and not (opened.get("already") or opened.get("skipUpload") or opened.get("via") == "library")):
        status = _upload_status(uploaded)
        count = status.get("successCount")
        detail = f"（上传结果 {count}/{len(pending_files)}）" if count is not None else ""
        missing = uploaded.get("missing") or []
        if missing:
            detail += "（素材库未找到：" + "、".join(str(name) for name in missing[:3])
            detail += "等）" if len(missing) > 3 else "）"
        reason = uploaded.get("error") or "未确认所有目标图片上传成功"
        raise RuntimeError(f"图片上传失败：{reason}{detail}，已停止绑定")
    def bind_once(bind_payload):
        try:
            return run_script(session, script, bind_payload, timeout=180)
        except FileChooserNeeded:
            _dismiss_filechooser(session)
            try:
                return run_script(session, script, bind_payload, timeout=180)
            except FileChooserNeeded:
                _dismiss_filechooser(session)
                return {"error": "filechooser", "picked": []}
            except Exception as exc:
                if _is_user_pause(exc):
                    raise
                return {"error": str(exc)[:200]}

    bind_payload = {**payload, "phase": pick_phase, "files": files}
    if script == "spec_images.js" and payload.get("onlyRows"):
        # 分批补图：只绑定本批行，JS 侧按 onlyRows 校验这些行已写入 SKU 表格。
        bound = bind_once(bind_payload)
        if not isinstance(bound, dict) or bound.get("error") or bound.get("hadFrame") is False:
            reason = bound.get("error") if isinstance(bound, dict) else "未返回绑定结果"
            raise RuntimeError(f"规格图未绑定到指定行：{reason or '素材库未加载'}")
    elif script == "spec_images.js" and len(payload.get("skus") or []) > 5:
        bind_log = []
        total = len(payload["skus"])
        for start in range(0, total, 5):
            end = min(start + 5, total)
            bound = bind_once({**bind_payload, "bindStart": start, "bindEnd": end})
            if not isinstance(bound, dict) or bound.get("error") or bound.get("hadFrame") is False:
                reason = bound.get("error") if isinstance(bound, dict) else "未返回绑定结果"
                raise RuntimeError(f"规格图未绑定到SKU {start}/{total}：{reason or '素材库未加载'}")
            bind_log.extend(bound.get("bindLog") or [])
            if on_bind_progress:
                on_bind_progress(end, total)
            if bound.get("saved") is True:
                break
            if end < total and (bound.get("partial") is not True or len(bound.get("bindLog") or []) != end - start):
                raise RuntimeError(f"规格图未绑定到SKU {end}/{total}：批次结果不完整")
            _check_cancel(session)
        bound["bindLog"] = bind_log
    else:
        bound = bind_once(bind_payload)
    _verify_image_binding(script, payload, bound)
    return {"open": opened, "upload": uploaded, "bind": bound}


def complete_current_product(session, product, confirm_submit=True, web=None):
    """在已打开的卡游新建页补完并入库，不覆盖得力页。"""
    web = web or _load_web()
    payload = product_to_payload(product)
    steps = []
    execution = "失败"
    notice = ""
    _write_progress([])
    session.attach()
    href = select_kayou_tab(session)
    web.assert_safe_url(href)
    steps.append({"step": "resume-tab", "url": href})
    _write_progress(steps)
    try:
        listed = session.tab_list()
        if _looks_like_filechooser(listed):
            _dismiss_filechooser(session)
        try:
            session.press("Escape")
        except Exception as exc:
            if _looks_like_filechooser(exc):
                _dismiss_filechooser(session)
            else:
                pass

        def _safe_script(name, timeout=120):
            try:
                return run_script(session, name, payload, timeout=timeout)
            except FileChooserNeeded:
                _dismiss_filechooser(session)
                return run_script(session, name, payload, timeout=timeout)

        if payload["main_images"]:
            main = _image_step(session, "main_images.js", {
                "files": payload["main_images"],
                "names": [Path(p).name for p in payload["main_images"]],
                "field": "#sell-field-mainImagesGroup",
                **_human_upload_policy(),
            }, payload["main_images"])
            steps.append({"step": "main_1_1", **main})
            _write_progress(steps)

        if payload["detail_images"]:
            details = _image_step(session, "details.js", {
                "files": payload["detail_images"],
                "names": [Path(p).name for p in payload["detail_images"]],
                **_human_upload_policy(),
            }, payload["detail_images"])
            steps.append({"step": "details", **details})
            _write_progress(steps)

        attributes = _safe_script("attributes.js", 150)
        steps.append({"step": "attributes", "result": attributes})
        tags = _safe_script("fill_tags.js", 60)
        steps.append({"step": "tags", "result": tags})
        _write_progress(steps)

        if payload["skus"]:
            cats = _safe_script("sku_category.js", 90)
            steps.append({"step": "sku_category", "result": cats})
            _write_progress(steps)
            specs = spec_images_gate(session, payload, steps)

        logistics = run_script(session, "logistics.js", payload, timeout=90)
        steps.append({"step": "logistics", "result": logistics})
        _write_progress(steps)

        result = _finish_publish(session, payload, confirm_submit, web, steps)
        execution = result.get("execution") or execution
        notice = result.get("notice") or notice
        return result
    except Exception as exc:
        execution = "暂停" if "PAUSE:" in str(exc) or hard_pause_reason(str(exc)) else "失败"
        notice = short_fail_notice(str(exc)) or str(exc)[:160]
        try:
            if web.is_publish_page(session.href()):
                run_script(session, "warehouse.js", {}, timeout=40)
        except Exception:
            pass
        return {
            "execution": execution,
            "notice": notice,
            "errors": [notice],
            "steps": steps,
            "url": "",
        }
    finally:
        _write_progress(steps + [{"step": "end", "execution": execution, "notice": notice}])


def _dismiss_import_dialog(session):
    """关闭残留的批量导入弹窗；skus.js 的 dismissBlockingDialogs 不覆盖该弹窗。"""
    try:
        run_script(session, "close_import_dialog.js", {}, timeout=30)
    except Exception:
        pass


def _reveal_automation_window():
    """还原最小化/隐藏的自动化窗口；虚拟滚动表格在最小化窗口里停止渲染。"""
    try:
        web = _load_web()
        if hasattr(web, "restore_automation_chrome"):
            web.reload_paths()
            web.restore_automation_chrome()
    except Exception:
        pass


def _topup_missing_sku_rows(session, payload, request, steps, result, path):
    """核验行数不足时的恢复路径：还原窗口后复核，仍缺再用编辑器逐值补齐。

    SKU 表格是虚拟滚动，DOM 只渲染约一屏的行（37 行恒显示 17 行），
    verify 已改为滚动累加计数；走到这里说明深度扫描也确认缺行——通常是
    最小化窗口里表格重建被冻结，还原窗口即可补完，其次才是 skus.js 补值。
    """
    try:
        count = int(result.get("count") or 0)
        expected = int(result.get("expected") or len(payload.get("skus") or []))
    except (TypeError, ValueError):
        return result
    if result.get("error") or count >= expected:
        return result
    steps.append({"step": "sku_import",
                  "result": {"partial_topup": True, "count": count, "expected": expected}})
    _write_progress(steps)
    _dismiss_import_dialog(session)
    _reveal_automation_window()
    time.sleep(2)
    result = run_script(session, "sku_import.js", {**request, "phase": "verify"}, timeout=120)
    if not result.get("verified") and not result.get("error"):
        # skus.js 会跳过已存在的规格值并补齐价格/数量，无重复行风险。
        run_gate(session, "skus.js", {**payload, "skip_thickness": True}, steps, "sku_seed", timeout=600)
        result = run_script(session, "sku_import.js", {**request, "phase": "verify"}, timeout=120)
    return result


def import_skus_from_template(session, payload, steps):
    """Create the SKU table when needed, then upload and verify the template."""
    template = Path(os.environ.get("QIANNIU_TEMPLATES_DIR") or ROOT / "templates") / "sku_import_50012720.xls"
    directory = Path(os.environ.get("QIANNIU_RESULTS_DIR") or get_output()) / "sku-import"
    try:
        path = sku_import.build_import_file(payload, template, directory)
    except (ValueError, FileNotFoundError) as exc:
        steps.append({"step": "sku_import", "result": {"error": str(exc)[:180]}})
        _write_progress(steps)
        raise RuntimeError(f"PAUSE:SKU 模板生成失败：{exc}") from exc
    request = {"file": str(path), "skus": payload["skus"]}
    try:
        opened = run_script(session, "sku_import.js", {**request, "phase": "open"}, timeout=60)
    except FileChooserNeeded:
        session.upload_files(str(path), timeout=90)
        opened = {"uploaded": True, "via": "filechooser"}
    if opened.get("unavailable"):
        first_attempt = opened
        steps.append({"step": "sku_import", "result": {"retry_after_seed": True, "diagnostics": first_attempt}})
        _write_progress(steps)
        # Qianniu may render the import button only after the SKU table exists.
        # Seed one row through the established editor, then import the full file.
        seed = {**payload, "skus": payload["skus"][:1]}
        run_gate(session, "skus.js", seed, steps, "sku_seed", timeout=90, attempts=1)
        try:
            opened = run_script(session, "sku_import.js", {**request, "phase": "open"}, timeout=60)
        except FileChooserNeeded:
            session.upload_files(str(path), timeout=90)
            opened = {"uploaded": True, "via": "filechooser"}
        if opened.get("unavailable"):
            reason = str(opened.get("reason") or "未找到 SKU 批量导入入口")
            steps.append({"step": "sku_import", "result": {"unavailable": True, "reason": reason, "initial": first_attempt, "after_seed": opened}})
            _write_progress(steps)
            raise RuntimeError(f"PAUSE:{reason}；已停止，避免逐项填写")
    if not opened.get("uploaded"):
        try:
            session.upload_files(str(path), timeout=90)
        except Exception as exc:
            raise RuntimeError("PAUSE:SKU 模板导入入口已打开，但文件选择器不可用，请检查千牛页面") from exc
    try:
        result = run_script(session, "sku_import.js", {**request, "phase": "verify"}, timeout=120)
    except Exception as exc:
        raise RuntimeError(f"PAUSE:SKU 模板已上传但结果未核实，请检查当前页面：{short_fail_notice(str(exc))}") from exc
    steps.append({"step": "sku_import", "result": {**result, "file": str(path)}})
    _write_progress(steps)
    if not result.get("verified"):
        result = _topup_missing_sku_rows(session, payload, request, steps, result, path)
        steps.append({"step": "sku_import", "result": {**result, "file": str(path), "after_topup": True}})
        _write_progress(steps)
    if not result.get("verified"):
        if result.get("error"):
            detail = str(result["error"])[:180]
        elif result.get("addedDimensions"):
            names = "、".join(map(str, result["addedDimensions"]))
            detail = f"已添加{names}，规格行仅核实 {result.get('matched', 0)}/{result.get('expected', len(payload['skus']))}"
        elif result.get("recognitionClicked"):
            detail = f"识别已确认，规格行仅核实 {result.get('matched', 0)}/{result.get('expected', len(payload['skus']))}"
        else:
            detail = "未能完成确认识别或规格行核对"
        raise RuntimeError(f"PAUSE:SKU 模板已上传但{detail}，请检查当前页面后继续")
    return True


VIDEO_UPLOAD_TIMEOUT = 420


def _playable_video_checker():
    """加载 商品解析.is_playable_video；解析器不可用时返回 None（放行不阻塞）。"""
    try:
        import 商品解析 as parser
    except Exception:
        try:
            spec = importlib.util.spec_from_file_location(
                "qianniu_video_check", Path(__file__).resolve().parents[1] / "商品解析.py")
            parser = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(parser)
        except Exception:
            return None
    return getattr(parser, "is_playable_video", None)


def video_step(session, payload):
    """上传主视频到商品视频区。视频是可选项：失败一律告警跳过，不阻断入库。

    只有用户主动暂停和平台安全验证（滑块/验证码，PAUSE 类异常）才会中断流程；
    视频自身的失败以 warning 结果返回，由调用方记录后继续。
    """
    _check_cancel(session)
    files = [payload["main_video"]]
    checker = _playable_video_checker()
    if checker is not None and not checker(files[0]):
        return {"uploaded": False, "skipped": True,
                "warning": "主视频文件无法播放（扩展名是视频但内容不是有效视频），已跳过上传"}
    request = {"files": files, "names": [Path(files[0]).name], "phase": "open"}
    result = None
    try:
        result = run_script(session, "main_video.js", request, timeout=VIDEO_UPLOAD_TIMEOUT)
    except FileChooserNeeded:
        # 发布页“上传视频”点内层文字会弹原生文件选择器（与 SKU 模板导入同一
        # 机制）。把视频交给 pending 的选择器后只做复核，不重复投递。
        try:
            session.upload_files(files[0], timeout=180)
        except Exception as exc:
            if _is_user_pause(exc):
                raise
            _dismiss_filechooser(session)
            return {"uploaded": False,
                    "warning": f"视频文件选择器不可用，已跳过视频：{short_fail_notice(str(exc))}"}
        try:
            result = run_script(session, "main_video.js", {**request, "phase": "verify"}, timeout=180)
        except Exception as exc:
            if _is_user_pause(exc):
                raise
            result = {"error": short_fail_notice(str(exc)) or str(exc)[:160]}
    except Exception as exc:
        if _is_user_pause(exc):
            raise
        # 其余运行异常视为视频自身失败：记录后跳过，不阻断入库。
        result = {"error": short_fail_notice(str(exc)) or str(exc)[:160]}
    if not isinstance(result, dict):
        return {"uploaded": False, "warning": "视频上传结果未确认，已跳过视频"}
    if result.get("already") or result.get("uploaded"):
        return result
    if result.get("need_cli_upload") and not _upload_dispatched(result):
        # 页面内没有可用上传入口、需要原生文件选择器时，由 CLI 代投一次后复核。
        try:
            session.upload_files(files[0], timeout=180)
        except Exception as exc:
            if _is_user_pause(exc):
                raise
            _dismiss_filechooser(session)
            return {"uploaded": False,
                    "warning": f"视频文件选择器不可用，已跳过视频：{short_fail_notice(str(exc))}"}
        try:
            result = run_script(session, "main_video.js", {**request, "phase": "verify"}, timeout=180)
        except Exception as exc:
            if _is_user_pause(exc):
                raise
            result = {"error": short_fail_notice(str(exc)) or str(exc)[:160]}
        if isinstance(result, dict) and (result.get("already") or result.get("uploaded")):
            return result
    reason = short_fail_notice(str(result.get("error") or "")) or "未确认主视频上传成功"
    detail = str(result.get("detail") or "")
    if detail:
        reason = f"{reason}：{detail}"
    return {"uploaded": False, "warning": f"主视频未上传，已跳过继续：{reason}"}


def _close_video_dialog(session):
    """关闭残留的“选择视频”对话框；失败不阻断入库。

    视频按可选项策略失败跳过后对话框常驻页面，其 videoSelector iframe 与
    图片空间同域且 URL 形似，会把详情步骤的图片空间定位劫持到视频对话框，
    导致详情图被当成视频投递（2026-09-30 真实页面复现）。
    """
    try:
        return run_script(session, "close_video_dialog.js", {}, timeout=60)
    except FileChooserNeeded:
        _dismiss_filechooser(session)
        return None
    except Exception as exc:
        if _is_user_pause(exc):
            raise
        return None


def fill_new_product(session, product, confirm_submit=False, web=None, force_new=False, sku_template_import=False, skip_spec_images=False):
    web = web or _load_web()
    payload = product_to_payload(product)
    steps = []
    execution = "失败"
    notice = ""
    completed = set()
    checkpoint_ready = False
    _write_progress([])
    try:
        _check_cancel(session)
        href, how = ensure_fill_tab(session, web, force_new=force_new)
        steps.append({"step": "tab", "url": href, "how": how})
        _write_progress(steps)

        skips = set()
        if how == "reuse-publish":
            state = _probe_fill_state(session, payload)
            if not state:
                raise RuntimeError("PAUSE:无法读取当前发布页，已保留现场，请稍后继续")
            skips = decide_skips(state, payload)
            steps.append({
                "step": "probe",
                "result": {key: state.get(key) for key in (
                    "title", "skuRows", "specImgs", "mainImgs", "p34Imgs", "detailImgs", "videos", "popup", "specDialog"
                )},
                "skips": sorted(skips),
            })
            _write_progress(steps)
            if page_conflicts(state, payload):
                href = ensure_new_category_tab(session, web)
                how = "new-category"
                skips = set()
                steps.append({"step": "tab", "url": href, "how": "conflict-new-category"})
                _write_progress(steps)
            else:
                if (state.get("checkpoint") or {}).get("key") == resume_key(payload):
                    completed.update(state["checkpoint"].get("completed", []))
                continue_spec = bool(payload.get("skus")) and "spec_images" not in skips
                dialog_open = bool(state.get("specDialog") or state.get("popup"))
                pending_media = any(payload.get(key) and skip not in skips for key, skip in (
                    ("main_images", "main_images"), ("portrait_images", "portraits"),
                    ("detail_images", "details"), ("main_video", "video"),
                ))
                if dialog_open and (pending_media or not continue_spec):
                    _maybe_close_overlays(session)

        if how != "reuse-publish":
            category = run_gate(session, "category.js", payload, steps, "category", timeout=90)
            web.assert_safe_url(session.href())
            if not web.is_publish_page(session.href()):
                raise RuntimeError("未进入新建发布页: " + session.href())
        else:
            steps.append({"step": "category", "result": {"skipped": True, "reason": how, "url": href, "skips": sorted(skips)}})
            _write_progress(steps)

        checkpoint_ready = True
        completed.add("category")
        _save_checkpoint(session, payload, completed)

        # The publish page must exist first; upload product media before any
        # attribute work, SKU template import, or per-SKU image binding.
        if payload["main_images"]:
            if "main_images" in skips:
                steps.append({"step": "main_1_1", "skipped": True})
                _write_progress(steps)
            else:
                main = _image_step(session, "main_images.js", {
                    "files": payload["main_images"],
                    "names": [Path(p).name for p in payload["main_images"]],
                    "field": "#sell-field-mainImagesGroup",
                    **_human_upload_policy(),
                }, payload["main_images"])
                steps.append({"step": "main_1_1", **main})
                _write_progress(steps)
            completed.add("main_images")
            _save_checkpoint(session, payload, completed)

        if payload["portrait_images"]:
            if "portraits" in skips:
                steps.append({"step": "main_3_4", "skipped": True})
                _write_progress(steps)
            else:
                portraits = _image_step(session, "main_images.js", {
                    "files": payload["portrait_images"],
                    "names": [Path(p).name for p in payload["portrait_images"]],
                    "field": "#sell-field-threeToFourImages",
                    **_human_upload_policy(),
                }, payload["portrait_images"])
                steps.append({"step": "main_3_4", **portraits})
                _write_progress(steps)
            completed.add("portraits")
            _save_checkpoint(session, payload, completed)

        if payload["main_video"]:
            if "video" in skips:
                steps.append({"step": "video", "skipped": True})
                _write_progress(steps)
            else:
                video = video_step(session, payload)
                steps.append({"step": "video", **video})
                _write_progress(steps)
            _close_video_dialog(session)
            completed.add("video")
            _save_checkpoint(session, payload, completed)

        if payload["detail_images"]:
            if "details" in skips:
                steps.append({"step": "details", "skipped": True})
                _write_progress(steps)
            else:
                details = _image_step(session, "details.js", {
                    "files": payload["detail_images"],
                    "names": [Path(p).name for p in payload["detail_images"]],
                    **_human_upload_policy(),
                }, payload["detail_images"])
                steps.append({"step": "details", **details})
                _write_progress(steps)
            completed.add("details")
            _save_checkpoint(session, payload, completed)

        if "attributes" in skips:
            steps.append({"step": "attributes", "result": {"skipped": True}})
            _write_progress(steps)
        else:
            attributes = run_gate(session, "attributes.js", payload, steps, "attributes", timeout=150)
        completed.add("attributes")
        _save_checkpoint(session, payload, completed)

        if payload["skus"]:
            if "skus" in skips:
                steps.append({"step": "skus", "result": {"skipped": True}})
                _write_progress(steps)
            else:
                if sku_template_import and sku_import.supports_product(payload):
                    import_skus_from_template(session, payload, steps)
                    cats = run_gate(session, "sku_category.js", payload, steps, "sku_category", timeout=150)
                    # 分类脚本自带逐屏终检（audit）；行不全就在建品前判失败，
                    # 断点不标记 skus，条目级重试会重新执行整个 SKU 步骤。
                    if isinstance(cats, dict) and cats.get("audit") and not cats.get("ok"):
                        raise RuntimeError(
                            f"SKU 规格分类未写入全部规格行"
                            f"（页面 {cats.get('total')} 行，未分类 {cats.get('missing')} 行）；将重新处理 SKU 步骤")
                else:
                    skus = run_gate(session, "skus.js", payload, steps, "skus", timeout=300)

            if "spec_images" in skips or skip_spec_images:
                steps.append({"step": "spec_images", "skipped": True, "skip_spec_images": bool(skip_spec_images)})
                _write_progress(steps)
            else:
                specs = spec_images_gate(session, payload, steps)
            completed.update({"skus", "spec_images"})
            _save_checkpoint(session, payload, completed)

        logistics = run_script(session, "logistics.js", payload, timeout=90)
        steps.append({"step": "logistics", "result": logistics})
        _write_progress(steps)

        result = _finish_publish(session, payload, confirm_submit, web, steps)
        execution = result.get("execution") or execution
        notice = result.get("notice") or notice
        return result
    except UserStopped as exc:
        execution, notice = "暂停", str(exc).removeprefix("PAUSE:")
        return {"execution": execution, "notice": notice, "errors": [], "url": session.href(), "steps": steps}
    except web.SessionLost as exc:
        execution, notice = "暂停", str(exc)
        raise
    except SpecRowsMismatch as exc:
        # 规格行与输入不符：丢弃 skus/spec_images 断点标记，finally 重存
        # checkpoint 时同步生效；条目级重试会重新执行 SKU 步骤。
        completed.discard("skus")
        completed.discard("spec_images")
        execution, notice = "暂停", str(exc).removeprefix("PAUSE:")
        return {"execution": execution, "notice": notice, "errors": [notice], "url": session.href(), "steps": steps}
    except Exception as exc:
        execution = "暂停" if "PAUSE:" in str(exc) or hard_pause_reason(str(exc)) else "失败"
        notice = short_fail_notice(str(exc)) or str(exc)[:160]
        return {
            "execution": execution,
            "notice": notice,
            "errors": [notice],
            "url": session.href() if session else "",
            "steps": steps,
        }
    finally:
        try:
            if checkpoint_ready and web.is_publish_page(session.href()):
                _save_checkpoint(session, payload, completed)
            # A paused/failed flow must not close the upload/verification UI.
            # Warehouse selection is also enforced before any real submission.
            if execution not in {"暂停", "失败"} and session and web.is_publish_page(session.href()):
                run_script(session, "warehouse.js", {}, timeout=40)
        except Exception:
            pass
        _write_progress(steps + [{"step": "end", "execution": execution, "notice": notice}])


def _emit_flow(item, product, on_flow_stage):
    if on_flow_stage:
        try:
            on_flow_stage(product, item)
        except Exception:
            pass


def _spec_stage_callbacks(item, product, on_flow_stage, touch_flow_stage=True):
    """规格图分批补传的进度回调：每批提交前后落盘阶段与提示。

    touch_flow_stage=False 用于 both 策略——flow_stage 此时表示搜索主图素材
    阶段，不能被规格图批次覆盖。
    """
    from . import material_import

    def before_submit():
        item["spec_image_stage"] = material_import.STAGE_SUBMIT_PENDING
        if touch_flow_stage:
            item.update(flow_stage=material_import.STAGE_SUBMIT_PENDING,
                        flow_version=SPEC_COLUMN_FLOW_VERSION)
        _emit_flow(item, product, on_flow_stage)
        _remember_item(product, item)

    def after_batch(batch_index, remaining, total_rows):
        item.update(spec_image_stage=SPEC_STAGE_UPLOADING,
                    execution="已入库，补规格图中",
                    notice=f"规格图第 {batch_index} 批已保存，待补 {remaining} 行（共 {total_rows} 行图片）")
        if touch_flow_stage:
            item["flow_stage"] = material_import.STAGE_CREATED
        _emit_flow(item, product, on_flow_stage)
        _remember_item(product, item)

    return before_submit, after_batch


def _parse_tabs_with_current(text):
    """解析 tab-list 输出为 [(index, url, is_current)]。

    CLI 输出行形如 "- 2: (current) [标题](https://...)"；与 parse_tabs 的
    区别是额外保留当前页签标记：重开的编辑页 URL 完全相同，靠 URL 分不清
    哪个是 CLI 正在使用的页，必须用 "(current)" 标记。
    """
    tabs = []
    for line in str(text or "").splitlines():
        match = re.search(r"(https?://\S+)", line)
        if not match:
            continue
        index_match = re.search(r"^\s*-\s*(\d+):", line) or re.search(r"(\d+)", line)
        tabs.append((int(index_match.group(1)) if index_match else len(tabs),
                     match.group(1).rstrip("],)"),
                     bool(re.search(r"^\s*-\s*\d+:\s*\(current\)", line))))
    return tabs


def _is_item_publish_url(url, item_id):
    """是否指定商品的编辑页签；忽略站点加载后附加的 fr 等参数。"""
    from urllib.parse import parse_qs, urlparse
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return False
    if (parsed.hostname or "").lower() != "item.upload.taobao.com":
        return False
    if not parsed.path.lower().endswith("/publish.htm"):
        return False
    return parse_qs(parsed.query).get("itemId") == [str(item_id)]


def _is_safe_park_url(url):
    """可停靠页签：卖家中心/登录页。prune 始终保留它们，切过去不会失效。"""
    from urllib.parse import urlparse
    text = str(url or "").strip()
    if not text.lower().startswith("http"):
        return False
    host = (urlparse(text).hostname or "").lower()
    return (host == "myseller.taobao.com" or host.endswith(".myseller.taobao.com")
            or "login" in text.lower())


def _close_stale_item_tabs(session, item_id, keep_current=True):
    """按 itemId 关闭商品编辑页签，返回关闭数量。

    逐个关闭且每次关闭前重新拉取页签列表：tab_close 会让后续序号重排，
    复用旧序号有关错页签的风险。keep_current 时必须解析到 "(current)"
    标记才动手，解析不到宁可不动，避免把 CLI 正在使用的页签关掉。
    """
    closed = 0
    for _ in range(30):
        try:
            rows = _parse_tabs_with_current(session.tab_list())
        except Exception:
            break
        current_index = next((index for index, _url, current in rows if current), None)
        if keep_current and current_index is None:
            break
        victim = next((index for index, url, current in rows
                       if _is_item_publish_url(url, item_id)
                       and not (keep_current and index == current_index)), None)
        if victim is None:
            break
        try:
            session.tab_close(victim)
            closed += 1
        except Exception:
            break
        time.sleep(0.2)
    return closed


def _open_item_edit_tab(session, item_id):
    """新开指定商品的编辑页签，并回收同商品的历史编辑页签。

    分批补图每批都会重开编辑页；重开页与历史页 URL 相同，prune 的精确
    匹配保留规则分不清哪个是"当前页"，同商品页签只会越积越多。这里先
    新开（新页即当前页），再按 itemId 关掉其余页签，保证同商品至多一个。
    """
    url = "https://item.upload.taobao.com/sell/v2/publish.htm?itemId=" + str(item_id)
    session.tab_new(url)
    try:
        _close_stale_item_tabs(session, item_id, keep_current=True)
    except Exception:
        pass
    return url


def _recycle_success_tabs(session, item_id):
    """成功核验的商品回收其全部编辑页签，返回关闭数量。

    成功商品不需要保留现场（断点续跑只依赖商品 ID），但不能让 CLI 的
    当前页签失效：当前页正是该商品的编辑页时，先切到卖家中心/登录页再
    关；找不到可停靠页签时退化为只关多余页签、保留当前页。
    """
    try:
        rows = _parse_tabs_with_current(session.tab_list())
    except Exception:
        return 0
    if not any(_is_item_publish_url(url, item_id) for _index, url, _current in rows):
        return 0
    current_index = next((index for index, _url, current in rows if current), None)
    current_is_item = current_index is not None and any(
        index == current_index and _is_item_publish_url(url, item_id)
        for index, url, _current in rows)
    if current_is_item:
        park = next((index for index, url, _current in rows
                     if index != current_index and _is_safe_park_url(url)), None)
        if park is not None:
            try:
                session.tab_select(park)
                time.sleep(0.3)
            except Exception:
                pass
    return _close_stale_item_tabs(session, item_id, keep_current=True)


def _finish_product_tabs(session, web, item):
    """单条商品收尾的页签治理。

    成功核验的商品立即回收其编辑页签；其余状态保留当前页作为断点续跑
    现场。两种情况都会顺带清掉其他历史页签。
    """
    if item.get("run_status") == "completed" and str(item.get("taobao_item_id") or ""):
        try:
            _recycle_success_tabs(session, str(item["taobao_item_id"]))
        except Exception:
            pass
    try:
        _prune_tabs(web, keep_url=session.href())
    except Exception:
        pass


def _recover_existing_item(session, web, product, item_id):
    """Read a fresh server page before migrating an ID-only legacy record.

    Never reuse an unsaved edit tab or submit again to discover whether the
    previous submission succeeded. A failed check leaves the record unchanged.
    """
    from urllib.parse import parse_qs, urlparse
    from . import material_import

    if not re.fullmatch(r"\d{8,20}", item_id):
        raise RuntimeError("PAUSE:已有商品 ID 无效；禁止再次建品")
    payload = product_to_payload(product)
    _open_item_edit_tab(session, item_id)
    state = run_script(session, "probe_state.js", {**payload, "waitForReady": True})
    risk = run_script(session, "upload_status.js", {})
    if (state.get("captchaVisible") or risk.get("securityChallenge")
            or (risk.get("status") or {}).get("securityLimit")):
        # 机器检测到的安全验证必须带显式码：文案里没有“验证码/滑块”字样，
        # 只靠关键词兜底会被误判为可重试错误，导致验证期间被反复尝试。
        raise RuntimeError("PAUSE:captcha:已有商品核验遇到安全验证；未修改或重新提交商品")
    url = urlparse(state.get("href") or "")
    if (url.hostname != "item.upload.taobao.com"
            or url.path != "/sell/v2/publish.htm"
            or parse_qs(url.query).get("itemId") != [item_id]):
        raise RuntimeError("PAUSE:未打开指定商品的服务器编辑页；禁止再次建品")
    expected_title = display_title(payload["title"])
    if state.get("title") != expected_title:
        # 带上页面实际商品标题：ID 被污染时（历史缺陷会把别的商品的 ID 刮进
        # 失败记录），用户能直接看出该 ID 属于哪个商品，放心清除记录。
        raise RuntimeError(
            "PAUSE:已有商品 ID 的标题与输入不符"
            + (f"（页面商品：{state.get('title')}）" if state.get("title") else "")
            + "；禁止再次建品"
        )
    wanted = [sku["name"] for sku in payload.get("skus") or []]
    # 规格表是虚拟滚动表格，probe_state 的 skuNames/skuRows 只含可视区（约一屏
    # 17 行），对超过一屏的商品必然误报"不符"（2026-10-01 连续三次误报，商品
    # 实际是完整的 37 行）。改用 sku_import.js 的 audit 阶段逐屏深扫描做全量
    # 比对；audit 只读，允许在已有商品编辑页执行。
    audit = run_script(session, "sku_import.js", {"phase": "audit", "skus": payload.get("skus") or []}, timeout=120)
    if not isinstance(audit, dict) or not audit.get("audit"):
        raise RuntimeError("PAUSE:已有商品 SKU 深扫描未完成，无法核实规格行；禁止再次建品")
    if audit.get("count") != len(wanted) or audit.get("missing") or audit.get("extra"):
        detail = f"页面 {audit.get('count')} 行 / 输入 {len(wanted)} 行"
        missing = list(audit.get("missing") or [])
        extra = list(audit.get("extra") or [])
        if missing:
            detail += f"；缺失 {'、'.join(map(str, missing[:3]))}" + ("等" if len(missing) > 3 else "")
        if extra:
            detail += f"；多出 {'、'.join(map(str, extra[:3]))}" + ("等" if len(extra) > 3 else "")
        raise RuntimeError(f"PAUSE:已有商品的 SKU 与输入不符（{detail}）；禁止再次建品")
    for field, count in (("main_images", "mainImgs"), ("detail_images", "detailImgs")):
        if state.get(count, 0) != len(payload.get(field) or []):
            raise RuntimeError("PAUSE:已有商品的主图或详情图数量不完整；保留商品，禁止再次建品")
    if not any(row.get("checked") and row.get("t") == "放入仓库"
               for row in state.get("warehouse") or []):
        raise RuntimeError("PAUSE:已有商品未确认处于仓库；禁止再次建品")
    rows = material_import.inspect_target_skus(session, web, item_id, expected_title)
    material_import.check_rows(rows, product)
    return rows


def _spec_column_state(session, product):
    """Read only specification cells; a search-main thumbnail is not evidence."""
    state = run_script(session, "spec_row_status.js", {}, timeout=40)
    skus = product.get("skus") or []
    # Taobao reloads saved images as protocol-relative URLs. Preserve the full
    # host/path/query identity while ignoring only that transport spelling.
    sources = {int(row["index"]): re.sub(r"^https?:", "", row.get("src") or "")
               for row in state.get("sources") or []}
    if state.get("total") != len(skus):
        raise RuntimeError("PAUSE:商品规格列行数不符，不能确认规格图片")
    missing = [i for i, sku in enumerate(skus, 1) if sku.get("image") and not sources.get(i)]
    return sources, missing


def _repair_existing_spec_images(session, web, product, item_id, confirm_submit,
                                 on_before_submit=None, spec_batch_size=0,
                                 on_batch_done=None):
    """Repair only the existing item's spec images; never create another item.

    规格图分批补传：每批最多 spec_batch_size 行（0 表示全部一次），流程为
    重新打开服务器编辑页 → 读取规格列缺失行 → 只补本批行 → 保存商品 →
    退出编辑页 → 下一批。已保存的行每次从服务器状态读取，天然支持断点续传；
    已上传到图片空间的文件不会重复上传。
    """
    from . import material_import
    baseline = _recover_existing_item(session, web, product, item_id)
    payload = {**product_to_payload(product), "repairItemId": item_id}
    skus = payload.get("skus") or []
    total_with_image = len([sku for sku in skus if sku.get("image")])
    batch_size = max(0, int(spec_batch_size or 0))
    steps = []
    batch_index = 0
    while True:
        _open_item_edit_tab(session, item_id)
        state = run_script(session, "probe_state.js", {**payload, "waitForReady": True})
        risk = run_script(session, "upload_status.js", {})
        if (state.get("captchaVisible") or risk.get("securityChallenge")
                or (risk.get("status") or {}).get("securityLimit")):
            raise RuntimeError("PAUSE:captcha:商品编辑页遇到安全验证；未修改或重新提交商品")
        before, missing = _spec_column_state(session, product)
        if not missing:
            break
        if ((product.get("flow_version") == SPEC_COLUMN_FLOW_VERSION
                and product.get("flow_stage") == material_import.STAGE_SUBMIT_PENDING)
                or product.get("spec_image_stage") == material_import.STAGE_SUBMIT_PENDING):
            raise RuntimeError("PAUSE:上次规格图保存结果不明确；禁止自动重复提交")
        if not confirm_submit:
            raise RuntimeError("PAUSE:已有商品缺少商品规格图；确认提交后可补图，不会重复建品")
        batch = missing[:batch_size] if batch_size else missing
        batch_index += 1
        steps.append({"step": "spec_images", "batch": batch_index, "rows": list(batch),
                      "pendingRows": len(missing), "batchSize": batch_size or None})
        _write_progress(steps)
        spec_images_gate(session, payload, steps, only_rows=[row - 1 for row in batch],
                         progress_offset=total_with_image - len(missing),
                         progress_total=total_with_image,
                         min_filled_count=total_with_image - (len(missing) - len(batch)))
        bound_sources, _ = _spec_column_state(session, product)
        unresolved = [row for row in batch if not bound_sources.get(row)]
        if unresolved:
            raise RuntimeError("PAUSE:商品规格图未完整写入，未提交")
        errors = run_script(session, "probe_errors.js", payload, timeout=40)
        if required_blockers(errors):
            raise RuntimeError("PAUSE:已有商品存在必填属性错误；补规格图不会自动修改商品属性")
        if on_before_submit:
            on_before_submit()
        result = _finish_publish(session, payload, True, web, steps)
        if material_import.item_id_from_result(result) != item_id:
            raise RuntimeError("PAUSE:规格图保存结果待核实；禁止自动重复提交")
        if on_batch_done:
            on_batch_done(batch_index, len(missing) - len(batch), total_with_image)
        # 本批已保存：退出编辑页，下一批重新打开服务器页面。
        _prune_tabs(web, keep_url=session.href())
    # Reopen server data, verify baseline values and then the exact target cell
    # sources. Do not accept a picker preview or a search-main material receipt.
    rows = _recover_existing_item(session, web, product, item_id)
    material_import.check_rows(rows, product, baseline)
    _open_item_edit_tab(session, item_id)
    run_script(session, "probe_state.js", {**payload, "waitForReady": True})
    after, missing = _spec_column_state(session, product)
    if missing or any(after.get(i) != src for i, src in before.items() if src):
        raise RuntimeError("PAUSE:刷新后商品规格图缺失或变化，未标记完成")
    return {"flow_version": SPEC_COLUMN_FLOW_VERSION, "flow_stage": material_import.STAGE_COMPLETE,
            "spec_image_stage": material_import.STAGE_COMPLETE,
            "sku_image_strategy": material_import.STRATEGY_PUBLISH,
            "execution": "已入库，图片已核验", "run_status": "completed",
            "notice": "商品规格图已保存并刷新核验（非 SKU 搜索主图）",
            "errors": [], "last_error": "", "steps": steps}


def _run_search_images(session, web, product, item, on_flow_stage=None, combined=False):
    """Resume the search-main import without treating specification images as proof."""
    from . import material_import

    state = {
        "stage": material_import.normalize_stage(item.get("flow_stage") or material_import.STAGE_CREATED),
        "baseline": item.get("sku_material_manifest") or [],
        "preview": item.get("material_preview") or item.get("material_result") or [],
        "folder": item.get("material_folder") or "",
        "material_root": str(material_import.material_root()),
        "product_key": str(product.get("product_id") or product.get("row") or ""),
    }
    stage_map = {
        "created": "material_baseline",
        "material_prepared": "material_prepare",
        "material_upload_pending": "material_upload",
        "material_recognizing": "material_recognize",
        "material_reviewed": "material_review",
        "material_adopt_pending": "material_adopt",
        "material_verifying": "material_verify",
    }

    def on_stage(stage, current):
        item["flow_stage"] = stage
        item["sku_material_manifest"] = current.get("baseline") or item.get("sku_material_manifest") or []
        item["material_folder"] = current.get("folder") or item.get("material_folder") or ""
        item["material_result"] = current.get("verified") or []
        item["material_preview"] = current.get("preview") or item.get("material_preview") or []
        if current.get("notice"):
            item["notice"] = current["notice"]
        _write_progress([{"step": stage_map.get(stage, stage), "stage": stage}])
        _emit_flow(item, product, on_flow_stage)

    finished = material_import.run_material_flow(
        session, web, product, item["taobao_item_id"], state, on_stage=on_stage
    )
    if material_import.normalize_stage(finished.get("stage")) != material_import.STAGE_COMPLETE:
        raise RuntimeError("PAUSE:搜索主图流程未到完成阶段，保留当前断点")
    item.update(
        flow_stage=material_import.STAGE_COMPLETE,
        flow_version=BOTH_IMAGE_FLOW_VERSION if combined else material_import.FLOW_VERSION,
        execution="已入库，图片已核验" if combined else "已入库，搜索主图已核验",
        notice=("商品规格图和 SKU 搜索主图均已刷新核验" if combined
                else "SKU 搜索主图已采纳并复核；销售规格图未执行"),
        run_status="completed", errors=[], last_error="",
    )


def run_batch(products, confirm_submit=False, limit=None, session=None, cancel_event=None,
              on_item_start=None, on_item_done=None, force_new=False, sku_template_import=False,
              skip_spec_images=False, sku_image_strategy="", on_flow_stage=None,
              spec_upload_batch_size=0, item_retry_limit=0, on_item_retry=None):
    """批量执行上架流程。

    spec_upload_batch_size：入库后进编辑页每批补传的规格图行数；0 表示全部
    一次上传。skip_spec_images 为兼容保留的旧参数，建品阶段现在一律不传
    规格图，规格图统一在拿到商品 ID 后按批次补传。
    item_retry_limit：条目失败后的自动重试次数；重试用尽或遇不可重试失败
    （安全验证、提交待核实、结果不明确类）时标记该条并继续下一条，整批
    不再因单条失败中断。on_item_retry(product, item, attempt, limit) 在每次
    自动重试前回调。
    """
    _write_progress([])
    web = _load_web()
    selected = list(products or [])
    if limit:
        selected = selected[:limit]
    if not selected:
        return []
    own_session = session is None
    session = session or web.CliSession()
    session.cancel_event = cancel_event
    session.attach()
    href = session.href()
    web.assert_logged_in(href, session.snapshot())
    try:
        _prune_tabs(web, keep_url=href, keep_fill_pages=True)
    except Exception:
        pass
    from . import material_import

    updated = []
    need_new_tab = False
    current_account = ""
    try:
        current_account = session.seller_account() if hasattr(session, "seller_account") else ""
    except Exception:
        current_account = ""
    product_index = 0
    retry_limit = max(0, int(item_retry_limit or 0))
    attempt_state = None   # (product_index, attempt)；仅发生过重试时非 None
    resume_state = None    # (product_index, state)；重试时暂存上一轮推进到的断点状态
    outcome = ""
    while product_index < len(selected):
        product = selected[product_index]
        if resume_state is not None and resume_state[0] == product_index:
            product = dict(product)
            product.update(resume_state[1])
        attempt = attempt_state[1] if attempt_state is not None and attempt_state[0] == product_index else 1
        if cancel_event is not None and cancel_event.is_set():
            item = dict(product)
            item["execution"] = "已停止"
            item["notice"] = "用户停止任务"
            item["errors"] = []
            item["run_status"] = "stopped"
            updated.append(item)
            if on_item_done:
                on_item_done(product, item)
            _remember_item(product, item, status="stopped")
            break
        item = dict(product)
        item.setdefault("flow_version", material_import.FLOW_VERSION)
        snapshot_strategy = str(product.get("sku_image_strategy") or "")
        strategy = resolve_sku_strategy(product, sku_image_strategy or snapshot_strategy)
        item["sku_image_strategy"] = strategy
        prior_stage = material_import.normalize_stage(product.get("flow_stage") or "pending")
        prior_id = str(product.get("taobao_item_id") or "")
        # 历史缺陷清洗：失败记录的 ID 可能来自被拒 URL 的文本刮取（"拒绝使用
        # 已有商品编辑页"文案里带着上一条商品的 itemId），不属于本商品。
        # 命中指纹时丢弃，按全新建品处理；成功后会被真实 ID 覆盖。
        prior_notice = str(product.get("notice") or "")
        if prior_id and "拒绝使用已有商品编辑页" in prior_notice and prior_id in prior_notice:
            import job_session
            if str(product.get("execution") or "") in job_session.FAIL_EXECUTIONS:
                prior_id = ""
                item["taobao_item_id"] = ""
        saved_account = str(product.get("seller_account") or "").strip()
        if saved_account and current_account and saved_account != current_account and prior_id:
            item["execution"] = "暂停"
            item["notice"] = "当前店铺与上次执行店铺不一致，已停止以免沿用其他店铺的商品 ID"
            item["errors"] = [item["notice"]]
            item["run_status"] = "paused"
            updated.append(item)
            if on_item_done:
                on_item_done(product, item)
            _remember_item(product, item, status="paused")
            break
        if current_account and not saved_account:
            item["seller_account"] = current_account
        legacy_record = not (product.get("flow_version") or product.get("flow_stage"))
        prior = str(product.get("execution") or "")
        if not force_new and not prior_id and legacy_record and prior in DONE_EXECUTIONS:
            item["execution"] = prior
            item["notice"] = product.get("notice") or "已填写，跳过"
            item["errors"] = list(product.get("errors") or [])
            updated.append(item)
            if on_item_done:
                on_item_done(product, item)
            need_new_tab = True
            product_index += 1
            continue
        if (not force_new and not legacy_record and prior_stage == material_import.STAGE_COMPLETE
                and strategy == material_import.STRATEGY_PUBLISH
                and product.get("flow_version") == SPEC_COLUMN_FLOW_VERSION):
            item["execution"] = product.get("execution") or "已入库，图片已核验"
            item["notice"] = product.get("notice") or "已完成，跳过"
            item["errors"] = list(product.get("errors") or [])
            updated.append(item)
            if on_item_done:
                on_item_done(product, item)
            need_new_tab = True
            product_index += 1
            continue
        if (not force_new and not legacy_record and prior_stage == material_import.STAGE_COMPLETE
                and strategy == "both" and product.get("flow_version") == BOTH_IMAGE_FLOW_VERSION):
            item["execution"] = product.get("execution") or "已入库，图片已核验"
            item["notice"] = product.get("notice") or "两类图片已核验"
            item["errors"] = list(product.get("errors") or [])
            updated.append(item)
            if on_item_done:
                on_item_done(product, item)
            need_new_tab = True
            product_index += 1
            continue
        _write_progress([])
        if on_item_start:
            on_item_start(product)
        item_force_new = bool(force_new) or need_new_tab
        # 规格图统一在入库成功后按批次进入编辑页补传（降低一次性上传触发
        # 滑块验证的概率），建品阶段不再上传任何规格图。
        skip_spec = True
        try:
            if prior_id and not force_new and strategy == "both":
                # Keep the material checkpoint separate from a pending spec save.
                search_stage = (prior_stage if product.get("flow_version") in
                                {material_import.FLOW_VERSION, BOTH_IMAGE_FLOW_VERSION}
                                else material_import.STAGE_CREATED)
                if search_stage == material_import.STAGE_COMPLETE:
                    search_stage = material_import.STAGE_VERIFYING
                item.update(flow_version=BOTH_IMAGE_FLOW_VERSION, flow_stage=search_stage)

                before_both_spec_submit, after_both_spec_batch = _spec_stage_callbacks(
                    item, product, on_flow_stage, touch_flow_stage=False)

                _repair_existing_spec_images(session, web, product, prior_id,
                                             confirm_submit, on_before_submit=before_both_spec_submit,
                                             spec_batch_size=spec_upload_batch_size,
                                             on_batch_done=after_both_spec_batch)
                item["spec_image_stage"] = material_import.STAGE_COMPLETE
                item["flow_stage"] = search_stage
                _emit_flow(item, product, on_flow_stage)
                if confirm_submit and any(s.get("image") for s in product.get("skus") or []):
                    _run_search_images(session, web, product, item, on_flow_stage, combined=True)
                elif confirm_submit:
                    item.update(flow_stage=material_import.STAGE_COMPLETE,
                                execution="已入库，图片已核验", run_status="completed",
                                notice="该商品没有 SKU 图片，已核验商品状态")
                else:
                    item.update(execution="已入库，规格图已核验", run_status="paused",
                                notice="搜索主图待确认提交后处理")
                updated.append(item)
                if on_item_done:
                    on_item_done(product, item)
                _emit_flow(item, product, on_flow_stage)
                _remember_item(product, item)
                _finish_product_tabs(session, web, item)
                need_new_tab = True
                product_index += 1
                continue
            if prior_id and not force_new and strategy == material_import.STRATEGY_SLIM:
                if product.get("flow_version") == SPEC_COLUMN_FLOW_VERSION:
                    # Specification completion is not search-main completion.
                    # Resolve a possibly pending save before beginning a different flow.
                    if prior_stage == material_import.STAGE_SUBMIT_PENDING:
                        raise RuntimeError("PAUSE:上次规格图提交结果待核实；核实后才能切换搜索主图流程")
                    prior_stage = material_import.STAGE_CREATED
                    item.update(flow_stage=prior_stage, sku_material_manifest=[],
                                material_preview=[], material_result=[], material_folder="")
                elif prior_stage == material_import.STAGE_COMPLETE:
                    # Re-read persisted server state, never re-upload a completed import.
                    prior_stage = material_import.STAGE_VERIFYING
                    item["flow_stage"] = prior_stage
                item["flow_version"] = material_import.FLOW_VERSION
            if prior_id and not force_new and strategy == material_import.STRATEGY_PUBLISH:
                # Old 'complete' referred to search-main images. Re-verify and
                # repair the real specification column without building an item.
                item["flow_stage"] = material_import.STAGE_CREATED
                item.update(errors=[], last_error="", notice="正在核验商品规格图")
                before_spec_submit, after_spec_batch = _spec_stage_callbacks(item, product, on_flow_stage)
                item.update(_repair_existing_spec_images(session, web, product, prior_id,
                            confirm_submit, on_before_submit=before_spec_submit,
                            spec_batch_size=spec_upload_batch_size,
                            on_batch_done=after_spec_batch))
                updated.append(item)
                if on_item_done:
                    on_item_done(product, item)
                _emit_flow(item, product, on_flow_stage)
                _remember_item(product, item)
                _finish_product_tabs(session, web, item)
                need_new_tab = True
                product_index += 1
                continue
            if (prior_id and not force_new and prior_stage in {
                    material_import.STAGE_FILLED, material_import.STAGE_SUBMIT_PENDING}):
                # Legacy ID-only records must never fall through to new-product
                # creation. Migrate only after read-only server/SKU checks pass.
                rows = _recover_existing_item(session, web, product, prior_id)
                if strategy != material_import.STRATEGY_SLIM:
                    raise RuntimeError("PAUSE:已有商品已定位；原发布图片仍待核验，未重复建品")
                prior_stage = material_import.STAGE_CREATED
                item.update(flow_version=material_import.FLOW_VERSION,
                            flow_stage=prior_stage, sku_material_manifest=rows,
                            errors=[], notice="已有商品已核验，继续 SKU 素材流程，不重新建品")
                _emit_flow(item, product, on_flow_stage)
            if prior_stage in {
                material_import.STAGE_CREATED,
                material_import.STAGE_PREPARED,
                material_import.STAGE_UPLOAD_PENDING,
                material_import.STAGE_RECOGNIZING,
                material_import.STAGE_REVIEWED,
                material_import.STAGE_ADOPT_PENDING,
                material_import.STAGE_VERIFYING,
            } and prior_id and not force_new:
                # 已有商品 ID：只续跑补图，不重新建品。
                item["flow_stage"] = prior_stage
                item["execution"] = "已入库，待补图"
                result = item
            elif prior_stage == material_import.STAGE_SUBMIT_PENDING and not force_new:
                raise RuntimeError("PAUSE:上次提交结果不明确；禁止自动重复提交，请核实仓库后继续")
            else:
                kwargs = {"confirm_submit": confirm_submit, "web": web, "force_new": item_force_new}
                if sku_template_import:
                    kwargs["sku_template_import"] = True
                if skip_spec:
                    kwargs["skip_spec_images"] = True
                result = fill_new_product(session, product, **kwargs)
                item.update(result)
                if item.get("execution") not in {"失败", "暂停", "提交失败"} and "errors" not in result:
                    item["errors"] = []
                if confirm_submit and item.get("execution") not in {"失败", "暂停", "提交失败"}:
                    created = material_import.item_id_from_result(item)
                    if created:
                        item["taobao_item_id"] = created
                        item["flow_stage"] = material_import.STAGE_CREATED
                        _emit_flow(item, product, on_flow_stage)
                    else:
                        item["flow_stage"] = material_import.STAGE_SUBMIT_PENDING
                        item["execution"] = "提交待核实"
                        item["notice"] = item.get("notice") or "提交结果待核实"
                        _emit_flow(item, product, on_flow_stage)
                elif not confirm_submit and item.get("execution") not in {"失败", "暂停", "提交失败"}:
                    item["flow_stage"] = material_import.STAGE_FILLED
            outcome = ""
            pause_blob = " ".join([str(item.get("notice") or ""), *(str(e) for e in item.get("errors") or [])])
            if item.get("execution") == "暂停" and (hard_pause_reason(pause_blob) or pause_reason_code(pause_blob)):
                # 安全验证类硬暂停（登录/验证码/滑块）：重试无法通过，标记后
                # 跳下一条，全部跑完后由桌面端统一汇总需人工处理的条目。
                item["run_status"] = "paused"
                outcome = "hard"
            elif item.get("flow_stage") == material_import.STAGE_SUBMIT_PENDING:
                # 提交结果不明确：按规则禁止自动重复提交，标记后跳下一条。
                item["run_status"] = "paused"
                outcome = "submit_pending"
            elif item.get("execution") in {"失败", "暂停", "提交失败"}:
                # 建品失败/暂停立即终止该商品的后续动作：不再打开 SKU 管理页，
                # 也不允许素材阶段的状态覆盖建品阶段留下的失败信息。
                item["run_status"] = "paused" if item["execution"] == "暂停" else "error"
                outcome = "failed"
            # 入库成功后进入官方素材导入；serial 单商品闭环。
            if confirm_submit and not outcome and strategy == material_import.STRATEGY_SLIM and item.get("taobao_item_id"):
                _run_search_images(session, web, product, item, on_flow_stage)
            elif confirm_submit and not outcome and strategy in {material_import.STRATEGY_PUBLISH, "both"} and item.get("execution") not in {"失败", "暂停", "提交失败", "提交待核实"}:
                if any(s.get("image") for s in product.get("skus") or []):
                    # 入库成功后按批次进入编辑页补传规格图并逐批保存；
                    # 每批保存后重开服务器页面复核，避免一次性上传触发滑块。
                    before_created, after_created = _spec_stage_callbacks(item, product, on_flow_stage)
                    verified_spec = _repair_existing_spec_images(
                        session, web, product, item["taobao_item_id"], True,
                        on_before_submit=before_created,
                        spec_batch_size=spec_upload_batch_size,
                        on_batch_done=after_created)
                    if strategy == "both":
                        item["spec_image_stage"] = material_import.STAGE_COMPLETE
                    else:
                        item.update(verified_spec)
                else:
                    item.update(flow_stage=material_import.STAGE_COMPLETE,
                                flow_version=SPEC_COLUMN_FLOW_VERSION)
                if strategy == "both" and item.get("taobao_item_id"):
                    item.update(flow_version=BOTH_IMAGE_FLOW_VERSION,
                                flow_stage=material_import.STAGE_CREATED)
                    _emit_flow(item, product, on_flow_stage)
                    if any(s.get("image") for s in product.get("skus") or []):
                        _run_search_images(session, web, product, item, on_flow_stage, combined=True)
                    else:
                        item.update(flow_stage=material_import.STAGE_COMPLETE,
                                    execution="已入库，图片已核验", run_status="completed",
                                    notice="该商品没有 SKU 图片，已核验商品状态")
        except web.SessionLost as exc:
            # 登录失效：重试无法通过，标记后跳下一条。
            item["execution"] = "暂停"
            item["notice"] = str(exc)
            item["errors"] = [str(exc)]
            item["run_status"] = "paused"
            outcome = "hard"
        except Exception as exc:
            pause = "PAUSE:" in str(exc) or hard_pause_reason(str(exc))
            item["execution"] = "暂停" if pause else "失败"
            notice = str(exc).replace("PAUSE:", "", 1).strip() if pause else str(exc)
            # 建品已失败但记录已有商品 ID 的续跑场景：素材阶段错误只记入
            # last_error，保留建品失败作为用户可见 notice，避免误导。
            if item.get("taobao_item_id") and item.get("errors"):
                item["notice"] = "; ".join(str(e) for e in item.get("errors") if e) or item.get("notice") or notice
                item["errors"] = list(item.get("errors") or [])
            else:
                item["notice"] = notice
                item["errors"] = [notice]
            item["last_error"] = str(exc)
            item["run_status"] = "paused" if pause else "error"
            outcome = "failed"
        # —— 条目级重试 / 跳过决策 ——
        failure = outcome in {"hard", "submit_pending", "failed"} or item.get("execution") in {
            "失败", "暂停", "提交失败", "提交待核实"}
        retryable = (
            outcome == "failed"
            and attempt <= retry_limit
            and not (cancel_event is not None and cancel_event.is_set())
            and item_retryable_notice(item.get("notice"), item.get("errors"))
        )
        if retryable:
            # 从断点续跑：把本次尝试推进到的状态合并回商品，下一轮尝试按
            # 既有断点（flow_stage + 页面 checkpoint）接着填，不从头重做。
            merged = dict(product)
            for key in ("flow_version", "flow_stage", "spec_image_stage", "taobao_item_id",
                        "view_url", "edit_url", "url", "seller_account", "sku_image_strategy",
                        "sku_material_manifest", "material_result", "material_preview",
                        "material_folder", "last_error"):
                if item.get(key) not in (None, ""):
                    merged[key] = item[key]
            merged["execution"] = item.get("execution") or ""
            merged["notice"] = item.get("notice") or ""
            merged["run_status"] = ""
            if on_item_retry:
                on_item_retry(merged, item, attempt, retry_limit)
            for cleanup in (_maybe_close_overlays, _dismiss_import_dialog):
                try:
                    cleanup(session)
                except Exception:
                    pass
            attempt_state = (product_index, attempt + 1)
            resume_state = (product_index, merged)
            continue
        # 终局：成功，或重试用尽/不可重试的失败 —— 落库后进入下一条。
        updated.append(item)
        product_index += 1
        need_new_tab = True
        if on_item_done:
            on_item_done(product, item)
        _emit_flow(item, product, on_flow_stage)
        _remember_item(product, item, status="paused" if outcome in {"hard", "submit_pending"}
                       else ("error" if item.get("execution") in {"失败", "暂停", "提交失败"} else None))
        if not failure:
            _finish_product_tabs(session, web, item)
        if cancel_event is not None and cancel_event.is_set():
            break
    keep_url = ""
    if updated and updated[-1].get("execution") in {"失败", "暂停", "提交失败", "已停止", "已填写未提交", "提交待核实"}:
        try:
            keep_url = session.href()
        except Exception:
            pass
    if own_session:
        try:
            session.detach()
        except Exception:
            pass
    try:
        _prune_tabs(web, keep_url=keep_url, keep_fill_pages=bool(keep_url))
    except Exception:
        pass
    return updated


def resolve_naruto_product():
    import importlib.util
    spec = importlib.util.spec_from_file_location("seller", ROOT / "千牛自动上架.py")
    seller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seller)
    pack_dir = seller.naruto_pack_dir()
    pack = seller.scan_image_pack(pack_dir)
    templates = seller.load_templates({"attributes": "中性笔", "logistics": "48小时", "sales": "仓库多规格"})
    row = {
        "商品标识*": "火影-001",
        "商品标题*": "卡游火影忍者中性笔盲盒忍道版",
        "品牌*": "卡游",
        "型号": "忍道版第1弹",
        "价格*": 9.9,
        "库存*": 20,
        "图片包路径*": str(pack_dir),
        "商品属性模板*": "中性笔",
        "物流模板*": "48小时",
        "销售模板*": "仓库多规格",
    }
    product = seller.resolve_product(row, [], pack, templates, pack_dir.parent)
    errors = seller.validate_product(product)
    if errors:
        raise ValueError("火影示例校验失败: " + "; ".join(errors))
    return product
